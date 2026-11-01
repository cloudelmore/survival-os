#!/usr/bin/env bash
# Run the production installer on the Pi: dev-install.sh --dry-run|--apply|--enable|--disable|--uninstall
set -euo pipefail
cd "$(dirname "$0")/../.."

HOST="${SURVIVAL_HOST:-survival}"
MODE="${1:---dry-run}"

[ -f frontend/dist/index.html ] || { echo "Run 'make build' first" >&2; exit 1; }
rsync -az --delete --relative --exclude .venv --exclude __pycache__ --exclude '*.egg-info' \
  backend/ search/ content-manifests/ frontend/dist/ installers/ systemd/ "$HOST:survival-os-dev/"
ssh -n "$HOST" "cd survival-os-dev && sudo -n installers/install.sh $MODE"
