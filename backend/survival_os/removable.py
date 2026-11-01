"""Import from removable media. The drive is mounted read-only by a small root helper."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from survival_search import CATEGORIES, FORMATS

from . import content
from .content import Paths, Refused

MOUNT_ROOT = Path(os.environ.get("SURVIVAL_USB_ROOT", "/run/survival-usb"))
SERVICE = ["/usr/bin/sudo", "-n", "/usr/bin/systemctl"]
BLOCK = 1024 * 1024


def run_helper(action: str) -> bool:
    verb = "start" if action == "mount" else "stop"
    result = subprocess.run([*SERVICE, verb, "survival-usb.service"], capture_output=True,
                            timeout=60)
    return result.returncode == 0


def scan(root: Path = MOUNT_ROOT) -> list[dict]:
    """List importable files. `path` is relative to the mount, so a job can name it safely."""
    found = []
    for path in sorted(root.rglob("*")) if root.is_dir() else ():
        suffix = path.suffix.lower()
        if path.is_symlink() or not path.is_file() or (suffix != ".zim" and suffix not in FORMATS):
            continue
        found.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                      "format": "zim" if suffix == ".zim" else FORMATS[suffix]})
    return found


def _resolve(relative: str, root: Path) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise Refused("That file is no longer on the drive")
    return path


def import_file(worker, job_id: int, target: str, root: Path = MOUNT_ROOT) -> None:
    """Copy one file in, unless an identical file is already installed."""
    request = json.loads(target)
    source = _resolve(request["path"], root)
    category = request["category"]
    paths: Paths = worker.paths
    allowed = content.load_budgets(paths) if source.suffix.lower() == ".zim" else CATEGORIES
    if category not in allowed:
        raise Refused("Choose a subject for this file")
    size = source.stat().st_size
    worker.update_job(job_id, phase="checking for a copy", bytes_total=size)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while block := handle.read(BLOCK):
            digest.update(block)
    sha = digest.hexdigest()
    if worker.db.execute("SELECT 1 FROM installed WHERE sha256=?", (sha,)).fetchone():
        worker.update_job(job_id, phase="", error="Already installed, so nothing was copied")
        return
    is_zim = source.suffix.lower() == ".zim"
    final = (paths.zim if is_zim else paths.library / category) / source.name
    if final.exists():
        raise Refused(f"A different file named {source.name} is already installed")
    content.check(paths, category, size, size)
    worker.update_job(job_id, phase="copying")
    partial = paths.partial / f"{source.name}.import.part"
    partial.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, partial)
    worker.update_job(job_id, phase="verifying")
    from .acquire import sha256_file
    if sha256_file(partial) != sha:
        partial.unlink()
        raise Refused("The copy did not match the drive, so it was discarded")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial, final)
    worker.record(f"import-{sha[:16]}", source.stem, "zim" if is_zim else source.suffix[1:].lower(),
                  category, final, sha, "imported", "removable media", "computed on import")
    worker.refresh_kiwix()
