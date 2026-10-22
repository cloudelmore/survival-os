# SURVIVAL OS status

Read this first at the start of every session. One phase per session; stop
for review at the end of each.

**Current phase: 1 (Environment), IN PROGRESS: tooling delivered and updated for the confirmed hardware; hardware steps waiting on the user.**
**Next phase after review: 1 (finish), then 2 (Foundation).**

Hardware baseline: [HARDWARE.md](HARDWARE.md). The USB-attached 990 Pro,
wall power, and no touch requirement override the Rev. 2 prompt.

---

## Session 1 (2026-10-22)

### Context
Both sessions ran in a **cloud container**, not on the Windows dev PC, with no
network path to the Pi. Every step that touches the PC or the Pi has to be run
by the user. Nothing hardware-related is verified.

### Completed work
- First-session planning: [ARCHITECTURE.md](ARCHITECTURE.md) (with the target
  repository tree), [STORAGE_PLAN.md](STORAGE_PLAN.md), [RISKS.md](RISKS.md),
  [MILESTONES.md](MILESTONES.md).
- Phase 1 tooling: `scripts/dev/wsl2-bootstrap.sh` (`--dry-run`/`--check`),
  `scripts/pi/inspect_hardware.py` (read-only), `scripts/dev/pi-remote-inspect.sh`,
  `scripts/pi/kiosk-trial.sh` with its test page, the
  [WSL2 setup guide](dev/windows-wsl2-setup.md), and the
  [Phase 1 guide](phase1/hardware-and-boot.md).

## Session 1, follow-up (2026-10-22): owner answers applied

### Decisions recorded
| Question | Answer | Where applied |
|---|---|---|
| Touch input | Not required | HARDWARE.md, inspector (no touch warning; warns on missing keyboard or trackpad), kiosk trial, milestones |
| NVMe | Samsung 990 Pro in an **external USB enclosure** | Inspector detects USB disks (link speed, UAS, SMART via `smartctl`). Boot via USB mass storage. Flash from the Windows PC with Imager. |
| Power | Wall power over USB-C | Solar assumptions removed. Inspector reports the negotiated supply current and warns below 5 A (USB 600 mA limit). |
| ext4 reserved blocks | 1% | STORAGE_PLAN.md (about 972 GB usable estimated), Phase 1 Step 5 `tune2fs -m 1` |
| License | Apache-2.0 | `LICENSE` (official text from apache.org), `NOTICE`, README |
| GitHub | `cloudelmore/survival-os`, push approved | **Blocked:** the repository does not exist yet, and this session cannot create repositories (see below) |

### Test results (cloud container, x86_64)
- `python3 -m pytest`: **13 passed.** New coverage: USB-attached 990 Pro
  (sysfs link walk, UAS driver, 5000 Mb/s), SMART summary through the bridge
  (non-zero smartctl exit status handled), PSU current from the device tree,
  a USB 2 link warning, a weak-supply warning, the default `0xf41` boot order
  accepted for USB boot, a boot order without USB flagged, and no warnings
  when touch is absent.
- `shellcheck`: clean.

### Unverified (needs real hardware or the dev PC)
- Everything in the Phase 1 guide: WSL2 bootstrap, remote inspection, kiosk
  trial, Imager flash to the 990 Pro, and first USB boot.
- Whether the USB enclosure's bridge passes NVMe SMART through to `smartctl`,
  and whether it uses UAS.
- That the Pi 5 firmware populates `/proc/device-tree/chosen/power/max_current`
  with the negotiated PD current on this OS version.
- Capacity figures in STORAGE_PLAN.md are estimates until inspection runs on
  the drive.

### Open questions
1. USB enclosure make and model (bridge chip), recorded during Phase 1 Step 2.
2. Locale, keyboard layout, and timezone (assumed `en_US.UTF-8`, US,
   `America/New_York`).

### Exact next steps
1. **User:** create an empty repository `cloudelmore/survival-os` on GitHub
   (public, per the spec; no README or license, so the first push is clean).
   Make sure the Claude GitHub App has access to it at
   https://claude.ai/connect-github. Then ask Claude to push. The local
   commits are pushed as-is.
2. **User:** run Phase 1 Steps 1–3 from [phase1/hardware-and-boot.md](phase1/hardware-and-boot.md).
3. **User, with explicit approval:** Steps 4–5 (Imager flash to the 990 Pro,
   first USB boot, `tune2fs -m 1`, re-inspection).
4. Bring the inspection summary and kiosk-trial results to the next session to
   close Phase 1. Then: **Phase 2: Foundation.**
