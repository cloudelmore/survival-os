# Milestones

One phase per session. Each phase ends with a STATUS.md update and a stop for
user review. "Exit criteria" must be demonstrated, not just written.

| Phase | Scope | Exit criteria |
|---|---|---|
| 1. Environment | WSL2 tooling, SSH to Pi, hardware inspection, Pi OS Lite + kiosk trial from SD, then (with approval) flash Pi OS Lite to the USB NVMe | `wsl2-bootstrap.sh --check` passes on the dev PC. Inspection report collected. Kiosk trial run with keyboard and trackpad verified, memory logged for cage and labwc. Pi boots Pi OS Lite from the USB NVMe at 5 Gb/s UAS with 1% reserved blocks. |
| 2. Foundation | Repo scaffold (LICENSE, CONTRIBUTING, SECURITY, CHANGELOG, CI skeleton), manifest JSON Schema plus validator, kiosk compositor/browser decision from Phase 1 data, `make deploy` dev loop over SSH/rsync | Schema validates sample manifests in tests. One-command deploy of a hello-world API and page to the Pi. Kiosk decision documented with numbers. |
| 3. Dashboard | Homepage with 10 sections, kiosk auto-launch and auto-restart, system status (real telemetry only), power controls, maintenance mode, keyboard navigation | Boots to the dashboard. Kill the browser and it restarts. Maintenance exit works on the device. Usable at 1280x800 with the keyboard alone, and with the trackpad. |
| 4. Search | Importers (PDF/EPUB/TXT/MD/HTML), FTS5 indexing (incremental, resumable, throttled), snippets, filters, bundled viewers, open-at-page, optional OCR | Test corpus search returns correct snippets and page links that open in the built-in viewer. Indexing survives a forced kill. |
| 5. Content | Kiwix integration, content manager: install, validate, update, remove, import from USB, category accounting, 15% floor enforcement | ZIM browsable offline. An operation that would cross the floor is blocked in tests. Usage by category shown. Resumed download verifies its checksum. |
| 6. Maps | PMTiles serving with range requests, MapLibre with bundled style, glyphs, and sprites, NC and SE US packages, waypoints, GPX import/export | Map renders with all networking off. GPX round-trips. |
| 7. AI | llama.cpp optional install and removal, retrieval over FTS5 with citations | Answers cite passages that open in viewers. Uninstall leaves no residue. Library unaffected when AI is off. |
| 8. Operations | Pi OS Lite installer (detect, dry run, install, repair, uninstall), backup/export, integrity check, restore docs | Dry run lists every change. Install, repair, and uninstall cycle tested on a fresh SD install. |
| 9. Release pipeline | Image builder (confirm current official tool), `.img.xz` plus SHA-256, first boot, CI | Image builds reproducibly from WSL2/Docker. |
| 10. Verification | Offline acceptance test, performance, power-loss and reboot tests, real Pi 5 boot of the built image from the USB NVMe | Every acceptance item in spec §10 passes or is listed as unverified. Tag `v0.1.0-alpha` (with approval). |
