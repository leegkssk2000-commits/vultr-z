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
  'R7A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_START' \
  'MODE=READ_ONLY_ALL_25_LANE_CANDLE_GEOMETRY_DISCOVERY_REPAIR_EXECUTION' \
  'EXPECTED_STRATEGY_LANE_COUNT=25' \
  'EXPECTED_CANDIDATE_ARM_COUNT=75' \
  'DISCOVERY_SEGMENT_COUNT=12' \
  'COST_PROFILE_COUNT=3' \
  'PERTURBATION_COUNT=2' \
  'EXPECTED_REPAIR_ARM_CELL_COUNT=450' \
  'ONE_LOCK_PER_UNIQUE_STRATEGY=true' \
  'SEVERE_CELL_ECONOMIC_PASS_REQUIRED=true' \
  'MINIMUM_POSITIVE_STRESS_CELL_COUNT=4' \
  'MINIMUM_DISCOVERY_TRADE_COUNT=8' \
  'STOP_FIRST_COLLISION_REQUIRED=true' \
  'OVERLAPPING_POSITION_ALLOWED=false' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'UNIVERSAL_RR_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_plan/repair_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/aggregate_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-all-lane-repair-execution.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_all_lane_architecture_repair_execution.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_execution.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_execution.py" --self-test; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ALL_LANE_REPAIR_EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_execution.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --helper-module "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_EXECUTION_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
