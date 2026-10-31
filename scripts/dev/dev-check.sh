#!/usr/bin/env bash
# Confirm the development backend and dashboard respond on the Pi.
set -euo pipefail

HOST="${SURVIVAL_HOST:-survival}"

ssh "$HOST" 'bash -s' <<'REMOTE_SCRIPT'
set -euo pipefail
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1 && break
  sleep 1
done
echo "health: $(curl -fsS http://127.0.0.1:8080/api/health)"
curl -fsS http://127.0.0.1:8080/ | grep -q '<div id="root">' && echo "dashboard: served"
echo "listening: $(ss -ltnH 'sport = :8080' | awk '{print $4}')"
REMOTE_SCRIPT
