# Risks

| # | Risk | Impact | Mitigation / how we find out |
|---|---|---|---|
| R1 | The "7-inch 1280x800" panel may be a portrait-native panel (the official Touch Display 2 is 720x1280) or an HDMI panel with separate USB touch. | Wrong rotation, touch offset from the image | Phase 1 inspection reports DRM modes and input devices. The kiosk trial test page checks corner taps. Rotation goes in compositor config. |
| R2 | The NVMe or its adapter may not boot reliably (PCIe gen, power, firmware). | Cannot meet "boots from NVMe" | Inspection reports the PCIe link and BOOT_ORDER. Test SD boot first, then NVMe. Keep an SD recovery card. EEPROM or boot-order changes only with approval. |
| R3 | Solar input can sag, causing under-voltage, throttling, or abrupt power loss. | Corruption, crashes | Read `get_throttled` and EXT5V. WAL SQLite, atomic writes, journaled ext4, power-loss tests in Phase 10. Battery % is shown only if Linux exposes it (it currently does not by default). |
| R4 | Kiosk browser RAM and stability on Pi OS Lite. | Crashes, swap on 8 GB alongside indexing and AI | Measure cage vs labwc with Chromium (`kiosk-trial.sh`). systemd auto-restart. Memory limits on indexer and LLM units. |
| R5 | Running indexing, Kiwix, and AI at the same time starves the UI. | Sluggish dashboard | Indexer at nice 19 with idle I/O and CPUQuota. LLM off by default with a memory cap. Load tests in Phase 10. |
| R6 | Content licensing: redistribution limits (some manuals, Stack Exchange CC BY-SA attribution, OSM ODbL). | Legal or publishing problems | Manifest records the license per entry. Large or restricted content is never in the image. Attribution page in the UI. Fields that cannot be verified live are marked `unverified`. |
| R7 | Content sources move or change size (Kiwix mirrors, map extracts). | Broken acquisition | Verify URL, size, and checksum live at acquisition time. Resumable downloads. No values taken from model memory. |
| R8 | The official image tooling has changed (`rpi-image-gen` vs `pi-gen`). | Rework in Phase 9 | Confirm the current supported tool at the start of Phase 9. Keep build inputs declarative. |
| R9 | WSL2 limits for image builds (loop devices, binfmt, Docker networking). | Reproducible builds on the dev PC may not work | qemu-user-static and binfmt checked by `wsl2-bootstrap.sh --check`. Docker fallback. Validate early in Phase 9. |
| R10 | Offline maps need correctly bundled glyphs and sprites; a single missing asset breaks the map. | Blank labels or map offline | CI check that the built bundle has no external URLs. Phase 10 offline acceptance with all interfaces down. |
| R11 | Unsafe AI output in medical or safety topics. | Harm | AI disabled by default. It must cite sources and show warnings, and it is never the source for medical, edible-plant, or electrical-safety guidance. |
| R12 | Single NVMe is a single point of failure. | Total data loss | Documented external export and backup (USB). Same-disk snapshots are labeled as not protecting against drive failure. |
| R13 | This session ran in a cloud container without access to the Pi or Windows PC. | Phase 1 hardware steps cannot be executed by Claude here | The user runs the provided scripts. Results go into STATUS.md. Nothing is marked verified until the user reports it. |
