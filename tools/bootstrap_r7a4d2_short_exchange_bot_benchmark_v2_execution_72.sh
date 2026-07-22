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
  'R7A4D2_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_START' \
  'MODE=READ_ONLY_SIX_EXCHANGE_STYLE_BOTS_DUAL_DIRECTION_AND_REAL_GRID_SEVENTY_TWO_CELL_EXECUTION' \
  'EXPECTED_EXCHANGE_BOT_V2_COUNT=6' \
  'EXPECTED_EXCHANGE_BOT_V2_LANE_COUNT=12' \
  'EXPECTED_SELECTED_SEGMENT_COUNT=24' \
  'EXPECTED_STRESS_CELL_PER_LANE=6' \
  'EXPECTED_EXCHANGE_BOT_V2_CELL_COUNT=72' \
  'BASE_AND_ADVERSE_POSITIVE_ECONOMICS_REQUIRED=true' \
  'MINIMUM_LANE_TRADES=24' \
  'MINIMUM_SYMBOL_COUNT=3' \
  'MINIMUM_POSITIVE_WALK_FORWARD_FOLDS=4' \
  'MINIMUM_POSITIVE_PRIMARY_CELLS=3' \
  'SEVERE_PROFILE_PRIMARY_SELECTION_ALLOWED=false' \
  'MIN_TARGET_TO_BASE_COST_RATIO=3.0' \
  'MIN_RISK_TO_BASE_COST_RATIO=2.0' \
  'BAR_LATENCY_AS_EXCHANGE_LATENCY_ALLOWED=false' \
  'NEXT_BAR_SIGNAL_TO_FILL_DISCRETIZATION_REQUIRED=true' \
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
  echo 'STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-exchange-bot-v2.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
CONTRACT="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$TARGET" "$RAW" "$HELPER"; then
  echo 'STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXCHANGE_BOT_V2_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
