#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
RC=2

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_START' \
  'MODE=READ_ONLY_MA5_ROLLBACK_PARENT_EXACT_VARIANT_REBIND_AND_EXISTING_SIX_STRESS_AB' \
  'EXPECTED_LANE_ID=dual_ma_trend_bot:5m' \
  'EXPECTED_REPAIR_AXIS=STATE_RESET_COOLDOWN' \
  'EXPECTED_REPAIR_MECHANISM=REENTRY_CHURN' \
  'EXPECTED_STRESS_CELL_COUNT=6' \
  'PARENT_SOURCE=SECOND_WAVE_ROLLBACK_CONTROL' \
  'PARENT_LANE_FIELD_COMPAT=lane_id_or_source_lane_id' \
  'PARENT_VARIANT_FIELD_COMPAT=control_variant_id_or_variant_id' \
  'EXACT_LANE_BEST_VARIANT_REQUIRED=true' \
  'PATCH_SCOPE=temporary_execution_copy_only' \
  'PARENT_IMMUTABLE=true' \
  'CHILD_ONLY_REPAIR=true' \
  'ATR5_ROBUST_PARENT_PRESERVED=true' \
  'ATR15_INCREMENTAL_PARENT_PRESERVED=true' \
  'DONCHIAN15_REFERENCE_PRESERVED=true' \
  'KEEP14_UNTOUCHED=true' \
  'SAME_FROZEN_DATA_AND_COSTS_REQUIRED=true' \
  'NO_STOP_WIDENING=true' \
  'NO_ENTRY_THRESHOLD_RELAXATION=true' \
  'NO_PARAMETER_OPTIMIZATION=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_incremental_defect3b_payoff_geometry_all_loss_audit/incremental_defect3b_payoff_geometry_all_loss_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_summary_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-defect3b-parent-lineage-fix.XXXXXX)" || exit 2
EXEC="$TMP/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py"

if ! git -C "$ROOT" show \
  "$SHA:tools/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py" \
  > "$EXEC"
then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 - "$EXEC" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''    parent_rows = [row for row in trades if str(row.get("lane_id") or "") == LANE_ID]\n    cells = {cell_key(row) for row in parent_rows}\n'''
new = '''    lane_best_rows = {\n        str(row.get("lane_id") or row.get("source_lane_id") or ""): row\n        for row in second_summary.get("lane_best_rows") or []\n        if isinstance(row, dict)\n    }\n    ma5_best = dict(lane_best_rows.get(LANE_ID) or {})\n    expected_variant = str(\n        ma5_best.get("variant_id")\n        or ma5_best.get("control_variant_id")\n        or ""\n    )\n    if not expected_variant:\n        blockers.append("MA5_PARENT_VARIANT_MISSING")\n    parent_rows = [\n        {\n            **row,\n            "lane_id": LANE_ID,\n            "control_variant_id": expected_variant,\n        }\n        for row in trades\n        if expected_variant\n        and str(row.get("lane_id") or row.get("source_lane_id") or "") == LANE_ID\n        and str(row.get("control_variant_id") or row.get("variant_id") or "") == expected_variant\n    ]\n    cells = {cell_key(row) for row in parent_rows}\n'''
if text.count(old) != 1:
    print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT")
    print("BLOCKER_COUNT=1")
    print('BLOCKERS=["PARENT_SELECTION_PATCH_ANCHOR_MISMATCH"]')
    print("RC=2")
    raise SystemExit(2)
path.write_text(text.replace(old, new), encoding="utf-8")
print("STATE=PASS_INCREMENTAL_DEFECT3B_PARENT_LINEAGE_TEMP_PATCH")
print("PATCH_SCOPE=temporary_execution_copy_only")
print("RC=0")
PY
PATCH_RC=$?
if [[ "$PATCH_RC" -ne 0 ]]; then
  exit "$PATCH_RC"
fi

python3 - "$ROOT" <<'PY'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
summary_path = root / "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json"
trades_path = root / "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
trades = [json.loads(line) for line in trades_path.read_text(encoding="utf-8").splitlines() if line.strip()]
lane_id = "dual_ma_trend_bot:5m"
lane_best_rows = {
    str(row.get("lane_id") or row.get("source_lane_id") or ""): row
    for row in summary.get("lane_best_rows") or []
    if isinstance(row, dict)
}
best = dict(lane_best_rows.get(lane_id) or {})
variant = str(best.get("variant_id") or best.get("control_variant_id") or "")
rows = [
    row for row in trades
    if variant
    and str(row.get("lane_id") or row.get("source_lane_id") or "") == lane_id
    and str(row.get("control_variant_id") or row.get("variant_id") or "") == variant
]
cells = {
    (
        str(row.get("cost_profile_id") or ""),
        str(row.get("timing_id") or "timing_0"),
    )
    for row in rows
}
print("MA5_PARENT_VARIANT_ID=" + json.dumps(variant))
print("MA5_PARENT_ROW_COUNT=" + str(len(rows)))
print("MA5_PARENT_CELL_COUNT=" + str(len(cells)))
print("MA5_PARENT_CELL_KEYS=" + json.dumps(sorted(cells)))
print("MA5_PARENT_BINDING_MODE=LANE_BEST_EXACT_VARIANT")
if not variant:
    print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT")
    print("BLOCKER_COUNT=1")
    print('BLOCKERS=["MA5_PARENT_VARIANT_MISSING"]')
    print("RC=2")
    raise SystemExit(2)
if not rows:
    print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT")
    print("BLOCKER_COUNT=1")
    print('BLOCKERS=["MA5_PARENT_ROWS_MISSING_AFTER_EXACT_REBIND"]')
    print("RC=2")
    raise SystemExit(2)
if len(cells) != 6:
    print("STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT")
    print("BLOCKER_COUNT=1")
    print('BLOCKERS=["MA5_PARENT_STRESS_CELL_COUNT_NOT_SIX"]')
    print("RC=2")
    raise SystemExit(2)
print("STATE=PASS_INCREMENTAL_DEFECT3B_MA5_PARENT_LINEAGE_PREFLIGHT")
print("RC=0")
PY
PREFLIGHT_RC=$?
if [[ "$PREFLIGHT_RC" -ne 0 ]]; then
  exit "$PREFLIGHT_RC"
fi

if ! python3 -m py_compile "$EXEC"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$EXEC" --self-test; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$EXEC" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_LINEAGE_FIX_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
