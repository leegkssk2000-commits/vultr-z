#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/z/z}"
SHA="${2:?target sha required}"
OUT_DIR="$ROOT/runtime/exact25_edge_v1/r7a1a2_canonical_source_import_plan"
WORK="$(mktemp -d /tmp/r7a1a2.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
GIT=(git -C "$ROOT" -c "safe.directory=$ROOT")
"${GIT[@]}" show "$SHA:backend/contracts/ZOS_R7A1A2_CANONICAL_SOURCE_IMPORT_PLAN_v1.json" > "$WORK/contract.json"
"${GIT[@]}" show "$SHA:tools/r7a1a2_canonical_source_import_plan.py" > "$WORK/plan.py"
python3 -m py_compile "$WORK/plan.py"
mkdir -p "$OUT_DIR"
python3 "$WORK/plan.py" \
  --contract "$WORK/contract.json" \
  --target-sha "$SHA" \
  --output "$OUT_DIR/status_latest.json" \
  --report "$OUT_DIR/report_latest.md"
