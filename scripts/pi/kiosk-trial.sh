#!/usr/bin/env bash
# SURVIVAL OS - Phase 1 kiosk trial (run on a TEST SD/USB boot of Pi OS Lite).
#
# Launches Chromium in kiosk mode under a Wayland compositor against a local
# test page, and samples memory use so Phase 2 can choose the compositor on
# measured numbers. Nothing is enabled at boot and no system config changes;
# the only persistent effect is the optional apt install.
#
# Run from the Pi's local console (tty1), NOT over SSH: the compositor needs
# the local seat.
#
#   scripts/pi/kiosk-trial.sh --install            # apt install candidates (asks first)
#   scripts/pi/kiosk-trial.sh cage                 # trial cage + Chromium
#   scripts/pi/kiosk-trial.sh labwc                # trial labwc + Chromium
#   scripts/pi/kiosk-trial.sh cage --rotate DSI-1:90   # rotate a portrait panel
#
# Leave the kiosk: Ctrl+W in Chromium closes it and the compositor exits.
# Ctrl+Alt+F2 switches to a text console (VT switching via the seat).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
page="file://$here/kiosk-trial/testpage.html"
logdir="$HOME/survival-kiosk-trial"

find_chromium() {
  local c
  for c in chromium chromium-browser; do
    command -v "$c" >/dev/null && { echo "$c"; return; }
  done
  return 1
}

if [[ "${1:-}" == "--install" ]]; then
  pkgs=(cage labwc wlr-randr)
  if apt-cache show chromium >/dev/null 2>&1; then pkgs+=(chromium); else pkgs+=(chromium-browser); fi
  echo "Will run: sudo apt-get install -y ${pkgs[*]}"
  read -r -p "Proceed on this TEST system? [y/N] " ans
  [[ $ans == [yY] ]] || { echo "aborted"; exit 1; }
  sudo apt-get update
  sudo apt-get install -y "${pkgs[@]}"
  exit 0
fi

comp="${1:?usage: $0 --install | cage|labwc [--rotate OUTPUT:DEGREES]}"
shift
rotate=""
if [[ "${1:-}" == "--rotate" ]]; then rotate="${2:?--rotate needs OUTPUT:DEGREES}"; shift 2; fi

case "$(tty)" in
  /dev/tty[0-9]*) ;;
  *) echo "Run this from the local console (tty1), not SSH or a terminal emulator." >&2; exit 1 ;;
esac
command -v "$comp" >/dev/null || { echo "$comp not installed; run with --install" >&2; exit 1; }
browser="$(find_chromium)" || { echo "Chromium not installed; run with --install" >&2; exit 1; }

mkdir -p "$logdir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
memlog="$logdir/mem-$comp-$stamp.tsv"
profile="$(mktemp -d)"
cfgdir="$(mktemp -d)"

launch="$browser --kiosk --ozone-platform=wayland --noerrdialogs --disable-infobars \
--no-first-run --password-store=basic --disable-features=Translate \
--user-data-dir=$profile $page"
if [[ -n $rotate ]]; then
  command -v wlr-randr >/dev/null || { echo "wlr-randr needed for --rotate" >&2; exit 1; }
  launch="wlr-randr --output ${rotate%%:*} --transform ${rotate##*:}; exec $launch"
fi

# Sample proportional set size (PSS) of the compositor + browser every 5 s.
sample() {
  printf 'utc\tmem_available_kib\tkiosk_pss_kib\tprocesses\n' >"$memlog"
  while sleep 5; do
    local total=0 n=0 pid pss
    for pid in $(pgrep -u "$USER" -f "^($comp|.*$browser)" || true); do
      pss="$(awk '/^Pss:/ {print $2}' "/proc/$pid/smaps_rollup" 2>/dev/null || echo 0)"
      total=$((total + ${pss:-0})); n=$((n + 1))
    done
    printf '%s\t%s\t%s\t%s\n' "$(date -u +%H:%M:%S)" \
      "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)" "$total" "$n" >>"$memlog"
  done
}
sample &
sampler=$!
trap 'kill $sampler 2>/dev/null || true; rm -rf "$profile" "$cfgdir"' EXIT

echo "Starting $comp + $browser. Memory log: $memlog"
start=$(date +%s)
case "$comp" in
  cage)  cage -- sh -c "$launch" ;;
  labwc) labwc -C "$cfgdir" -s "sh -c '$launch'" ;;
  *) echo "unsupported compositor: $comp" >&2; exit 2 ;;
esac
status=$?
echo "Compositor exited with status $status after $(( $(date +%s) - start )) s."
echo "Peak kiosk PSS (KiB): $(awk 'NR>1 && $3>m {m=$3} END {print m+0}' "$memlog")"
echo "Min MemAvailable (KiB): $(awk 'NR==2 {m=$2} NR>1 && $2<m {m=$2} END {print m+0}' "$memlog")"
