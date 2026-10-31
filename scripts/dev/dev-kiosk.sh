#!/usr/bin/env bash
# Show the deployed dashboard on the Pi's screen. Transient, nothing autostarts. Development only.
# The -s flag allows Ctrl+Alt+F2 to reach a text console; without it cage blocks VT switching.
set -euo pipefail

HOST="${SURVIVAL_HOST:-survival}"

case "${1:-}" in
  start)
    ssh "$HOST" 'bash -s' <<'REMOTE_SCRIPT'
set -euo pipefail
sudo -n systemctl stop survival-kiosk-dev 2>/dev/null || true
sudo -n systemctl reset-failed survival-kiosk-dev 2>/dev/null || true
sudo -n systemd-run -q --unit=survival-kiosk-dev --uid="$(id -u)" --gid="$(id -g)" \
  -p PAMName=login -p TTYPath=/dev/tty7 -p StandardInput=tty -p TTYReset=yes -p TTYVHangup=yes \
  -p StandardOutput=journal -p StandardError=journal -p Environment=XDG_SESSION_TYPE=wayland \
  -p Restart=always -p RestartSec=2 \
  /usr/bin/cage -s -- /usr/bin/chromium --ozone-platform=wayland --kiosk --no-first-run \
  --noerrdialogs --password-store=basic --user-data-dir=/tmp/survival-kiosk-dev \
  http://127.0.0.1:8080/
sudo -n chvt 7
REMOTE_SCRIPT
    ;;
  stop)
    ssh "$HOST" 'sudo -n systemctl stop survival-kiosk-dev; sudo -n chvt 1; rm -rf /tmp/survival-kiosk-dev'
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
