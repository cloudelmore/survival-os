"""Load and validate content manifests and storage budgets.

The JSON Schema covers structure. This module adds the rules a schema cannot express, such as the
Section 5 category assignment overrides and uniqueness across the whole catalog.

Run as: python -m survival_os.manifests content-manifests
"""

import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

EXPECTED_TOTAL_GB = 800
VERIFIABLE_FIELDS = ("source_url", "license", "publication_date", "size_bytes", "sha256")
VIDEO_FORMATS = {"video", "kolibri-video"}
MAP_FORMATS = {"pmtiles", "map-data"}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def check_budgets(budgets: dict[str, Any]) -> list[str]:
    errors = []
    categories = budgets["categories"]
    ids = [c["id"] for c in categories]
    if len(ids) != len(set(ids)):
        errors.append("budgets: duplicate category id")
    total = sum(c["cap_gb"] for c in categories)
    if total != EXPECTED_TOTAL_GB:
        errors.append(f"budgets: caps total {total} GB, expected {EXPECTED_TOTAL_GB}")
    return errors


def check_schema_sync(schema: dict[str, Any], budgets: dict[str, Any]) -> list[str]:
    enum = set(schema["properties"]["budget_category"]["enum"])
    ids = {c["id"] for c in budgets["categories"]}
    if enum != ids:
        return [f"schema and budgets disagree on categories: {sorted(enum ^ ids)}"]
    return []


def expected_category(entry: dict[str, Any]) -> str | None:
    """Return the category forced by a format override, or None if subject decides."""
    if entry["format"] in VIDEO_FORMATS:
        return "video"
    if entry["format"] in MAP_FORMATS:
        return "maps"
    if entry["format"] == "zim" and entry.get("wikimedia_project"):
        return "wikimedia_zim"
    return None


def check_entry(entry: dict[str, Any]) -> list[str]:
    errors = []
    label = entry["id"]

    forced = expected_category(entry)
    if forced and entry["budget_category"] != forced:
        errors.append(f"{label}: format override requires category {forced}")
    if entry.get("also_fits") and not entry.get("category_reason"):
        errors.append(f"{label}: also_fits needs a one-line category_reason")
    if entry["budget_category"] in entry.get("also_fits", []):
        errors.append(f"{label}: also_fits repeats budget_category")

    for name in VERIFIABLE_FIELDS:
        field = entry[name]
        if field["status"] == "verified":
            if field.get("value") is None:
                errors.append(f"{label}: {name} is verified but has no value")
            if not field.get("verified_at"):
                errors.append(f"{label}: {name} is verified but has no verified_at")

    destination = PurePosixPath(entry["destination"])
    if destination.is_absolute() or ".." in destination.parts:
        errors.append(f"{label}: destination must be relative with no '..'")
    return errors


def validate_catalog(root: Path) -> list[str]:
    schema = load_json(root / "schema" / "manifest.schema.json")
    budgets = load_json(root / "budgets.json")
    errors = check_budgets(budgets) + check_schema_sync(schema, budgets)

    validator = Draft202012Validator(schema)
    seen_ids: dict[str, Path] = {}
    seen_destinations: dict[str, str] = {}
    for path in sorted((root / "catalog").glob("*.json")):
        entry = load_json(path)
        structural = list(validator.iter_errors(entry))
        if structural:
            errors += [f"{path.name}: {e.message}" for e in structural]
            continue
        errors += check_entry(entry)
        if entry["id"] in seen_ids:
            errors.append(f"{path.name}: duplicate id {entry['id']}")
        seen_ids[entry["id"]] = path
        if entry["destination"] in seen_destinations:
            errors.append(f"{path.name}: destination shared with "
                          f"{seen_destinations[entry['destination']]}")
        seen_destinations[entry["destination"]] = entry["id"]
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("content-manifests")
    errors = validate_catalog(root)
    for error in errors:
        print(error, file=sys.stderr)
    count = len(list((root / "catalog").glob("*.json")))
    print(f"{count} catalog entries checked, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
