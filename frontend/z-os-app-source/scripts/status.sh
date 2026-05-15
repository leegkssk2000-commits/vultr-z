#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="/home/z/z/frontend"
echo "== canonical source status =="
echo "ROOT=$ROOT"
cat "$BASE/.z_app_source_root.env" 2>/dev/null || true
echo "-- package --"
node -e "const p=require('$ROOT/package.json'); console.log(p.name, p.scripts)" 2>/dev/null || cat "$ROOT/package.json"
echo "-- live --"
curl -k -L -sI "https://app.z-os.vip/?status=$(date +%s)" | grep -Ei 'date:|cache-control:|server:|x-zel-root:' || true
curl -k -L -s "https://app.z-os.vip/?status=$(date +%s)" -o /tmp/z_app_status_live.html
grep -nE 'assets/index-|_emergency_runtime_guard|zel_team|zuiTeam|TeamOverlay|ALIMI|source=baseline-preserve' /tmp/z_app_status_live.html || true
