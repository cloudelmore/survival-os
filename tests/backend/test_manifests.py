import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from survival_os import manifests

ROOT = Path(__file__).resolve().parents[2] / "content-manifests"
SCHEMA = manifests.load_json(ROOT / "schema" / "manifest.schema.json")
BUDGETS = manifests.load_json(ROOT / "budgets.json")


def unverified():
    return {"value": None, "status": "unverified"}


def entry(**overrides):
    base = {
        "id": "test-entry",
        "title": "Test entry",
        "publisher": "Example publisher",
        "format": "pdf",
        "budget_category": "medical_survival",
        "destination": "manuals/test.pdf",
        "source_url": unverified(),
        "license": unverified(),
        "publication_date": unverified(),
        "size_bytes": unverified(),
        "sha256": unverified(),
        "redistribution": {"base_image_allowed": False},
    }
    base.update(overrides)
    return base


def schema_errors(item):
    return list(Draft202012Validator(SCHEMA).iter_errors(item))


def make_root(tmp_path, *entries):
    (tmp_path / "schema").mkdir()
    (tmp_path / "catalog").mkdir()
    (tmp_path / "schema" / "manifest.schema.json").write_text(json.dumps(SCHEMA))
    (tmp_path / "budgets.json").write_text(json.dumps(BUDGETS))
    for i, item in enumerate(entries):
        (tmp_path / "catalog" / f"{i}.json").write_text(json.dumps(item))
    return tmp_path


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_budgets_match_the_brief():
    assert len(BUDGETS["categories"]) == 13
    assert sum(c["cap_gb"] for c in BUDGETS["categories"]) == 800
    assert BUDGETS["free_space_floor_percent"] == 15
    assert manifests.check_budgets(BUDGETS) == []


def test_changed_cap_is_caught():
    budgets = copy.deepcopy(BUDGETS)
    budgets["categories"][0]["cap_gb"] += 1
    assert manifests.check_budgets(budgets)


def test_schema_and_budgets_agree():
    assert manifests.check_schema_sync(SCHEMA, BUDGETS) == []


def test_shipped_catalog_is_valid():
    assert manifests.validate_catalog(ROOT) == []


def test_unverified_entry_is_accepted():
    assert schema_errors(entry()) == []
    assert manifests.check_entry(entry()) == []


@pytest.mark.parametrize("missing", ["publisher", "license", "budget_category", "destination"])
def test_required_fields(missing):
    item = entry()
    del item[missing]
    assert schema_errors(item)


def test_only_one_category_is_possible():
    assert schema_errors(entry(budget_category=["maps", "os_apps"]))
    assert schema_errors(entry(budget_category="not_a_category"))


def test_bad_checksum_is_rejected():
    bad = {"value": "abc", "status": "verified", "verified_at": "2026-10-30"}
    assert schema_errors(entry(sha256=bad))


@pytest.mark.parametrize("name", ["license", "sha256"])
def test_verified_needs_a_value_and_date(name):
    errors = manifests.check_entry(entry(**{name: {"value": None, "status": "verified"}}))
    assert any("no value" in e for e in errors)
    assert any("no verified_at" in e for e in errors)


@pytest.mark.parametrize("fields, required", [
    ({"format": "video"}, "video"),
    ({"format": "kolibri-video"}, "video"),
    ({"format": "pmtiles", "extract": {"bbox": [0, 0, 1, 1], "max_zoom": 8}}, "maps"),
    ({"format": "zim", "wikimedia_project": True}, "wikimedia_zim"),
])
def test_format_overrides(fields, required):
    assert manifests.check_entry(entry(**fields))
    assert manifests.check_entry(entry(budget_category=required, **fields)) == []


def test_map_needs_a_region():
    assert manifests.check_entry(entry(format="pmtiles", budget_category="maps"))


def test_non_wikimedia_zim_goes_by_subject():
    assert manifests.check_entry(entry(format="zim", budget_category="radio")) == []


def test_also_fits_needs_a_reason():
    assert manifests.check_entry(entry(also_fits=["natural_sciences"]))
    fixed = entry(also_fits=["natural_sciences"], category_reason="Mainly first aid.")
    assert manifests.check_entry(fixed) == []


@pytest.mark.parametrize("destination", ["/etc/passwd", "../outside", "a/../../b"])
def test_unsafe_destination_is_rejected(destination):
    assert manifests.check_entry(entry(destination=destination))


def test_duplicates_across_catalog(tmp_path):
    root = make_root(tmp_path, entry(), entry())
    errors = manifests.validate_catalog(root)
    assert any("duplicate id" in e for e in errors)
    assert any("destination shared" in e for e in errors)
