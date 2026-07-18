#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/z/z}"
SHA="${2:?target sha required}"
OUT="$ROOT/runtime/exact25_edge_v1/r7a1a3_canonical_import_preflight"
WORK="$(mktemp -d /tmp/r7a1a3.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
GIT=(git -C "$ROOT" -c "safe.directory=$ROOT")
"${GIT[@]}" show "$SHA:backend/contracts/ZOS_R7A1A3_CANONICAL_IMPORT_PREFLIGHT_v1.json" > "$WORK/contract.json"
"${GIT[@]}" show "$SHA:tools/r7a1a3_canonical_import_preflight.py" > "$WORK/preflight.py"
python3 -m py_compile "$WORK/preflight.py"
mkdir -p "$OUT"
python3 "$WORK/preflight.py" \
  --contract "$WORK/contract.json" \
  --target-sha "$SHA" \
  --output "$OUT/status_latest.json" \
  --report "$OUT/report_latest.md"
