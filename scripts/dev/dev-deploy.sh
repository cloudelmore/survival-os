#!/usr/bin/env bash
# Sync a built tree to the Pi and restart the development backend. Development only.
set -euo pipefail
cd "$(dirname "$0")/../.."

HOST="${SURVIVAL_HOST:-survival}"
REMOTE=survival-os-dev

[ -f frontend/dist/index.html ] || { echo "Run 'make build' first" >&2; exit 1; }

rsync -az --delete --relative \
  --exclude .venv --exclude __pycache__ --exclude '*.egg-info' \
  backend/ content-manifests/ frontend/dist/ "$HOST:$REMOTE/"

ssh "$HOST" REMOTE="$REMOTE" 'bash -s' <<'REMOTE_SCRIPT'
set -euo pipefail
cd "$HOME/$REMOTE"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check ./backend
sudo -n systemctl stop survival-backend-dev 2>/dev/null || true
sudo -n systemctl reset-failed survival-backend-dev 2>/dev/null || true
sudo -n systemd-run -q --unit=survival-backend-dev --uid="$(id -u)" --gid="$(id -g)" \
  --working-directory="$PWD" -p Environment=SURVIVAL_STATIC_DIR="$PWD/frontend/dist" \
  -p Restart=on-failure "$PWD/.venv/bin/uvicorn" survival_os.main:app \
  --host 127.0.0.1 --port 8080 --log-level warning
REMOTE_SCRIPT

scripts/dev/dev-check.sh
