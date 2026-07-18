#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/z/z}"
SHA="${2:?target sha required}"
OUT="$ROOT/runtime/exact25_edge_v1/r7a1a3b_exact_redaction_canonical_import"
WORK="$(mktemp -d /tmp/r7a1a3b.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
GIT=(git -C "$ROOT" -c "safe.directory=$ROOT")
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

mkdir -p "$WORK/tools" "$WORK/tests"
"${GIT[@]}" show "$SHA:backend/contracts/ZOS_R7A1A3B_EXACT_REDACTION_CANONICAL_IMPORT_v1.json" > "$WORK/contract.json"
"${GIT[@]}" show "$SHA:tools/r7a1a3b_exact_redaction_canonical_import.py" > "$WORK/tools/r7a1a3b_exact_redaction_canonical_import.py"
"${GIT[@]}" show "$SHA:tests/test_r7a1a3b_exact_redaction_canonical_import.py" > "$WORK/tests/test_r7a1a3b_exact_redaction_canonical_import.py"

"$PY" -m py_compile "$WORK/tools/r7a1a3b_exact_redaction_canonical_import.py"
(
  cd "$WORK"
  "$PY" -m pytest -q tests/test_r7a1a3b_exact_redaction_canonical_import.py
)

mkdir -p "$OUT"
"$PY" "$WORK/tools/r7a1a3b_exact_redaction_canonical_import.py" \
  --contract "$WORK/contract.json" \
  --target-sha "$SHA" \
  --output "$OUT/status_latest.json" \
  --report "$OUT/report_latest.md"
