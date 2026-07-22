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
  'R7A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_START' \
  'MODE=READ_ONLY_FIVE_FIXED_SIMPLE_BENCHMARKS_TEN_LANES_SIX_STRESS_CELLS_AND_EXTERNAL_DATA_COVERAGE_AUDIT' \
  'EXPECTED_BENCHMARK_COUNT=5' \
  'EXPECTED_BENCHMARK_LANE_COUNT=10' \
  'EXPECTED_SELECTED_SEGMENT_COUNT=24' \
  'EXPECTED_STRESS_CELL_PER_LANE=6' \
  'EXPECTED_BENCHMARK_CELL_COUNT=60' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'SAME_FROZEN_DATA_AND_COSTS_REQUIRED=true' \
  'STOP_FIRST_COLLISION_REQUIRED=true' \
  'OVERLAPPING_POSITION_ALLOWED=false' \
  'FOLD_METRICS_REQUIRED=true' \
  'FUNDING_OI_BASIS_MICROSTRUCTURE_COVERAGE_AUDIT_REQUIRED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_macro_alpha_reset_plan/macro_alpha_reset_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-simple-benchmark.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
then
  echo 'STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py" --self-test; then
  echo 'STATE=HOLD_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SIMPLE_BENCHMARK_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --helper-module "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
