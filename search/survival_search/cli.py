"""Command line for the library: import files, ask for a rescan, show progress."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import CATEGORIES, DEFAULT_CATEGORY, FORMATS, query
from .indexer import Paths, bytes_above_floor


def plan_import(source: Path) -> list[tuple[Path, Path]]:
    """Pair each supported file with its path relative to the import."""
    if source.is_file():
        return [(source, Path(source.name))]
    return [(path, path.relative_to(source)) for path in sorted(source.rglob("*"))
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in FORMATS]


def import_files(paths: Paths, source: Path, category: str) -> int:
    """Copy files in, refusing the whole import if it would cross the 15% free floor."""
    files = plan_import(source)
    target = paths.library / category
    target.mkdir(parents=True, exist_ok=True)
    needed = sum(path.stat().st_size for path, _ in files)
    if needed > bytes_above_floor(target):
        raise SystemExit("Refused: this import would cross the 15% free storage floor")
    for path, relative in files:
        destination = target / relative
        if destination.exists():
            print(f"Skipped, already present: {relative}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Copied under a name the indexer ignores, so it never reads a partial file.
        partial = destination.with_name(f".{destination.name}.part")
        shutil.copyfile(path, partial)
        partial.replace(destination)
    paths.rescan_flag.parent.mkdir(parents=True, exist_ok=True)
    paths.rescan_flag.touch()
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(prog="survival-library")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("import", help="copy files or a folder into the library")
    add.add_argument("source", type=Path)
    add.add_argument("--category", choices=CATEGORIES, default=DEFAULT_CATEGORY)
    commands.add_parser("status", help="show indexing progress")
    commands.add_parser("rescan", help="ask the indexer to look for changes")
    args = parser.parse_args()
    paths = Paths.from_env()
    if args.command == "import":
        if not args.source.exists():
            sys.exit(f"Not found: {args.source}")
        print(f"{import_files(paths, args.source, args.category)} files in the import")
    elif args.command == "rescan":
        paths.rescan_flag.parent.mkdir(parents=True, exist_ok=True)
        paths.rescan_flag.touch()
    else:
        print(json.dumps(query.status(paths), indent=2))
