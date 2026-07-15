#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

R0_DIR="$ROOT/runtime/exact25_edge_v1/team_advisor_r0_canonical_truth"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r01_owner_adjudication"
MODULE="$WT/tools/q4r3_team_advisor_r01_owner_adjudication.py"
TEST="$WT/tests/test_q4r3_team_advisor_r01_owner_adjudication.py"

for required in \
  "$R0_DIR/status_latest.json" \
  "$R0_DIR/candidates_latest.json" \
  "$R0_DIR/units_latest.json" \
  "$MODULE" \
  "$TEST"
do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"
mkdir -p "$OUT"

"$PY" "$MODULE" \
  --root "$ROOT" \
  --r0-truth "$R0_DIR/status_latest.json" \
  --r0-candidates "$R0_DIR/candidates_latest.json" \
  --r0-units "$R0_DIR/units_latest.json" \
  --output-json "$OUT/status_latest.json" \
  --output-md "$OUT/owner_adjudication_latest.md"

"$PY" - "$OUT/status_latest.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("schema")=="q4r3_team_advisor_r01_owner_adjudication_v1"
assert p.get("state")=="HOLD"
assert p.get("verdict")=="R01_OWNER_ADJUDICATION_PLAN_READY"
assert len(p.get("components",{}))==12
assert len(p.get("fix_queue",[]))==12
assert p.get("canonical_name_violations")==[]
assert p.get("authority",{}).get("runtime_mutation_performed") is False
assert p.get("authority",{}).get("order_authority")=="blocked"
assert p.get("authority",{}).get("execution_authority")=="none"
assert p.get("publication",{}).get("raw_source_text_included") is False
print("R01_OUTPUT_SCHEMA=PASS")
PY

echo Q4R3_TEAM_ADVISOR_R01_OWNER_ADJUDICATION_COMPLETE
echo "OUTPUT_JSON=$OUT/status_latest.json"
echo "OUTPUT_MD=$OUT/owner_adjudication_latest.md"
