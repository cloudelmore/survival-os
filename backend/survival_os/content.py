"""Content catalog, category accounting and the storage rules.

Every operation passes `check` first, and again before each later step. The check counts what the
operation needs at its peak, so a download that would cross the 15% floor never starts.
"""

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

GB = 1_000_000_000
FLOOR_FRACTION = 0.15
WARN_FRACTION = 0.8
EMPTY_KIWIX_LIBRARY = '<library version="20110515"></library>\n'

SCHEMA = """
CREATE TABLE IF NOT EXISTS installed (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    format TEXT NOT NULL,
    category TEXT NOT NULL,
    path TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    origin TEXT NOT NULL,
    checksum_source TEXT NOT NULL,
    installed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT '',
    bytes_done INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS updates (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    source_url TEXT NOT NULL,
    bytes INTEGER NOT NULL
);
"""


class Refused(Exception):
    """A storage rule stopped the operation. The message is shown to the user."""


@dataclass(frozen=True)
class Paths:
    state: Path
    catalog: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(Path(os.environ.get("SURVIVAL_STATE_DIR", "state")),
                   Path(os.environ.get("SURVIVAL_CATALOG_DIR", "content-manifests")))

    @property
    def content(self) -> Path:
        return self.state / "content"

    @property
    def database(self) -> Path:
        return self.content / "content.db"

    @property
    def partial(self) -> Path:
        return self.content / "partial"

    @property
    def zim(self) -> Path:
        return self.content / "zim"

    @property
    def ai(self) -> Path:
        return self.state / "ai"

    @property
    def maps(self) -> Path:
        return self.state / "maps"

    @property
    def library(self) -> Path:
        return self.state / "library"

    @property
    def kiwix_library(self) -> Path:
        return self.content / "kiwix-library.xml"


def connect(paths: Paths) -> sqlite3.Connection:
    paths.content.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(paths.database, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def load_budgets(paths: Paths) -> dict[str, dict]:
    budgets = json.loads((paths.catalog / "budgets.json").read_text())
    return {item["id"]: item for item in budgets["categories"]}


def load_catalog(paths: Paths) -> dict[str, dict]:
    return {entry["id"]: entry for entry in (
        json.loads(path.read_text()) for path in sorted((paths.catalog / "catalog").glob("*.json")))}


def capacity(path: Path) -> dict[str, int]:
    """Measure the real filesystem, reserved blocks excluded, as STORAGE_PLAN.md defines it."""
    stats = os.statvfs(path)
    available = stats.f_bavail * stats.f_frsize
    usable = stats.f_frsize * (stats.f_blocks - (stats.f_bfree - stats.f_bavail))
    floor = int(usable * FLOOR_FRACTION)
    return {"usable": usable, "available": available, "floor": floor,
            "headroom": max(available - floor, 0)}


def tree_bytes(path: Path) -> int:
    total = 0
    for directory, _, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(Path(directory, name)).st_blocks * 512
            except OSError:
                pass
    return total


def category_usage(paths: Paths) -> dict[str, int]:
    """Bytes in each budget category. Each file counts once, in the one place it is stored."""
    used = dict.fromkeys(load_budgets(paths), 0)
    db = connect(paths)
    with db:
        tracked = db.execute("SELECT category, sum(bytes) AS total FROM installed"
                             " WHERE path NOT LIKE 'library/%' GROUP BY category").fetchall()
    db.close()
    for row in tracked:
        used[row["category"]] += row["total"]
    if paths.library.is_dir():
        for folder in paths.library.iterdir():
            if folder.is_dir() and folder.name in used:
                used[folder.name] += tree_bytes(folder)
            elif folder.is_file():
                used["personal"] += tree_bytes(folder)
    used["ai_indexes"] += tree_bytes(paths.state / "index")
    return used


def check(paths: Paths, category: str, peak_bytes: int, final_bytes: int) -> None:
    """Refuse an operation that would cross the floor or its category ceiling."""
    room = capacity(paths.state)
    if peak_bytes > room["headroom"]:
        raise Refused(f"Needs {peak_bytes / GB:.2f} GB but only {room['headroom'] / GB:.2f} GB"
                      " is left above the 15% free floor")
    cap = load_budgets(paths)[category]
    used = category_usage(paths)[category]
    if used + final_bytes > cap["cap_gb"] * GB:
        raise Refused(f"{cap['name']} would pass its {cap['cap_gb']} GB ceiling")


def summary(paths: Paths) -> dict:
    budgets = load_budgets(paths)
    used = category_usage(paths)
    room = capacity(paths.state)
    filesystem_used = room["usable"] - room["available"]
    # Whatever no category claims is the system itself, so the rows add up to the disk.
    used["os_apps"] = max(filesystem_used - sum(used.values()), 0)
    spent = filesystem_used / max(room["usable"] - room["floor"], 1)
    return {
        **room,
        "used": filesystem_used,
        "warning": spent >= WARN_FRACTION,
        "categories": [{"id": key, "name": item["name"], "cap_bytes": item["cap_gb"] * GB,
                        "used_bytes": used[key]} for key, item in budgets.items()],
    }


def destination(paths: Paths, entry: dict) -> Path:
    relative = PurePosixPath(entry["destination"])
    if entry["format"] == "zim":
        return paths.zim / relative.name
    if entry["format"] in ("firmware", "software"):
        return paths.content / entry["format"] / relative.name
    if entry["format"] == "pmtiles":
        return paths.maps / relative.name
    if entry["format"] == "model":
        return paths.ai / relative.name
    return paths.library / entry["budget_category"] / relative.name


def stored_path(paths: Paths, path: Path) -> str:
    return path.relative_to(paths.state).as_posix()


def enqueue(db: sqlite3.Connection, action: str, target: str) -> int:
    active = db.execute("SELECT id FROM jobs WHERE action=? AND target=?"
                        " AND state IN ('queued', 'running')", (action, target)).fetchone()
    if active:
        return active["id"]
    cursor = db.execute("INSERT INTO jobs (action, target, created_at) VALUES (?, ?, ?)",
                        (action, target, time.time()))
    db.commit()
    return cursor.lastrowid


def overview(paths: Paths) -> dict:
    catalog = load_catalog(paths)
    db = connect(paths)
    with db:
        installed = {row["id"]: dict(row) for row in db.execute("SELECT * FROM installed")}
        updates = {row["id"]: dict(row) for row in db.execute("SELECT * FROM updates")}
        jobs = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 20")]
    db.close()
    entries = []
    for key, entry in catalog.items():
        entries.append({
            "id": key, "title": entry["title"], "publisher": entry["publisher"],
            "format": entry["format"], "category": entry["budget_category"],
            "summary": entry.get("summary", ""),
            "bytes": entry["size_bytes"]["value"], "bytes_status": entry["size_bytes"]["status"],
            "license": entry["license"]["value"], "license_status": entry["license"]["status"],
            "checksum_status": entry["sha256"]["status"],
            "date": entry["publication_date"]["value"],
            "installed": installed.pop(key, None), "update": updates.get(key),
        })
    return {"entries": entries, "imported": list(installed.values()), "jobs": jobs}
