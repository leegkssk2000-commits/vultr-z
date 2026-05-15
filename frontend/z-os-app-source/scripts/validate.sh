#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
echo "== validate canonical app source/dist =="
echo "ROOT=$ROOT"
echo "DIST=$DIST"
[ "$(basename "$ROOT")" = "z-os-app-source" ] || { echo "FAIL: wrong source root basename: $ROOT" >&2; exit 1; }
[ -f "$ROOT/package.json" ] || { echo "FAIL: package.json missing" >&2; exit 1; }
[ -f "$DIST/index.html" ] || { echo "FAIL: dist/index.html missing" >&2; exit 1; }
[ -d "$DIST/assets" ] || { echo "FAIL: dist/assets missing" >&2; exit 1; }

echo "-- dist index refs --"
grep -nE 'assets/index-|_emergency_runtime_guard|zel_team|zuiTeam|TeamOverlay|ALIMI|source=baseline-preserve' "$DIST/index.html" || true

echo "-- dist asset token scan --"
JS="$(grep -oE '/assets/index-[^"]+\.js' "$DIST/index.html" | head -1 || true)"
echo "DIST_JS=${JS:-none}"
if [ -n "$JS" ] && [ -f "$DIST$JS" ]; then
  grep -oE 'ALIMI|Operational Console|TeamOverlay|zuiTeamOverlayModalV4|RouteTeamsPanel|data-zr-route-teams-panel|MutationObserver|setInterval|OrderBook|bookTicker|BTCUSDT' "$DIST$JS" | sort | uniq -c || true
fi

echo "-- source root guard --"
case "$ROOT" in
  */z-os-alimi|*/z-os-pwa|*/dist|*/node_modules|*/backup*|*/.backup*|*/ZEL_ALIMI_MESSENGER_RESTORE*|*/repo_snapshot*)
    echo "FAIL: forbidden source root: $ROOT" >&2
    exit 1
    ;;
esac

echo "RESULT=PASS_VALIDATE_CANONICAL_SOURCE_ROOT"
