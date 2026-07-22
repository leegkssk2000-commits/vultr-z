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
  'R7A4D2_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_START' \
  'MODE=READ_ONLY_EXECUTION_ECONOMICS_UNIT_REPAIR_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN' \
  'EXPECTED_OLD_BENCHMARK_LANE_COUNT=10' \
  'EXPECTED_OLD_BENCHMARK_CELL_COUNT=60' \
  'EXPECTED_SELECTED_SEGMENT_COUNT=24' \
  'EXPECTED_EXCHANGE_BOT_V2_COUNT=6' \
  'EXPECTED_EXCHANGE_BOT_V2_LANE_COUNT=12' \
  'EXPECTED_EXCHANGE_BOT_V2_CELL_TARGET=72' \
  'BAR_LATENCY_AS_EXCHANGE_LATENCY_ALLOWED=false' \
  'NEXT_BAR_SIGNAL_TO_FILL_DISCRETIZATION_REQUIRED=true' \
  'BASE_AND_ADVERSE_POSITIVE_ECONOMICS_REQUIRED=true' \
  'SEVERE_PROFILE_PRIMARY_SELECTION_ALLOWED=false' \
  'MIN_TARGET_TO_BASE_COST_RATIO=3.0' \
  'MIN_RISK_TO_BASE_COST_RATIO=2.0' \
  'SHORT_ONLY_MIXED_REGIME_BENCHMARK_ALLOWED=false' \
  'SINGLE_CYCLE_SHORT_AS_GRID_ALLOWED=false' \
  'NEGATIVE_BENCHMARK_RELATIVE_PROMOTION_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_baseline_and_data_coverage_v1.json" \
  "$ROOT/runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_trade_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_cell_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_macro_alpha_reset_plan/macro_alpha_reset_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-economic-calibration.XXXXXX)" || exit 2
mkdir -p "$TMP/tools" "$TMP/backend/contracts"

for path in \
  tools/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan.py"
CONTRACT="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ECONOMIC_CALIBRATION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
