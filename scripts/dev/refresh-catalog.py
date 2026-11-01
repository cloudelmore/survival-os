#!/usr/bin/env python3
"""Regenerate catalog entries from the live Kiwix catalog. Run on the dev machine, never on the Pi.

Sizes, dates and checksums are read from the publisher. Nothing is written from memory, and a field
that cannot be confirmed is marked unverified.
"""

import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "content-manifests"
CATALOG_URL = "https://opds.library.kiwix.org/catalog/v2/entries"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
METALINK = {"m": "urn:ietf:params:xml:ns:metalink"}
AGENT = {"User-Agent": "SURVIVAL-OS-catalog-refresh"}
TODAY = date.today().isoformat()


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def verified(value) -> dict:
    return {"value": value, "status": "verified", "verified_at": TODAY}


def build(source: dict) -> dict:
    query = urllib.parse.urlencode({"name": source["name"], "count": 20})
    root = ET.fromstring(get(f"{CATALOG_URL}?{query}"))
    flavour = source.get("flavour", "")
    for item in root.findall("a:entry", ATOM):
        if (item.findtext("a:flavour", "", ATOM) or "") == flavour:
            break
    else:
        raise SystemExit(f"Not in the live catalog: {source['name']} {flavour}")
    link = next(entry for entry in item.findall("a:link", ATOM) if entry.get("length"))
    meta = ET.fromstring(get(link.get("href")))
    size = int(meta.findtext(".//m:file/m:size", namespaces=METALINK))
    sha = meta.find(".//m:file/m:hash[@type='sha-256']", METALINK).text.strip()
    name = meta.find(".//m:file", METALINK).get("name")
    author = item.find("a:author/a:name", ATOM)
    wikimedia = source["category"] == "wikimedia_zim"
    entry = {
        "id": source["id"],
        "title": source.get("title") or item.findtext("a:title", "", ATOM),
        "summary": " ".join(filter(None, [item.findtext("a:summary", "", ATOM), source.get("note")])),
        "publisher": author.text if author is not None else "Kiwix",
        "format": "zim",
        "wikimedia_project": wikimedia,
        "budget_category": source["category"],
        "kiwix": {"name": source["name"], "flavour": flavour},
        "destination": f"zim/{name}",
        "source_url": verified(link.get("href")),
        "license": {"value": source.get("license"), "status": "unverified"},
        "publication_date": verified(item.findtext("a:updated", "", ATOM)[:10]),
        "size_bytes": verified(size),
        "sha256": verified(sha),
        "redistribution": {"base_image_allowed": False,
                           "notes": "Large dataset. Downloaded separately, never in the base image."},
    }
    if source.get("reason"):
        entry["category_reason"] = source["reason"]
    return entry


def main() -> None:
    sources = json.loads((ROOT / "sources.json").read_text())
    target = ROOT / "catalog"
    only = set(sys.argv[1:])
    for source in sources:
        if only and source["id"] not in only:
            continue
        entry = build(source)
        (target / f"{entry['id']}.json").write_text(json.dumps(entry, indent=2) + "\n")
        print(f"{entry['size_bytes']['value'] / 1e9:8.2f} GB  {entry['id']}", file=sys.stderr)


if __name__ == "__main__":
    main()
