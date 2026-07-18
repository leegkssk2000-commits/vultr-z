#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/z/z}"
SHA="${2:?target sha required}"
BASE="$ROOT/runtime/exact25_edge_v1/r7a0b_canonical_runtime_parity_audit/status_latest.json"
OUT_DIR="$ROOT/runtime/exact25_edge_v1/r7a0c_audit_correctness_patch"
OUT_JSON="$OUT_DIR/status_latest.json"
OUT_MD="$OUT_DIR/report_latest.md"
WORK="$(mktemp -d /tmp/r7a0c.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
GIT=(git -C "$ROOT" -c "safe.directory=$ROOT")
for file in \
  tools/r7a0c_filter_false_positives.py \
  tools/r7a0c_reclassify_authority.py \
  tools/r7a0c_finalize_corrected_audit.py; do
  "${GIT[@]}" show "$SHA:$file" > "$WORK/$(basename "$file")"
done
for file in "$WORK"/*.py; do python3 -m py_compile "$file"; done
test -s "$BASE"
mkdir -p "$OUT_DIR"
python3 "$WORK/r7a0c_filter_false_positives.py" --input "$BASE" --output "$WORK/c1.json"
python3 "$WORK/r7a0c_reclassify_authority.py" --input "$WORK/c1.json" --output "$WORK/c2.json"
python3 "$WORK/r7a0c_finalize_corrected_audit.py" --input "$WORK/c2.json" --output "$OUT_JSON" --report "$OUT_MD"
