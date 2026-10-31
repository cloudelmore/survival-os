#!/usr/bin/env bash
# Fail if the built frontend would load anything from the network at runtime.
set -euo pipefail
cd "$(dirname "$0")/../../frontend/dist"

pattern='(src|href)=["'"'"']?(https?:)?//|url\(["'"'"']?(https?:)?//|@import[^;]*https?:'
if grep -rEn "$pattern" --include='*.html' --include='*.css' .; then
  echo "Remote asset reference found" >&2
  exit 1
fi
if grep -rEln 'fetch\(["'"'"'`]https?:' --include='*.js' .; then
  echo "Remote fetch found" >&2
  exit 1
fi
echo "No remote assets in the build"
