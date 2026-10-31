# SURVIVAL OS

A fully offline knowledge appliance for a Raspberry Pi 5 cyberdeck. It runs
Raspberry Pi OS Lite 64-bit (Debian 13 trixie) and boots straight into a
dashboard for keyboard, trackpad and touch, with library search, document viewers, Wikipedia (Kiwix),
offline maps, and optional local AI.

> **Status: Phase 3 (dashboard) in progress. The dashboard boots, but no content is installed yet.**
> See [docs/STATUS.md](docs/STATUS.md) for what works and what is still unverified.

## What exists today

| Path | What it is |
|---|---|
| `scripts/dev/wsl2-bootstrap.sh` | Sets up Linux tooling in WSL2 on the Windows dev PC (`--dry-run`, `--check`) |
| `scripts/dev/pi-remote-inspect.sh` | Runs the hardware inspection on the Pi over SSH and saves the report |
| `scripts/pi/inspect_hardware.py` | Read-only Pi 5 hardware/boot/storage/power inspection, including the USB-attached NVMe (stdlib Python) |
| `scripts/pi/kiosk-trial.sh` | Non-persistent kiosk trial (cage or labwc + Chromium) with memory sampling |
| `backend/`, `frontend/` | Dashboard, system status and PIN-protected power controls |
| `systemd/`, `installers/` | Kiosk and web services, plus an installer with a dry run |
| `content-manifests/` | Catalog schema, the 13 storage budgets, and validation (catalog entries arrive in Phase 5) |
| `Makefile`, `scripts/dev/dev-*.sh` | Test and deploy to the Pi |
| `docs/` | Architecture, storage plan, risks, milestones, setup and Phase 1 guides |

## Quick start (dev PC, WSL2)

```bash
scripts/dev/wsl2-bootstrap.sh --dry-run
scripts/dev/wsl2-bootstrap.sh
make setup
make test
scripts/dev/pi-remote-inspect.sh --sudo <user>@<pi-host>
```

Then follow [docs/phase1/hardware-and-boot.md](docs/phase1/hardware-and-boot.md).

## Documents

- [Hardware baseline](docs/HARDWARE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Storage plan](docs/STORAGE_PLAN.md)
- [Risks](docs/RISKS.md)
- [Milestones](docs/MILESTONES.md)
- [Windows + WSL2 setup](docs/dev/windows-wsl2-setup.md)
- [Maintenance and recovery](docs/MAINTENANCE.md)

## License

SURVIVAL OS source code is licensed under the [Apache License 2.0](LICENSE).
Downloaded content collections keep their own licenses; those are recorded per
entry in the content manifests.
