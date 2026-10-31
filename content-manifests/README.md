# Content manifests

`budgets.json` holds the 13 storage categories. `schema/manifest.schema.json` defines a catalog
entry, and each file in `catalog/` is one entry. Run `make validate` to check them.

`catalog/` is empty on purpose. Entries arrive in Phase 5, because URLs, licenses, sizes and
checksums must be checked live at the source, never written from memory.

Each of `source_url`, `license`, `publication_date`, `size_bytes` and `sha256` is recorded as:

```json
{"value": null, "status": "unverified"}
```

or, once checked:

```json
{"value": "CC-BY-SA-4.0", "status": "verified", "verified_at": "2026-11-01"}
```

Assignment rules: each entry has exactly one `budget_category`. All video goes to
`video`, all map data to `maps`, and Wikimedia ZIMs to `wikimedia_zim`. Other ZIMs
go by subject. If an entry still fits two categories, list the other in `also_fits` and give a
one-line `category_reason`.
