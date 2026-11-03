#!/usr/bin/env bash
# Install, enable or remove the SURVIVAL OS dashboard on Raspberry Pi OS Lite.
#
#   install.sh --dry-run     show what --apply would do, and change nothing
#   install.sh --apply       install services without enabling them at boot
#   install.sh --enable      boot straight into the dashboard from now on
#   install.sh --disable     boot to the normal console again, keeping the install
#   install.sh --uninstall   remove everything except saved settings
#
# Run from a source tree holding backend/, systemd/ and frontend/dist/. --dry-run needs no root.
# Disk layout and user data are never touched.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/survival-os
ETC=/etc/systemd/system
SUDOERS=/etc/sudoers.d/survival-os
UNITS=(survival-api.service survival-web.service survival-kiosk.service
       survival-indexer.service survival-kiwix.service survival-content.service
       survival-usb.service survival-usb-export.service survival-maintenance.target survival-maintenance-boot.service)
BOOT_UNITS=(survival-api.service survival-web.service survival-kiosk.service
            survival-indexer.service survival-kiwix.service
            survival-maintenance-boot.service)
PACKAGES=(nginx-light libnginx-mod-http-subs-filter cage chromium python3-venv kiwix-tools esptool
          python3-meshtastic)

MODE="${1:---dry-run}"
DRY=0
[ "$MODE" = "--dry-run" ] && DRY=1

run() {
  echo "+ $*"
  [ "$DRY" = 1 ] || "$@"
}

preflight() {
  grep -qa "Raspberry Pi 5" /proc/device-tree/model || { echo "Not a Raspberry Pi 5" >&2; exit 1; }
  [ "$(dpkg --print-architecture)" = arm64 ] || { echo "Needs arm64" >&2; exit 1; }
  grep -q 'VERSION_CODENAME=trixie' /etc/os-release || { echo "Needs Debian 13 trixie" >&2; exit 1; }
  [ -f "$SRC/frontend/dist/index.html" ] || { echo "Missing frontend/dist, build first" >&2; exit 1; }
  echo "Preflight passed: Pi 5, arm64, trixie, $(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo) GiB RAM"
}

need_root() {
  [ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "Run as root" >&2; exit 1; }
}

ensure_user() {
  local name=$1 groups=$2
  id "$name" >/dev/null 2>&1 && { echo "User $name exists"; return; }
  shift 2
  run useradd --system --shell /usr/sbin/nologin --groups "$groups" "$@" "$name"
}

apply() {
  # nginx would otherwise start on port 80 on all interfaces as soon as it is installed.
  run systemctl mask nginx.service
  run apt-get install -y --no-install-recommends "${PACKAGES[@]}"
  ensure_user survival video --no-create-home
  ensure_user kiosk video,render,input --create-home --home-dir /var/lib/survival-kiosk
  run mkdir -p "$APP"
  run rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.egg-info' \
    "$SRC/backend/" "$APP/backend/"
  run rsync -a --delete --exclude .venv --exclude __pycache__ --exclude '*.egg-info' \
    "$SRC/search/" "$APP/search/"
  run rsync -a --delete "$SRC/frontend/dist/" "$APP/frontend/"
  run install -m 644 "$SRC/systemd/nginx.conf" "$APP/nginx.conf"
  run rsync -a --delete "$SRC/content-manifests/" "$APP/content-manifests/"
  run install -d -m 755 "$APP/bin"
  run install -m 755 -o root -g root "$SRC/installers/survival-usb" "$APP/bin/survival-usb"
  [ -x "$APP/venv/bin/python" ] || run python3 -m venv "$APP/venv"
  run "$APP/venv/bin/python" -m pip install -q --disable-pip-version-check "$APP/search" "$APP/backend"
  for unit in "${UNITS[@]}"; do
    run install -m 644 "$SRC/systemd/$unit" "$ETC/$unit"
  done
  run visudo -cf "$SRC/systemd/survival-os.sudoers"
  run install -m 440 "$SRC/systemd/survival-os.sudoers" "$SUDOERS"
  run systemctl daemon-reload
  run systemctl restart survival-api.service survival-web.service
  run systemctl try-restart survival-indexer.service survival-kiwix.service
  echo "Installed. Nothing starts at boot until --enable."
}

enable() {
  run systemctl disable getty@tty1.service
  run systemctl enable "${BOOT_UNITS[@]}"
  echo "The dashboard starts at the next boot."
}

disable() {
  run systemctl disable "${BOOT_UNITS[@]}"
  run systemctl enable getty@tty1.service
  echo "The normal console returns at the next boot."
}

uninstall() {
  disable
  run systemctl stop survival-kiosk.service survival-indexer.service survival-kiwix.service \
    survival-content.service survival-usb.service survival-web.service survival-api.service
  for unit in "${UNITS[@]}"; do
    run rm -f "$ETC/$unit"
  done
  run rm -f "$SUDOERS"
  run rm -rf "$APP"
  run systemctl daemon-reload
  run systemctl start getty@tty1.service
  run userdel survival
  # The kiosk session manager outlives the service and blocks userdel.
  id kiosk >/dev/null 2>&1 && run systemctl stop "user@$(id -u kiosk).service"
  run userdel --remove kiosk
  run systemctl unmask nginx.service
  echo "Removed. Saved settings remain in /var/lib/survival-os."
}

need_root
case "$MODE" in
  --dry-run|--apply) preflight; apply ;;
  --enable) enable ;;
  --disable) disable ;;
  --uninstall) uninstall ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
