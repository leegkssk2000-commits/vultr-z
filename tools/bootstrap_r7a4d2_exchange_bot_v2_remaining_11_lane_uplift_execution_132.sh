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
  'R7A4D2_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_START' \
  'MODE=READ_ONLY_TWENTY_TWO_CAUSAL_REPAIR_BUNDLES_SIX_STRESS_CELL_EXECUTION' \
  'EXPECTED_FAILED_LANE_COUNT=11' \
  'EXPECTED_REPAIR_BUNDLE_COUNT=22' \
  'EXPECTED_STRESS_CELL_PER_BUNDLE=6' \
  'EXPECTED_UPLIFT_CELL_COUNT=132' \
  'REFERENCE_PASS_LANE_ID=dual_donchian_trend_bot:15m' \
  'BASE_AND_ADVERSE_POSITIVE_REQUIRED=true' \
  'MINIMUM_TRADES=24' \
  'MINIMUM_SYMBOL_COUNT=3' \
  'MINIMUM_POSITIVE_WALK_FORWARD_FOLDS=4' \
  'MINIMUM_POSITIVE_PRIMARY_CELLS=3' \
  'MUST_BEAT_OWN_BASELINE_RISK_SCORE=true' \
  'REFERENCE_BEAT_REPORTED_SEPARATELY=true' \
  'SEVERE_PROFILE_PRIMARY_SELECTION_ALLOWED=false' \
  'DISCOVERY_S_GRADE_LABEL_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'BLIND_STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_plan/remaining_11_lane_uplift_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-remaining-11-uplift.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
CONTRACT="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$TARGET" "$BENCHMARK" "$RAW" "$HELPER"; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["UPLIFT_EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --benchmark-module "$BENCHMARK" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
