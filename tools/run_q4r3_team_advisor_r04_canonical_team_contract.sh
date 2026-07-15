#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

CONTRACT="$WT/config/q4r3_team_canonical_contract_v1.json"
RECOVERY="$ROOT/runtime/exact25_edge_v1/team_advisor_r03_team_assignment_recovery/status_latest.json"
MODULE="$WT/tools/q4r3_team_advisor_r04_validate_canonical_team_contract.py"
TEST="$WT/tests/test_q4r3_team_advisor_r04_canonical_team_contract.py"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r04_canonical_team_contract/status_latest.json"

for required in "$CONTRACT" "$RECOVERY" "$MODULE" "$TEST"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"
mkdir -p "$(dirname "$OUT")"
"$PY" "$MODULE" --contract "$CONTRACT" --recovery "$RECOVERY" --output "$OUT"

"$PY" - "$OUT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("state")=="PASS", p
assert p.get("verdict")=="R04_CANONICAL_TEAM_CONTRACT_LOCK_PASS", p
assert p.get("blockers")==[], p
assert p.get("summary",{}).get("team_count")==4, p
assert p.get("summary",{}).get("zbot_external_only") is True, p
assert p.get("authority",{}).get("runtime_mutation_performed") is False, p
assert p.get("authority",{}).get("execution_authority")=="none", p
print("R04_OUTPUT_GATE=PASS")
PY

echo Q4R3_TEAM_ADVISOR_R04_CANONICAL_TEAM_CONTRACT_COMPLETE
echo "STATUS=$OUT"
