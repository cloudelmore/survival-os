# Windows + WSL2 development setup

Target: a Windows 10/11 PC that builds SURVIVAL OS and deploys to the Pi over
SSH. All Linux tooling runs inside WSL2. Containers (Docker) are used only on
the PC, never on the Pi.

## 1. Install WSL2 and a Debian distro

In an **administrator PowerShell**:

```powershell
wsl --install -d Debian
wsl --update
wsl -l -v          # Debian should show VERSION 2
```

Debian matches the Pi's userland most closely. Ubuntu works too, as a dev
host only; Ubuntu is not a supported target. Inside WSL, check the release with
`cat /etc/os-release`. Debian 13 (trixie) is preferred; Debian 12 works for
Phase 1.

### Networking to the Pi

WSL2's default NAT networking often cannot resolve `*.local` (mDNS) names or
reach some LAN devices. If `ssh pi@<name>.local` fails, either use the Pi's IP
address or enable mirrored networking in `%UserProfile%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then run `wsl --shutdown` and reopen the terminal.

## 2. Clone the repository inside the WSL filesystem

Keep the checkout under `~` (for example `~/src/survival-os`), not under
`/mnt/c`. Builds on `/mnt/c` are much slower and lose Unix permissions.

## 3. Bootstrap tooling

```bash
cd ~/src/survival-os
scripts/dev/wsl2-bootstrap.sh --dry-run   # review
scripts/dev/wsl2-bootstrap.sh             # install (uses sudo apt-get)
scripts/dev/wsl2-bootstrap.sh --check     # verify: python >= 3.11, FTS5, node >= 20, ssh, rsync...
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
python3 -m pytest
```

If the distro's Node.js is older than 20, install a current LTS from
nodejs.org or with `nvm`, then re-run `--check`.

Docker is not needed until Phase 9. When it is, use either Docker Desktop with
the WSL2 backend or Docker Engine installed inside the distro.

## 4. SSH access to the Pi

1. When you write the Pi OS Lite test SD card with Raspberry Pi Imager, use
   OS customisation to set a hostname, a user, and **SSH with public-key
   authentication only**. Paste the contents of `~/.ssh/id_ed25519.pub` from
   WSL.
2. Test it: `ssh <user>@<pi-host> 'uname -a'`.
3. Optional `~/.ssh/config` entry:

   ```
   Host survival
     HostName <pi-ip-or-name>
     User <user>
     IdentityFile ~/.ssh/id_ed25519
   ```

SSH is a development convenience. The release image ships with SSH disabled.

## 5. Running Claude Code

Run Claude Code inside the WSL2 shell, from the repository directory, so it
uses the same Linux tools and SSH config as above.

## 6. Pi dev loop

The dev loop needs key-based SSH and passwordless sudo on the Pi. Passwordless sudo is for
development only and must never ship in a release image. To add it, run this on the Pi:

```
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/090-dev
sudo chmod 440 /etc/sudoers.d/090-dev
sudo visudo -c
```

Set `SURVIVAL_HOST` to use a different SSH host name.

The Pi needs `cage` and `chromium` for the kiosk step, and `python3-venv` for the backend:

```
sudo apt-get install --no-install-recommends cage chromium python3-venv
```

Node 24 LTS is required (see `.nvmrc`). Debian's Node is too old, so install the official tarball
under `~/.local` after checking it against `SHASUMS256.txt`.

Commands:

| Command | What it does |
|---|---|
| `make setup` | Create the Python environment and install frontend packages |
| `make test` | Run backend tests, frontend tests and type checks, and validate manifests |
| `make deploy` | Build, sync to `~/survival-os-dev` on the Pi, restart the backend, check it |
| `make check` | Check the backend and page on the Pi |
| `make kiosk` | Show the deployed page on the Pi's screen |
| `make kiosk-stop` | Stop the kiosk and return to the console |

The backend and kiosk run as transient units, so they stop at reboot and nothing autostarts. The
backend listens on loopback only. To view it from the PC, use a tunnel, then open
<http://127.0.0.1:8080>:

```
ssh -L 8080:127.0.0.1:8080 survival
```

Frontend-only work can use `cd frontend && npm run dev`, with the tunnel providing the API.
