# SURVIVAL OS status

Read this first at the start of every session. One phase per session; stop
for review at the end of each.

**Current phase: 1 (Environment), IN PROGRESS: tooling delivered, hardware steps waiting on the user.**
**Next phase after review: 1 (finish), then 2 (Foundation).**

---

## Session 1 (2026-10-22)

### Context
This session ran in a **cloud container**, not on the Windows dev PC, and had
no network path to the Pi. Every step that touches the PC or the Pi has to be
run by the user with the scripts below. Nothing hardware-related is verified.

### Completed work
- First-session planning:
  [ARCHITECTURE.md](ARCHITECTURE.md) (with the target repository tree),
  [STORAGE_PLAN.md](STORAGE_PLAN.md), [RISKS.md](RISKS.md),
  [MILESTONES.md](MILESTONES.md).
- Phase 1 tooling:
  - `scripts/dev/wsl2-bootstrap.sh`: WSL2 tooling install with `--dry-run` and
    `--check` (Python ≥ 3.11 with FTS5, Node ≥ 20, git, ssh, rsync, shellcheck,
    jq, xz, qemu binfmt). Creates an ed25519 key if missing.
  - `scripts/pi/inspect_hardware.py`: read-only inspection covering model, RAM,
    OS, display connectors/modes, touchscreen, keyboard, and touchpad
    classification, NVMe and PCIe link, SMART (with sudo), ext4 superblock,
    usable capacity and 15% floor, bootloader version, decoded `BOOT_ORDER`,
    throttling and under-voltage, EXT5V, battery telemetry presence, network
    interfaces, and SSH state. JSON plus a summary with warnings.
  - `scripts/dev/pi-remote-inspect.sh`: runs the inspection over SSH and saves
    the report to `reports/` (git-ignored).
  - `scripts/pi/kiosk-trial.sh` + `kiosk-trial/testpage.html`: non-persistent
    cage or labwc + Chromium kiosk trial. Checks touch corners and keyboard,
    tests the VT/Ctrl+W exits, and samples memory (PSS) for the Phase 2
    decision.
  - Guides: [dev/windows-wsl2-setup.md](dev/windows-wsl2-setup.md) and
    [phase1/hardware-and-boot.md](phase1/hardware-and-boot.md). The NVMe flash
    and boot-order steps are written as procedures behind approval gates and
    are not scripted.

### Test results (in the cloud container, x86_64 Ubuntu 24.04)
- `python3 -m pytest`: **11 passed.** Coverage: fake Pi 5 sysfs/proc tree,
  input-device classification, BOOT_ORDER and throttle decoding, capacity math,
  dumpe2fs parsing, graceful degradation with nothing present, a real-host
  run, and a read-only guard.
- `shellcheck` on all shell scripts: **clean.**
- `wsl2-bootstrap.sh --dry-run`: prints the planned actions. `--check`
  correctly reported `ssh` and `rsync` as missing in the container.
- `inspect_hardware.py` on a non-Pi host: runs, and emits the expected
  "not a Pi 5" warnings.

### Unverified (needs the real hardware or dev PC)
- `wsl2-bootstrap.sh` install on real WSL2 (Debian or Ubuntu).
- `pi-remote-inspect.sh` against the Pi. Whether `inspect_hardware.py` parses
  real Pi 5 `vcgencmd`, `rpi-eeprom-config`, and `nvme` output.
- `kiosk-trial.sh`, never executed: package names on trixie (`chromium` vs
  `chromium-browser`), the `labwc -s` startup flag, `wlr-randr` rotation,
  seat access from tty1, and VT switching.
- The storage capacity figures in STORAGE_PLAN.md are estimates.
- Pi OS Lite trixie first-boot customisation mechanism when the image is
  written with `dd` (cloud-init vs firstrun).

### Open questions for the user
1. **Display:** exact 7-inch panel model and connection (DSI, or HDMI + USB
   touch)? The official Touch Display 2 is natively 720x1280 portrait.
2. **NVMe:** drive model and adapter/HAT. Can it be removed for flashing
   (Option A) or must it stay in the deck (Option B)?
3. **Power:** solar charge controller and battery model. Does it have any data
   interface?
4. **Reserved blocks:** keep ext4's 5% reserve (about 932 GB usable) or lower
   it to 1% (about 972 GB usable)? Recommendation: 1%.
5. **License:** MIT, Apache-2.0, or GPL-3.0-or-later? Recommendation:
   Apache-2.0 (permissive, with an explicit patent grant).
6. **GitHub:** which account or org should host `survival-os`, and may I
   push this work there? Until it is pushed, it exists only in this
   ephemeral session.
7. Locale, keyboard layout, and timezone (assumed `en_US.UTF-8`, US,
   `America/New_York`).

### Exact next steps (user, then Phase 1 completion session)
1. On the Windows PC: follow `docs/dev/windows-wsl2-setup.md` and run
   `scripts/dev/wsl2-bootstrap.sh --check` until it passes.
2. Write the Pi OS Lite test SD card, then run
   `scripts/dev/pi-remote-inspect.sh --sudo <user>@<pi-host>`.
3. Run the kiosk trial for cage and labwc and fill in the checklist in
   `docs/phase1/hardware-and-boot.md`, Step 3.
4. Bring the inspection summary, the trial results, and answers to the open
   questions to the next session.
5. After review and **explicit approval**, flash Pi OS Lite to the NVMe and set
   BOOT_ORDER if needed (Steps 4–5). Phase 1 is complete when the Pi boots Pi
   OS Lite from NVMe and re-inspection confirms it.
6. Then: **Phase 2: Foundation.**
