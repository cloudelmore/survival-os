#!/usr/bin/env bash
# Run the read-only hardware inspection on the Pi over SSH and save the report.
#
#   scripts/dev/pi-remote-inspect.sh pi@survival.local          # as normal user
#   scripts/dev/pi-remote-inspect.sh --sudo pi@survival.local   # adds NVMe SMART
#
# Copies inspect_hardware.py to a temporary directory on the Pi, runs it,
# copies the JSON report back to reports/, and removes the temp directory.
# Nothing on the Pi is installed or changed.
set -euo pipefail

use_sudo=0
if [[ "${1:-}" == "--sudo" ]]; then use_sudo=1; shift; fi
host="${1:?usage: $0 [--sudo] user@pi-host}"

repo="$(cd "$(dirname "$0")/../.." && pwd)"
script="$repo/scripts/pi/inspect_hardware.py"
outdir="$repo/reports"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$outdir/hardware-$stamp.json"
mkdir -p "$outdir"

remote_dir="$(ssh "$host" 'mktemp -d /tmp/survival-inspect.XXXXXX')"
trap 'ssh "$host" "rm -rf -- $remote_dir" >/dev/null 2>&1 || true' EXIT

scp -q "$script" "$host:$remote_dir/inspect_hardware.py"
prefix=""
if [[ $use_sudo == 1 ]]; then prefix="sudo "; fi
# -t so sudo can prompt for a password; the report is written to a file.
ssh -t "$host" "${prefix}python3 $remote_dir/inspect_hardware.py --output $remote_dir/report.json"
if [[ $use_sudo == 1 ]]; then
  # shellcheck disable=SC2029  # remote_dir is a known path; $(id) is escaped to run remotely
  ssh "$host" "sudo chown \$(id -u):\$(id -g) $remote_dir/report.json"
fi
scp -q "$host:$remote_dir/report.json" "$out"
echo
echo "Report saved: $out"
echo "reports/ is git-ignored. Review it before sharing; it contains device details."
