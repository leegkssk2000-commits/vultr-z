#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:?target sha required}"
OUT_DIR="$ROOT/runtime/exact25_edge_v1/r7a0b_canonical_runtime_parity_audit"
OUT_JSON="$OUT_DIR/status_latest.json"
OUT_MD="$OUT_DIR/report_latest.md"
WORK="$(mktemp -d /tmp/r7a0b.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

GIT=(git -C "$ROOT" -c "safe.directory=$ROOT")
"${GIT[@]}" show "$SHA:backend/contracts/ZOS_R7A0B_CANONICAL_RUNTIME_PARITY_AUDIT_v2.json" > "$WORK/contract.json"
"${GIT[@]}" show "$SHA:tools/r7a0b_canonical_runtime_parity_audit.py" > "$WORK/audit.py"
python3 -m py_compile "$WORK/audit.py"
mkdir -p "$OUT_DIR"
python3 "$WORK/audit.py" \
  --contract "$WORK/contract.json" \
  --target-sha "$SHA" \
  --output "$OUT_JSON" \
  --report "$OUT_MD"
