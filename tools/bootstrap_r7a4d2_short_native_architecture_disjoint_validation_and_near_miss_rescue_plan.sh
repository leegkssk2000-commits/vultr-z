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
  'R7A4D2_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_START' \
  'MODE=READ_ONLY_STRICT_SURVIVOR_HELD_OUT_VALIDATION_PLUS_ALL_LOSER_BUNDLE_RESCUE_AUDIT' \
  'EXPECTED_STRATEGY_COUNT=11' \
  'EXPECTED_ARCHITECTURE_BUNDLE_COUNT=22' \
  'EXPECTED_DISCOVERY_CELL_COUNT=132' \
  'EXPECTED_VALIDATION_SEGMENT_COUNT=12' \
  'EXPECTED_STRESS_CELL_PER_VALIDATED_BUNDLE=6' \
  'MAX_RESCUE_STRATEGY_COUNT=6' \
  'SECOND_GENERATION_VARIANT_PER_RESCUE_STRATEGY=2' \
  'STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_native_family_architecture_discovery_execution_132/architecture_discovery_lock_v1.json" \
  "$ROOT/runtime/r7a4d2_short_native_family_architecture_discovery_execution_132/architecture_cell_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_native_family_architecture_discovery_execution_132/architecture_trade_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan/rebuild_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-disjoint-rescue.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan.py \
  tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan.py" \
  "$TMP/tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
then
  echo 'STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan.py" --self-test; then
  echo 'STATE=HOLD_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISJOINT_VALIDATION_RESCUE_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --engine-module "$TMP/tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --helper-module "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
