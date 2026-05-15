#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
echo "== build from preserved live baseline =="
echo "ROOT=$ROOT"
[ -f "$ROOT/baseline/index.html" ] || { echo "FAIL: baseline/index.html missing" >&2; exit 1; }
[ -d "$ROOT/baseline/assets" ] || { echo "FAIL: baseline/assets missing" >&2; exit 1; }
rm -rf "$ROOT/dist"
mkdir -p "$ROOT/dist"
rsync -a --delete "$ROOT/baseline/" "$ROOT/dist/"
printf '\n<!-- z-os-app-canonical-source build=%s source=baseline-preserve -->\n' "$TS" >> "$ROOT/dist/index.html"
echo "BUILT_DIST=$ROOT/dist"
