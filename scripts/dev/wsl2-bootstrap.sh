#!/usr/bin/env bash
# SURVIVAL OS - Phase 1 dev environment bootstrap for WSL2 (Debian 13 or Ubuntu).
#
# Installs the Linux-side tooling used to build and deploy SURVIVAL OS from a
# Windows PC. It only touches the WSL2 distro: apt packages and, if missing,
# an SSH key in ~/.ssh. It never contacts the Pi.
#
#   scripts/dev/wsl2-bootstrap.sh --dry-run   # show what would happen
#   scripts/dev/wsl2-bootstrap.sh             # install
#   scripts/dev/wsl2-bootstrap.sh --check     # only verify versions
set -euo pipefail

MIN_PYTHON="3.11"
MIN_NODE_MAJOR=20

PACKAGES=(
  git openssh-client rsync curl ca-certificates jq xz-utils unzip
  python3 python3-venv python3-pip sqlite3 build-essential
  nodejs npm shellcheck
  qemu-user-static binfmt-support   # ARM64 emulation for later image builds
)

mode="install"
case "${1:-}" in
  --dry-run) mode="dry-run" ;;
  --check) mode="check" ;;
  "") ;;
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

log() { printf '[bootstrap] %s\n' "$*"; }
run() {
  if [[ $mode == dry-run ]]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi
}

version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

check_env() {
  if ! grep -qi microsoft /proc/version 2>/dev/null; then
    log "WARNING: this does not look like WSL2. Continuing anyway."
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  log "distro: ${PRETTY_NAME:-unknown}"
  case "${ID:-}" in
    debian|ubuntu) ;;
    *) log "WARNING: only Debian/Ubuntu WSL distros are tested." ;;
  esac
}

verify() {
  local ok=1
  local py node_v
  py="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
  if version_ge "$py" "$MIN_PYTHON"; then log "python3 $py ok"; else log "python3 $py < $MIN_PYTHON"; ok=0; fi
  if python3 -c 'import sqlite3; sqlite3.connect(":memory:").execute("create virtual table t using fts5(x)")'; then
    log "sqlite3 FTS5 ok"
  else
    log "sqlite3 FTS5 missing"; ok=0
  fi
  node_v="$(node --version 2>/dev/null | sed 's/^v//' || echo 0)"
  if [[ ${node_v%%.*} -ge $MIN_NODE_MAJOR ]] 2>/dev/null; then log "node $node_v ok"; else log "node $node_v < $MIN_NODE_MAJOR"; ok=0; fi
  for t in git ssh rsync shellcheck jq xz; do
    if command -v "$t" >/dev/null; then log "$t ok"; else log "$t missing"; ok=0; fi
  done
  if [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
    log "qemu-aarch64 binfmt ok"
  else
    log "qemu-aarch64 binfmt not registered (needed only for Phase 9 image builds)"
  fi
  [[ $ok == 1 ]]
}

check_env
if [[ $mode == check ]]; then verify; exit $?; fi

log "installing packages: ${PACKAGES[*]}"
run sudo apt-get update
run sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}"

if [[ ! -f "$HOME/.ssh/id_ed25519" ]]; then
  log "creating SSH key ~/.ssh/id_ed25519 (you will be asked for a passphrase)"
  run mkdir -p "$HOME/.ssh"
  run chmod 700 "$HOME/.ssh"
  run ssh-keygen -t ed25519 -C "survival-os-dev" -f "$HOME/.ssh/id_ed25519"
else
  log "SSH key already present: ~/.ssh/id_ed25519"
fi

if [[ $mode == install ]]; then
  verify || { log "verification FAILED, see above"; exit 1; }
fi

cat <<'EOF'

Next steps (see docs/dev/windows-wsl2-setup.md):
  1. Copy your key to the Pi:   ssh-copy-id <user>@<pi-host>
  2. Inspect the Pi hardware:   scripts/dev/pi-remote-inspect.sh <user>@<pi-host>
EOF
