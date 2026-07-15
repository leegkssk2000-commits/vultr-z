#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

MODULE="$WT/tools/q4r3_team_advisor_r06_bot_capability_inventory.py"
TEST="$WT/tests/test_q4r3_team_advisor_r06_bot_capability_inventory.py"
INVENTORY="$ROOT/runtime/exact25_edge_v1/team_advisor_r0_canonical_truth/candidates_latest.json"
TEAM="$ROOT/runtime/exact25_edge_v1/team_advisor_r05_canonical_team_package/status_latest.json"
OUT="$ROOT/runtime/exact25_edge_v1/team_advisor_r06_bot_capability_inventory/status_latest.json"

for required in "$MODULE" "$TEST" "$INVENTORY" "$TEAM"; do
  [[ -f "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

"$PY" -m py_compile "$MODULE"
PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST"
mkdir -p "$(dirname "$OUT")"
set +e
"$PY" "$MODULE" --root "$ROOT" --inventory "$INVENTORY" --team-evidence "$TEAM" --output "$OUT"
AUDIT_RC=$?
set -e
"$PY" - "$OUT" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
assert p.get("schema")=="q4r3_team_advisor_r06_bot_capability_inventory_v1", p
assert p.get("state") in {"PASS","HOLD"}, p
assert p.get("summary",{}).get("component_count")==4, p
assert set(p.get("components",{}))=={"LBot","MBot","OBot","SBot"}, p
assert p.get("authority",{}).get("runtime_mutation_performed") is False, p
assert p.get("authority",{}).get("execution_authority")=="none", p
print("R06_OUTPUT_SCHEMA=PASS")
PY

echo "R06_AUDIT_RC=$AUDIT_RC"
echo Q4R3_TEAM_ADVISOR_R06_CAPABILITY_INVENTORY_COMPLETE
echo "STATUS=$OUT"
