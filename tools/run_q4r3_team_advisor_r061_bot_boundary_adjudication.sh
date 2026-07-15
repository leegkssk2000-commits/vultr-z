#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

MODULE="$WT/tools/q4r3_team_advisor_r061_bot_boundary_adjudication.py"
TEST="$WT/tests/test_q4r3_team_advisor_r061_bot_boundary_adjudication.py"
INPUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r06_bot_capability_inventory/status_latest.json"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r061_bot_boundary_adjudication/status_latest.json"

for required in "$MODULE" "$TEST" "$INPUT"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"
mkdir -p "$(dirname "$OUT")"
"$PY" "$MODULE" --inventory "$INPUT" --output "$OUT"
"$PY" - "$OUT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("state")=="PASS", p
assert p.get("verdict")=="R061_BOT_BOUNDARIES_LOCKED", p
assert p.get("summary",{}).get("candidate_count")==14, p
assert p.get("summary",{}).get("core_owner_count")==4, p
assert p.get("summary",{}).get("unresolved_boundary_count")==0, p
assert p.get("blockers")==[], p
assert p.get("authority",{}).get("runtime_mutation_performed") is False, p
print("R061_OUTPUT_GATE=PASS")
PY

echo Q4R3_TEAM_ADVISOR_R061_BOUNDARY_ADJUDICATION_COMPLETE
echo "STATUS=$OUT"
