# SURVIVAL OS: Status

Read this first at the start of every session.

**Current phase:** 3 (Dashboard) complete. Phase 4 (Search) has not started.
**Last updated:** 2026-10-31 (Phase 3 session)

## Completed work

### Phase 3 (Dashboard)

- Original retro dashboard with ten sections, bundled OFL fonts and hand-made pixel icons.
- Keyboard: number keys, arrows, Enter, Esc, P for power. Touch and pointer work throughout.
- System status from real telemetry. No battery figure exists anywhere.
- Admin PIN, chosen at first use, for shutdown, reboot and maintenance. Five failures lock it for
  60 s. Cross-site requests are refused. The on-screen keypad works without a keyboard.
- Production services: `survival-api`, `survival-web` (nginx-light), `survival-kiosk`, and
  `survival-maintenance.target`. The browser profile is in RAM.
- Installer with `--dry-run`, `--apply`, `--enable`, `--disable`, `--uninstall`.
- CI-ready offline build check. `make deploy` now uses the installer.
- Docs: MAINTENANCE.md. Font licenses in docs/licenses.

Pi changes, approved by the user: nginx-light installed with `nginx.service` masked, users
`survival` and `kiosk`, `/opt/survival-os`, `/etc/sudoers.d/survival-os`, services enabled at boot,
`getty@tty1` disabled. `labwc`, `firefox` and `bc` from Phase 2 remain and can be removed.

### Phase 3 test results

| Check | Result |
|---|---|
| Python tests | 68 passed |
| Frontend tests and type check | 12 passed, clean |
| Offline build check | Pass |
| Dry run on the Pi changes nothing | Pass |
| Ports after reboot | Only 22 outward; 8080 and 8081 on loopback; no port 80 |
| Boots to the dashboard | Pass, one reboot through the API, unattended |
| Linux startup | 30.3 s, kiosk started 23 s after the kernel |
| Firmware | Started the OS at 19.2 s, of which 12.2 s came before its log begins |
| Reboot gap | 87 s from the last journal line to kernel start, so about 68 s is not firmware. Cause unknown; likely the late shutdown stage, which logs nothing |
| Browser killed twice | Pass, back in 3 s each time |
| Wrong PIN refused, right PIN accepted | Pass |
| Maintenance mode through the API | Pass: kiosk stops, getty starts on tty1, and it returns |
| Service account sudo | Pass: only the three listed commands |
| Strict content policy in Chromium | Pass, page and fonts render identically |
| Render at 1280x800 | Pass, headless on the Pi |

User report, 2026-10-31: "all good", with no itemised results. The Pi's logs show that no PIN was
set, maintenance mode was not entered, and no shutdown occurred after the 00:14 reboot, so those
checks were not run. The user then confirmed that keyboard and touch work on the device.

Device checks, 2026-10-31: the PIN was set and maintenance mode was entered from the screen at
09:35:53. The user logged in at tty1 and restarted the kiosk with `sudo systemctl start
survival-kiosk` at 20:01:43, and it came back. The user reported about two seconds for that return.

The user reported steps 1 to 4 complete, but the journal shows no shutdown and no new boot, so the
shutdown step did not run. The user then decided the shutdown timing and EEPROM comparison were not
necessary.

The user then asked to finish the remaining checks. Results from 2026-10-31, over SSH:

| Check | Result |
|---|---|
| Single browser crash | Pass after fix: restarts, no maintenance trigger, no console on tty1 |
| Repeated crashes | Pass after fix: 10 crashes inside 120 s, one trigger, ends in maintenance |
| Recovery from that | Pass: `reset-failed`, then start |
| `--uninstall` | Pass after fix: exit 0, all units, users and files gone, only SSH listening |
| Saved PIN across reinstall | Pass: file kept, API reports `pin_set` |
| Reinstall and `--enable` | Pass, kiosk started by hand; not yet proven by a boot |

Two bugs were found and fixed. `OnFailure` fired on every crash, showing a console on tty1 for about
2 s each time, so the earlier "back in 3 s" hid that; `RestartMode=direct` fixes it. `--uninstall`
stopped at `userdel kiosk` because the session manager was still running, leaving `nginx` masked.

Device results, 2026-10-31, evening. The user reported steps 1 to 5 good and a 1 min 10 s cold boot:

- Shutdown from the dialog: pass. Logged 20:13:51, clean journal stop at 20:13:53.
- Cold boot on the current install: pass, unattended to the dashboard, `throttled=0x0`, no failed
  units. User's stopwatch 1 min 10 s; kernel start 20:15:00. Linux 32.1 s, kiosk 24.7 s after kernel.
- Ctrl+Alt+F2 and F1, power dialog fit: pass, by user report. The logs cannot show these.

- Power loss: pass. After the cold boot, a boot ended with no clean shutdown. The next boot found
  the FAT dirty bit set on `/dev/sda1` and cleared it, ext4 was clean, and the kiosk started unattended.
- `survival.maintenance=1`: pass. With the flag added temporarily, the Pi booted to the maintenance
  target with getty on tty1 and no kiosk. `cmdline.txt` was restored (checksum matched), the backup
  removed, and a further boot reached the kiosk normally.
- Trackpad: pass. Detected as USB `1915:1025` with keyboard and mouse inputs; the user confirmed
  that it works.

### Phase 2 (Foundation)

- Repository reconciled onto the existing `cloudelmore/survival-os` history and pushed to `main`.
- Backend: FastAPI health endpoint and static dashboard serving, on loopback.
- Manifests: JSON Schema, 13 storage budgets, validator for the rules a schema cannot express. The
  catalog is empty until Phase 5, so no field is written from memory.
- Frontend: Vite, React and TypeScript placeholder page. The dashboard is Phase 3.
- Dev loop: `make test`, `deploy`, `check`, `kiosk`, `kiosk-stop`. Documented in docs/dev/windows-wsl2-setup.md.
- Compositor and browser decided: `cage -s` with Chromium. See ARCHITECTURE.md. Front web server is nginx-light, not yet measured.
- Node 24.22.2 LTS installed under `~/.local`, checksum verified.
- Pi: ext4 reserved blocks set to 1%. Added `labwc`, `firefox` and `bc` for the comparison, and
  `~/survival-os-dev` for the dev loop. The first three can be removed; nothing depends on them.

### Phase 2 test results

| Check | Result |
|---|---|
| Python tests | 41 passed (27 new, 14 from the earlier inspector suite) |
| Frontend tests and type check | 2 passed, clean |
| Manifest validation | Pass, 0 entries, 0 errors |
| Deploy to Pi, health and page check | Pass |
| Backend bind address | `127.0.0.1:8080` only |
| Source edit reaches the Pi through `make deploy` | Pass, about 8 s |
| Deployed page in kiosk on the real screen | Pass, screenshot shows backend ok |
| Remote assets in frontend build | None. URLs present are React error links and XML namespaces |
| Nothing autostarts | Pass, 0 survival units enabled |
| Crash recovery, two browser kills | Pass, 3.5 s and 3.0 s |
| CI workflow | Pass, first run on `e694b4f` |

Not tested: touch, keyboard and VT switching on the NVMe system, long-duration kiosk stability,
power-loss recovery, operation with all network interfaces disabled.

### Phase 1 (Environment)

- Wrote the first-session plan, since merged into ARCHITECTURE, STORAGE_PLAN, RISKS and MILESTONES.
- Current NVMe system, all development scaffolding: `cage chromium grim` installed,
  `/etc/sudoers.d/090-dev` passwordless sudo, and `zz-survival-dev.conf` persistent journal
  capped at 200 MB. None may reach a release image. Nothing autostarts. EEPROM and boot order
  are unchanged.
- Inspected Pi hardware and dev environment (below).
- Pi changes on the old USB stick, now retired:
  - `apt-get update`, then installed `cage chromium grim` plus dependencies.
  - `/etc/sudoers.d/090-dev` passwordless sudo, added by the user. Must not reach release images.
  - `/etc/systemd/journald.conf.d/zz-survival-dev.conf` persistent journal, 200 MB cap.
  - `/usr/local/sbin/dev-vitals` and `/var/log/dev-vitals.log` remain, not running.
  - Nothing autostarts. No boot, EEPROM or disk changes.

## Test results

### Dev environment (WSL2, Debian 13)

| Check | Result |
|---|---|
| Python 3.13.5, venv, pip install of FastAPI | Pass |
| SQLite 3.46.1 with FTS5 | Pass |
| Node 20.19.2, npm 9.2.0, npm registry reachable | Pass. Upgrade Node in Phase 2, version 20 is past end of life |
| rsync, make, gcc, xz, qemu-aarch64-static, jq, curl | Present |
| SSH to Pi by key | Pass, about 0.4 s to connect |
| Docker | Missing. Not needed until Phase 9 |
| gh | Missing. Needed before publishing |
| WSL sudo | Needs a password, so system packages here need the user |

### Pi hardware (`ssh survival`, on wlan0)

| Item | Finding |
|---|---|
| Board | Pi 5 Model B Rev 1.0, 8 GB |
| OS | Pi OS Lite, Debian 13, image 2026-10-06, kernel 6.18.50, arm64 |
| Boot device | 1 TB NVMe in a USB enclosure, see Storage connection decision |
| Display | 7-inch, **1024x600**, HDMI-A-2. Differs from the brief. See deviations |
| Touch | USB "QDtech MPI5001", direct-touch input device. Works |
| Keyboard | Logitech K270 on a Unifying receiver |
| Pointer | Trackpad exists but is swapped out (user). USB device 1915:1025 was likely it, unconfirmed. Support both |
| EEPROM | 2025-05-08. Update available (2026-09-25). Not applied, approval gate |
| EEPROM config | `BOOT_ORDER=0xf461` (SD, NVMe, USB, repeat), `PCIE_PROBE=1` |
| Power | `get_throttled=0x0`, EXT5V about 5.13 V, about 48 C at idle |
| Power source | Wall power, confirmed by the user. No system battery |

Telemetry rules for Phase 3:
- `hidpp_battery_0` is the keyboard battery (`scope=Device`). Never show it as system power.
- `BATT_V` from `pmic_read_adc` reads 0 V. It is the RTC battery rail, not a main battery.

### Kiosk trial on the NVMe system (2026-10-30)

`cage -s` with Chromium 156, transient unit. Package install took about 6 minutes, against about
25 on the stick. Reached 1024x600 about 4 s after launch, full-screen in the screenshot, WebGL 2
on V3D, about 622 MB RAM in use, 51 C, `throttled=0x0`, 5.13 V. Stopped cleanly and returned to
tty1. Touch, keyboard and VT switching were tested on the stick system only, with the same
hardware and software versions. Power-loss recovery is untested.

### Kiosk trial (USB stick system, transient unit, 2026-10-30)

`cage` 0.3.1 with Chromium 156 on tty7, loading a local test page.

| Check | Result |
|---|---|
| Launch to first page | Pass, about 12 s, from slow USB |
| Rendering | Pass, screenshot is full-screen 1024x600 |
| WebGL | Pass, WebGL 2 on the V3D 7.1 GPU through ANGLE, relevant to MapLibre |
| Reported touch points | 10 |
| System memory in use with kiosk running | About 595 MB of 8 GB |
| Thermal and power during trial | 54 C, `throttled=0x0` |
| Services added by packages | None at system level; only dconf's on-demand user service |

Window size is 972x451 at first load, then 1024x600 after a resize event within 5 s. Frontend
code must handle that resize rather than trust the size at load.

Input test: touch passes. Taps at all four corners and the centre arrived as `pointerType=touch`
at matching coordinates, with no calibration needed. Keyboard passes: letters and modifiers
arrive correctly.

VT switching passes with `cage -s`: Ctrl+Alt+F2 reaches a text login and Ctrl+Alt+F7 returns
(user tested at the device). Without `-s`, cage blocks it and Chromium receives
`key=Unidentified`. Any cage kiosk unit must pass `-s`. Cage is the trial candidate only; the
compositor choice stays in Phase 2.

## Open risks

### 1. Unexplained reboot on the USB stick system, about 22:07 on 2026-10-30

Sequence: the first command of the install step, `systemctl list-unit-files`, failed with
`Connection timed out`, then SSH was reset. The Pi came back with a new boot at 22:07.
Nothing from that step survived, as `/tmp` was cleared and apt history is empty.

- Evidence the shutdown was not clean: ext4 orphan cleanup on mount, FAT dirty bit on the
  boot partition (the FAT bit could be older).
- A hung PID 1 fits the D-Bus timeout, and the hardware watchdog is 1 minute. That is a
  hypothesis, not a finding.
- The user confirmed they did not reboot or power-cycle it.
- Remaining possibilities: power interruption, USB stick stall, system hang.
- The same `systemctl` timeout recurred during the next install with no reboot, so that error
  alone is not a crash sign. The stick writes only about 2 to 5 MB/s and `systemctl` calls took
  5 s or more under load, so I/O stalls are the leading suspect, unproven.
- A full 107-package install then completed in about 25 minutes with no reboot, 0x0 throttling
  and steady 5.13 V, which argues against a simple load-related power fault.
- Logs from the failed boot are gone because journald is `Storage=volatile`.
- `get_throttled=0x0` after the reboot is uninformative; that counter resets on boot.

## Earlier cloud sessions (2026-10-22)

The GitHub repository already held four commits of tooling and decisions, found in Phase 2. The
reconciliation kept them: Apache-2.0, `scripts/dev` and `scripts/pi`, budget keys, 1% reserve, and
the planning docs. Local MIT and duplicate docs were dropped. HARDWARE.md records where
measurements override that baseline.

The earlier inspector has not been run on this hardware, so its SMART handling stays unverified.

## Deviations from the brief

- **Display.** Brief says 1280x800. Hardware reports one mode, 1024x600, with an EDID size of
  153x86 mm. Decision: design for 1024x600 as the primary target and stay responsive up to
  1280x800, so the stated requirement still holds.
- **Boot media.** The NVMe is USB-attached, not on PCIe. See Storage connection decision.
- **Storage.** ext4 reserved blocks are 1%, applied to the single root filesystem.
- **Node.** Node 24 LTS. Node 20 is past end of life.

## Unverified

- Cause of the reboot.

## Open questions for the user

None open.

Answered: power is wall power over USB-C with no solar, so show input voltage, supply current and
throttling only. The Pi should boot from the NVMe eventually; USB is only a temporary system for
testing and flashing, and the existing boot order already favours NVMe. Passwordless sudo is
acceptable during development. A trackpad exists; the user
swapped it for the keyboard, so it may return and both inputs stay supported.

## Storage connection decision

Permanent setup: 1 TB Samsung 970 EVO Plus in a UGREEN CM578 USB enclosure (RTL9210 bridge) on a
USB 3 port, old stick removed. The user has no plans for a PCIe HAT. All "NVMe boot" work means
USB-attached NVMe, and PCIe `link down` is expected.

NVMe flashed by the user with Raspberry Pi Imager and booted 2026-10-30 23:09.

| Check | Result |
|---|---|
| Boots from the NVMe with no stick fitted | Pass. Now `root=PARTUUID=a4a3a4fb-02`; the ID changed once, consistent with first-boot setup |
| Filesystem expanded | Pass, 916.4 GiB (about 984 GB), about 969 GB available at 1% reserved |
| New host key | Matches the fingerprint seen before trust |
| USB power | `max_current` 5000 mA, `usb_max_current_enable=1`, so not current-limited |
| Link speed | Accepted limit: 480 Mbps (USB 2), `usb-storage` driver, not UAS |
| Direct 2 GB write / read | 33.4 / 37.2 MB/s at USB 2 |
| Power under that test | `throttled=0x0`, 5.13 V |

The earlier capacity estimate of about 983 GB holds. The USB power limit is ruled out as a
reboot risk at this supply.

The user accepted USB 2 speed for now (2026-10-30). The fault is not diagnosed: both SuperSpeed
ports report `not attached` with no over-current, so the USB 3 lines are not connecting. That
points to the cable or plug. Design indexing and acquisition for about 35 MB/s: budget long
imports, and keep throttling so search and Kiwix stay responsive.

## Phase 3 visual direction

The user wants a retro theme in the style of the original "Oregon Trail". Nothing visual is
built yet. This refines the brief's dark field-computer look:

- Apply it to the dashboard, menus and headings: Apple II-like palette, blocky type, simple pixel
  art, menu-driven screens.
- Long manuals and medical references stay in a clean, readable font.
- 1024x600 layout, large touch targets and full keyboard navigation still apply.
- All assets are original. Use no Oregon Trail name, artwork or game graphics in this public repo.
- Any pixel font must have a license that allows bundling, and ships locally.

## Next steps

1. Phase 4 (Search) starts when the user says so.

Dropped by the user, 2026-10-31: the cold boot baseline and the EEPROM change (`BOOT_ORDER=0xf14`,
removing `PCIE_PROBE=1`). The expected gain was seconds at most. The EEPROM is unchanged. Any future
EEPROM change needs fresh approval.
