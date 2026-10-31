# Risks

Updates from real hardware, 2026-10-30:

- R1 closed: the panel is landscape 1024x600.
- R2 occurred: the link is USB 2 at about 35 MB/s, accepted by the owner for now.
- R3 supply limit ruled out: the Pi reports a 5 A supply. Abrupt power loss remains a risk.
- R4 measured: see the decision in ARCHITECTURE.md.
- R13 closed: sessions now run on the dev PC with SSH to the Pi.
- New: one unexplained reboot occurred on the old USB stick system. Its cause is unknown, stick
  I/O stalls are the leading suspect, and journald is now persistent. See STATUS.md.
- New: journald is volatile in the stock image, so crash evidence is lost. Phase 8 must set a
  bounded persistent journal.

| # | Risk | Impact | Mitigation / how we find out |
|---|---|---|---|
| R1 | The 7-inch panel may report a portrait-native mode. (Touch has been dropped from the requirements.) | Wrong rotation | Phase 1 inspection reports DRM modes. Rotation goes in compositor config (`--rotate` in the trial). |
| R2 | USB enclosure problems: a bridge chip without UAS, a USB 2 link, UAS quirks, or SMART not passed through. | Slow I/O, disconnects, no health data | Inspection reports link speed, driver, and SMART. Use a blue USB 3 port. Kernel `usb-storage.quirks` as a documented fallback. Keep an SD recovery card. |
| R3 | A supply under 5 A limits USB to 600 mA combined, and the 990 Pro can brown out. A bumped USB cable or a wall-power cut is an abrupt power loss. | Disconnects, corruption | Inspection reports the negotiated supply current and throttling. Use a 5 V / 5 A PD supply. WAL SQLite, atomic writes, journaled ext4, power-loss and cable-pull tests in Phase 10. |
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
