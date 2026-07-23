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
  'R7A4D2_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_START' \
  'MODE=READ_ONLY_ACTIVE_PARENT_PAYOFF_GEOMETRY_ALL_LOSS_AND_WINNER_CAPTURE_AUDIT' \
  'EXPECTED_ACTIVE_LANE_COUNT=3' \
  'EXPECTED_ACTIVE_LANES=dual_atr_volatility_bot:5m,dual_atr_volatility_bot:15m,dual_ma_trend_bot:5m' \
  'ATR5_ROBUST_PARENT_IMMUTABLE=true' \
  'ATR15_INCREMENTAL_PARENT_IMMUTABLE=true' \
  'MA5_SECOND_WAVE_CONTROL_IMMUTABLE=true' \
  'ALL_LOSS_MECHANISMS_REQUIRED=COST_EROSION,EXIT_CAPTURE_FAILURE,TIMEOUT_DRIFT,NO_FAVORABLE_EXCURSION,FAST_STOP_VOLATILITY,REENTRY_CHURN' \
  'WINNER_CAPTURE_COMPRESSION_REQUIRED=true' \
  'PAYOFF_METRICS_REQUIRED=EXPECTANCY_R,PROFIT_FACTOR,AVERAGE_WIN_R,AVERAGE_LOSS_R,PAYOFF_RATIO,MFE_CAPTURE,COST_SHARE,FOLD_DISTRIBUTION' \
  'DISCOVERY_VALIDATION_PERSISTENCE_REQUIRED=true' \
  'MAX_ACTIVE_REPAIR_LANES=3' \
  'ONE_STRUCTURAL_AXIS_PER_LANE=true' \
  'CHILD_ONLY_REPAIR=true' \
  'BASELINE_NON_DEGRADE_REQUIRED=true' \
  'SAME_FROZEN_DATA_AND_COSTS_REQUIRED=true' \
  'NO_STOP_WIDENING=true' \
  'NO_ENTRY_THRESHOLD_RELAXATION=true' \
  'NO_PARAMETER_OPTIMIZATION=true' \
  'CONFIDENCE_CLAIM_ALLOWED=false' \
  'INDEPENDENT_OOS_REQUIRED_BEFORE_CONFIDENCE=true' \
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
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_incremental_defect2_execution/incremental_defect2_cell_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect3_consecutive_loss_causality_audit/incremental_defect3_consecutive_loss_causality_audit_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-defect3b-payoff-audit.XXXXXX)" || exit 2
AUDIT="$TMP/r7a4d2_incremental_defect3b_payoff_geometry_all_loss_audit.py"
DEFECT3="$TMP/r7a4d2_incremental_defect3_consecutive_loss_causality_audit.py"
RAW="$TMP/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_incremental_defect3b_payoff_geometry_all_loss_audit.py" > "$AUDIT"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["AUDIT_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_incremental_defect3_consecutive_loss_causality_audit.py" > "$DEFECT3"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DEFECT3_HELPER_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" > "$RAW"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RAW_HELPER_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$AUDIT" "$DEFECT3" "$RAW"; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$AUDIT" --self-test; then
  echo 'STATE=HOLD_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["AUDIT_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$AUDIT" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --defect3-module "$DEFECT3" \
  --raw-module "$RAW"
RC=$?

echo 'R7A4D2_INCREMENTAL_DEFECT3B_PAYOFF_GEOMETRY_ALL_LOSS_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
