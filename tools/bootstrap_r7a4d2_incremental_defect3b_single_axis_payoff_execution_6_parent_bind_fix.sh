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
  'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_START' \
  'MODE=READ_ONLY_MA5_SECOND_WAVE_ROLLBACK_PARENT_CANONICAL_REBIND_AND_SIX_STRESS_AB' \
  'EXPECTED_LANE_ID=dual_ma_trend_bot:5m' \
  'PARENT_SOURCE=SECOND_WAVE_ROLLBACK_CONTROL' \
  'LANE_FIELD_COMPAT=lane_id,source_lane_id' \
  'VARIANT_FIELD_COMPAT=control_variant_id,variant_id' \
  'EXPECTED_STRESS_CELL_COUNT=6' \
  'REPAIR_AXIS=STATE_RESET_COOLDOWN' \
  'REPAIR_MECHANISM=REENTRY_CHURN' \
  'PARENT_IMMUTABLE=true' \
  'CHILD_ONLY_REPAIR=true' \
  'SAME_FROZEN_DATA_AND_COSTS_REQUIRED=true' \
  'NO_STOP_WIDENING=true' \
  'NO_ENTRY_THRESHOLD_RELAXATION=true' \
  'NO_PARAMETER_OPTIMIZATION=true' \
  'ATR5_ROBUST_PARENT_PRESERVED=true' \
  'ATR15_INCREMENTAL_PARENT_PRESERVED=true' \
  'DONCHIAN15_REFERENCE_PRESERVED=true' \
  'KEEP14_UNTOUCHED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

BASE_PATH='tools/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py'
if ! git -C "$ROOT" cat-file -e "$SHA:$BASE_PATH" 2>/dev/null; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["BASE_EXECUTION_SOURCE_MISSING"]'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-defect3b-parent-bind-fix.XXXXXX)" || exit 2
EXEC="$TMP/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py"

git -C "$ROOT" show "$SHA:$BASE_PATH" > "$EXEC" || exit 2

python3 - "$EXEC" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''    parent_rows = [row for row in trades if str(row.get("lane_id") or "") == LANE_ID]
    cells = {cell_key(row) for row in parent_rows}
'''
new = '''    lane_best_rows = [
        row for row in (second_summary.get("lane_best_rows") or [])
        if isinstance(row, dict)
        and str(row.get("lane_id") or row.get("source_lane_id") or "") == LANE_ID
    ]
    if len(lane_best_rows) != 1:
        blockers.append(f"EXPECTED_ONE_MA5_LANE_BEST_ROW:{len(lane_best_rows)}")
    parent_variant_id = ""
    if lane_best_rows:
        parent_variant_id = str(
            lane_best_rows[0].get("variant_id")
            or lane_best_rows[0].get("control_variant_id")
            or ""
        )
    if not parent_variant_id:
        blockers.append("MA5_PARENT_VARIANT_UNRESOLVED")

    parent_rows = []
    for row in trades:
        row_lane = str(row.get("lane_id") or row.get("source_lane_id") or "")
        row_variant = str(row.get("control_variant_id") or row.get("variant_id") or "")
        if row_lane != LANE_ID or row_variant != parent_variant_id:
            continue
        parent_rows.append({
            **row,
            "lane_id": LANE_ID,
            "control_variant_id": parent_variant_id,
        })
    cells = {cell_key(row) for row in parent_rows}
'''
if text.count(old) != 1:
    raise SystemExit(f"PARENT_BIND_PATCH_ANCHOR_COUNT_INVALID:{text.count(old)}")
text = text.replace(old, new, 1)
old_summary = '        "parent_variant_id": "ma5_accel_15m_alignment",\n'
new_summary = '        "parent_variant_id": parent_variant_id,\n'
if text.count(old_summary) != 1:
    raise SystemExit(f"PARENT_VARIANT_SUMMARY_ANCHOR_COUNT_INVALID:{text.count(old_summary)}")
text = text.replace(old_summary, new_summary, 1)
path.write_text(text, encoding="utf-8")
print("STATE=PASS_MA5_PARENT_BIND_TEMPORARY_EXECUTION_PATCH")
print("PATCH_SCOPE=temporary_execution_copy_only")
PY
PATCH_RC=$?
if [[ $PATCH_RC -ne 0 ]]; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TEMPORARY_PARENT_BIND_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$EXEC"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$EXEC" --self-test; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
summary_path = root / "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json"
trades_path = root / "runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
lane = "dual_ma_trend_bot:5m"
best = [
    row for row in (summary.get("lane_best_rows") or [])
    if isinstance(row, dict)
    and str(row.get("lane_id") or row.get("source_lane_id") or "") == lane
]
variant = ""
if len(best) == 1:
    variant = str(best[0].get("variant_id") or best[0].get("control_variant_id") or "")
rows = []
for raw in trades_path.read_text(encoding="utf-8").splitlines():
    if not raw.strip():
        continue
    row = json.loads(raw)
    row_lane = str(row.get("lane_id") or row.get("source_lane_id") or "")
    row_variant = str(row.get("control_variant_id") or row.get("variant_id") or "")
    if row_lane == lane and row_variant == variant:
        rows.append(row)
cells = {
    (
        str(row.get("cost_profile_id") or row.get("profile") or ""),
        str(row.get("timing_id") or "timing_0"),
    )
    for row in rows
}
print(f"MA5_LANE_BEST_ROW_COUNT={len(best)}")
print(f"MA5_PARENT_VARIANT_ID={variant}")
print(f"MA5_PARENT_TRADE_PRECHECK_COUNT={len(rows)}")
print(f"MA5_PARENT_STRESS_CELL_PRECHECK_COUNT={len(cells)}")
if len(best) != 1 or not variant or not rows or len(cells) != 6:
    raise SystemExit(2)
PY
PRECHECK_RC=$?
if [[ $PRECHECK_RC -ne 0 ]]; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MA5_PARENT_LINEAGE_PRECHECK_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$EXEC" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_PARENT_BIND_FIX_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
