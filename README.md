# SURVIVAL OS

A fully offline knowledge appliance for a Raspberry Pi 5 cyberdeck. It runs
Raspberry Pi OS Lite 64-bit (Debian 13 trixie) and boots straight into a
touchscreen dashboard with library search, document viewers, Wikipedia (Kiwix),
offline maps, and optional local AI.

> **Status: Phase 1 (environment) in progress. Not usable yet.**
> See [docs/STATUS.md](docs/STATUS.md) for what works and what is still unverified.

## What exists today

| Path | What it is |
|---|---|
| `scripts/dev/wsl2-bootstrap.sh` | Sets up Linux tooling in WSL2 on the Windows dev PC (`--dry-run`, `--check`) |
| `scripts/dev/pi-remote-inspect.sh` | Runs the hardware inspection on the Pi over SSH and saves the report |
| `scripts/pi/inspect_hardware.py` | Read-only Pi 5 hardware/boot/storage/power inspection (stdlib Python) |
| `scripts/pi/kiosk-trial.sh` | Non-persistent kiosk trial (cage or labwc + Chromium) with memory sampling |
| `docs/` | Architecture, storage plan, risks, milestones, setup and Phase 1 guides |

## Quick start (dev PC, WSL2)

```bash
scripts/dev/wsl2-bootstrap.sh --dry-run
scripts/dev/wsl2-bootstrap.sh
python3 -m pytest
scripts/dev/pi-remote-inspect.sh <user>@<pi-host>
```

Then follow [docs/phase1/hardware-and-boot.md](docs/phase1/hardware-and-boot.md).

## Documents

- [Architecture](docs/ARCHITECTURE.md)
- [Storage plan](docs/STORAGE_PLAN.md)
- [Risks](docs/RISKS.md)
- [Milestones](docs/MILESTONES.md)
- [Windows + WSL2 setup](docs/dev/windows-wsl2-setup.md)

License: to be chosen (see open questions in STATUS.md).
