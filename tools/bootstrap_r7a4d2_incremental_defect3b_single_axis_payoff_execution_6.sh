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
  'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_START' \
  'MODE=READ_ONLY_MA5_STATE_RESET_COOLDOWN_CHILD_ONLY_SIX_STRESS_AB' \
  'EXPECTED_LANE_ID=dual_ma_trend_bot:5m' \
  'EXPECTED_REPAIR_AXIS=STATE_RESET_COOLDOWN' \
  'EXPECTED_REPAIR_MECHANISM=REENTRY_CHURN' \
  'EXPECTED_STRESS_CELL_COUNT=6' \
  'PRIOR_LOSS_REQUIRED=true' \
  'PRIOR_STOP_REQUIRED=true' \
  'SAME_SYMBOL_SIDE_SIGNAL_REQUIRED=true' \
  'CURRENT_REGIME=shock_recovery' \
  'CURRENT_SIDE=short' \
  'CURRENT_SIGNAL_REASON=ma5_accel_15m_alignment' \
  'MAXIMUM_GAP_BARS=2' \
  'CURRENT_EXIT_REASON_ALLOWED=false' \
  'FUTURE_LEAKAGE_ALLOWED=false' \
  'PARENT_IMMUTABLE=true' \
  'CHILD_ONLY_REPAIR=true' \
  'BASELINE_NON_DEGRADE_REQUIRED=true' \
  'ADVERSE_NON_DEGRADE_REQUIRED=true' \
  'SEVERE_NON_DEGRADE_REQUIRED=true' \
  'MINIMUM_TRADES=24' \
  'MINIMUM_SYMBOLS=3' \
  'MINIMUM_POSITIVE_FOLDS=4' \
  'MEANINGFUL_SEVERE_MIN_PNL_PCT=0.50' \
  'MEANINGFUL_SEVERE_MIN_PROFIT_FACTOR=1.20' \
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
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT'
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
    echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-defect3b-single-axis-6.XXXXXX)" || exit 2
EXEC="$TMP/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py"

if ! git -C "$ROOT" show \
  "$SHA:tools/r7a4d2_incremental_defect3b_single_axis_payoff_execution_6.py" \
  > "$EXEC"
then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$EXEC"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$EXEC" --self-test; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$EXEC" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_INCREMENTAL_DEFECT3B_SINGLE_AXIS_PAYOFF_EXECUTION_6_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
