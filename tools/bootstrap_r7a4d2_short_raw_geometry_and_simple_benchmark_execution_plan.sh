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
  'R7A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_START' \
  'MODE=READ_ONLY_ECONOMIC_ALIGNMENT_EXECUTION_PLAN' \
  'STRATEGY_POOL_COUNT=12' \
  'ACTIVE_STRATEGY_COUNT=11' \
  'COMPOSITE_EXECUTION_ALLOWED_NOW=false' \
  'ACTIVE_FAMILY_COUNT=5' \
  'STRATEGY_TIMEFRAME_LANE_TARGET=25' \
  'BENCHMARK_TIMEFRAME_LANE_TARGET=11' \
  'TOTAL_EXECUTION_LANE_TARGET=36' \
  'DISCOVERY_VALIDATION_SPLIT=CHRONOLOGICAL_3_FOLDS_PLUS_3_FOLDS_PER_REGIME' \
  'UNIVERSAL_RR_ALLOWED=false' \
  'FIXED_CANDIDATE_QUOTA_ALLOWED=false' \
  'SAME_DATA_COST_TIMING_COLLISION_REQUIRED=true' \
  'STRATEGY_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

REQUIRED_RUNTIME=(
  "$ROOT/runtime/r7a4d2_short_strategy_family_contract_and_simple_benchmark_plan/plan_v1.json"
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/scenario_plan_3600_v1.json"
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json"
)
for required in "${REQUIRED_RUNTIME[@]}"; do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-raw-geometry-benchmark-plan.XXXXXX)" || exit 2
SCRIPT_PATH="tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan.py"
CONTRACT_PATH="backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
REGISTRY_PATH="backend/strategy25/canonical_strategy_registry_v1.json"

for path in "$SCRIPT_PATH" "$CONTRACT_PATH" "$REGISTRY_PATH"; do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/$SCRIPT_PATH"; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/$SCRIPT_PATH" --self-test; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/$SCRIPT_PATH" \
  --root "$ROOT" \
  --contract "$TMP/$CONTRACT_PATH" \
  --registry "$TMP/$REGISTRY_PATH"
RC=$?

echo 'R7A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
