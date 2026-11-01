"""Background indexer: resumable, incremental and throttled.

Each batch of passages commits with the progress that describes it, so a kill or power cut resumes
from the last batch with no duplicates. Files are only ever read here, never changed.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import signal
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from . import CATEGORIES, DEFAULT_CATEGORY, FORMATS, extract, store

log = logging.getLogger("survival-indexer")

BATCH_PAGES = 20
BATCH_CHARS = 256 * 1024
MAX_ATTEMPTS = 3
FLOOR_FRACTION = 0.15
# Room to keep beyond the floor for index growth, per location of the next document.
INDEX_BYTES_PER_PAGE = 16 * 1024
SCAN_INTERVAL = 300
IDLE_POLL = 5


@dataclass(frozen=True)
class Paths:
    state: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(Path(os.environ.get("SURVIVAL_STATE_DIR", "state")))

    @property
    def library(self) -> Path:
        return self.state / "library"

    @property
    def database(self) -> Path:
        return self.state / "index" / "library.db"

    @property
    def rescan_flag(self) -> Path:
        return self.state / "index" / "rescan"

    @property
    def status_file(self) -> Path:
        return self.state / "index" / "indexer.json"


def bytes_above_floor(path: Path) -> int:
    """Space left before the 15% floor, measured the way System Status reports it."""
    stats = os.statvfs(path)
    available = stats.f_bavail * stats.f_frsize
    used = (stats.f_blocks - stats.f_bfree) * stats.f_frsize
    return available - int((used + available) * FLOOR_FRACTION)


def write_status(paths: Paths, state: str, detail: str = "") -> None:
    paths.status_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.status_file.with_suffix(".tmp")
    temporary.write_text(json.dumps({"state": state, "detail": detail, "time": time.time()}))
    temporary.replace(paths.status_file)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def category_of(relative: Path) -> str:
    return relative.parts[0] if len(relative.parts) > 1 and relative.parts[0] in CATEGORIES \
        else DEFAULT_CATEGORY


def library_files(root: Path) -> dict[str, Path]:
    found = {}
    for directory, folders, names in os.walk(root):
        folders[:] = [name for name in folders if not name.startswith(".")]
        for name in names:
            path = Path(directory, name)
            if not name.startswith(".") and path.suffix.lower() in FORMATS \
                    and not path.is_symlink():
                found[path.relative_to(root).as_posix()] = path
    return found


def add_document(db: sqlite3.Connection, relative: str, path: Path, digest: str) -> None:
    fmt = FORMATS[path.suffix.lower()]
    stats = path.stat()
    state, error, title, total = "pending", None, "", 0
    try:
        title, total = extract.document_info(path, fmt)
    except extract.ExtractionError as failure:
        state, error = "failed", str(failure)
    db.execute(
        "INSERT INTO documents (path, title, format, category, size, mtime_ns, sha256, state,"
        " pages_total, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (relative, title or path.stem, fmt, category_of(Path(relative)), stats.st_size,
         stats.st_mtime_ns, digest, state, total, error),
    )


def scan(db: sqlite3.Connection, root: Path) -> int:
    """Bring the catalog in line with the library folder. Return the number of changes."""
    root.mkdir(parents=True, exist_ok=True)
    files = library_files(root)
    known = {row["path"]: row for row in db.execute("SELECT * FROM documents")}
    gone = {path: row for path, row in known.items() if path not in files}
    changes = 0

    for relative, path in files.items():
        stats = path.stat()
        row = known.get(relative)
        if row and row["size"] == stats.st_size and row["mtime_ns"] == stats.st_mtime_ns:
            continue
        digest = sha256(path)
        if row:
            if row["sha256"] == digest:
                db.execute("UPDATE documents SET mtime_ns=? WHERE id=?",
                           (stats.st_mtime_ns, row["id"]))
            else:
                db.execute("DELETE FROM documents WHERE id=?", (row["id"],))
                add_document(db, relative, path, digest)
        else:
            moved = next((old for old in gone.values() if old["sha256"] == digest), None)
            if moved:
                del gone[moved["path"]]
                db.execute("UPDATE documents SET path=?, category=?, mtime_ns=? WHERE id=?",
                           (relative, category_of(Path(relative)), stats.st_mtime_ns, moved["id"]))
            else:
                add_document(db, relative, path, digest)
        db.commit()
        changes += 1

    for row in gone.values():
        db.execute("DELETE FROM documents WHERE id=?", (row["id"],))
        db.commit()
        changes += 1
    return changes


class Indexer:
    def __init__(self, paths: Paths, pause_ratio: float = 1.0, ocr: bool = False,
                 batch_pages: int = BATCH_PAGES) -> None:
        self.paths = paths
        self.pause_ratio = pause_ratio
        self.ocr = ocr and extract.ocr_available()
        self.batch_pages = batch_pages
        self.stopping = False
        self.db = store.connect(paths.database)

    def stop(self, *_: object) -> None:
        self.stopping = True

    def _flush(self, doc_id: int, batch: list[extract.Location]) -> None:
        rows = [(doc_id, location.page, location.label, part)
                for location in batch for part in extract.chunks(location.text)]
        self.db.executemany(
            "INSERT INTO passages (document_id, page, label, text) VALUES (?, ?, ?, ?)", rows)
        self.db.execute(
            "UPDATE documents SET pages_done=?, pages_no_text=pages_no_text+?, attempts=0"
            " WHERE id=?",
            (batch[-1].page, sum(location.no_text for location in batch), doc_id))
        self.db.commit()

    def _fail(self, doc_id: int, message: str) -> None:
        self.db.rollback()
        self.db.execute("DELETE FROM passages WHERE document_id=?", (doc_id,))
        self.db.execute("UPDATE documents SET state='failed', error=?, pages_done=0 WHERE id=?",
                        (message, doc_id))
        self.db.commit()

    def index_document(self, doc: sqlite3.Row) -> None:
        doc_id = doc["id"]
        if doc["attempts"] >= MAX_ATTEMPTS:
            # A malformed file that kills the extractor must not stop the rest of the library.
            self._fail(doc_id, "The indexer stopped repeatedly on this file")
            return
        self.db.execute("UPDATE documents SET state='indexing', attempts=attempts+1 WHERE id=?",
                        (doc_id,))
        self.db.commit()

        path = self.paths.library / doc["path"]
        batch: list[extract.Location] = []
        started = time.monotonic()
        try:
            for location in extract.locations(path, doc["format"], doc["pages_done"], self.ocr):
                batch.append(location)
                size = sum(len(item.text) for item in batch)
                if len(batch) >= self.batch_pages or size >= BATCH_CHARS:
                    self._flush(doc_id, batch)
                    batch = []
                    time.sleep((time.monotonic() - started) * self.pause_ratio)
                    started = time.monotonic()
                    if self.stopping:
                        return
            if batch:
                self._flush(doc_id, batch)
        except extract.ExtractionError as failure:
            self._fail(doc_id, str(failure))
            return
        except OSError as failure:
            self._fail(doc_id, f"File could not be read: {failure.strerror}")
            return
        self.db.execute("UPDATE documents SET state='done', error=NULL WHERE id=?", (doc_id,))
        self.db.commit()

    def next_document(self) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM documents WHERE state IN ('pending', 'indexing')"
            " ORDER BY state='pending', id LIMIT 1").fetchone()

    def run_pending(self) -> None:
        while not self.stopping and (doc := self.next_document()):
            needed = max(doc["pages_total"], 1) * INDEX_BYTES_PER_PAGE
            if bytes_above_floor(self.paths.state) < needed:
                write_status(self.paths, "paused", "Storage is at the 15% free floor")
                return
            write_status(self.paths, "indexing", doc["title"])
            self.index_document(doc)
        write_status(self.paths, "idle")

    def run_once(self) -> None:
        self.paths.state.mkdir(parents=True, exist_ok=True)
        write_status(self.paths, "scanning")
        if scan(self.db, self.paths.library):
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.run_pending()

    def run_forever(self) -> None:
        # The monotonic clock starts near zero at boot, so the first scan must not wait for it.
        last_scan = -SCAN_INTERVAL
        while not self.stopping:
            due = time.monotonic() - last_scan >= SCAN_INTERVAL
            if due or self.paths.rescan_flag.exists():
                self.paths.rescan_flag.unlink(missing_ok=True)
                self.run_once()
                last_scan = time.monotonic()
            time.sleep(IDLE_POLL)
        write_status(self.paths, "stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Index the SURVIVAL OS library")
    parser.add_argument("--once", action="store_true", help="scan, index, then exit")
    parser.add_argument("--pause-ratio", type=float,
                        default=float(os.environ.get("SURVIVAL_INDEX_PAUSE", "1.0")),
                        help="seconds to rest per second of work")
    parser.add_argument("--ocr", action="store_true",
                        default=os.environ.get("SURVIVAL_OCR") == "1",
                        help="read scanned pages with tesseract, if it is installed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    indexer = Indexer(Paths.from_env(), args.pause_ratio, args.ocr)
    signal.signal(signal.SIGTERM, indexer.stop)
    signal.signal(signal.SIGINT, indexer.stop)
    if args.ocr and not shutil.which("tesseract"):
        log.warning("OCR requested but tesseract is not installed")
    if args.once:
        indexer.run_once()
    else:
        indexer.run_forever()
