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
  'R7A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_START' \
  'MODE=READ_ONLY_VWAP_THREE_LANE_REPLACEMENT_AND_IMMUTABLE_EVIDENCE_MERGE' \
  'REBASELINE_STRATEGY_COUNT=1' \
  'AFFECTED_STRATEGY_LANE_COUNT=3' \
  'FROZEN_SEGMENT_COUNT=24' \
  'REPLACEMENT_SCAN_TARGET=72' \
  'PRESERVED_SCAN_COUNT=792' \
  'MERGED_SCAN_TARGET=864' \
  'PRESERVED_STRATEGY_LANE_COUNT=22' \
  'PRESERVED_BENCHMARK_LANE_COUNT=11' \
  'SOURCE_BINDING_MODE=IMMUTABLE_RUNTIME_SNAPSHOT' \
  'OLD_RAW_EVIDENCE_MUTATION_ALLOWED=false' \
  'FULL_864_REEXECUTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan/rebaseline_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan/snapshot_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/aggregate_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/proof_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy25_config_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-selective-vwap-raw.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_selective_raw_geometry_rebaseline_execution.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py \
  tools/r7a4d_historical_simulation_3600.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_selective_raw_geometry_rebaseline_execution.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py" \
  "$TMP/tools/r7a4d_historical_simulation_3600.py"
then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_selective_raw_geometry_rebaseline_execution.py" --self-test; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SELECTIVE_RAW_REBASELINE_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_selective_raw_geometry_rebaseline_execution.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --diagnose-module "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_REBASELINE_EXECUTION_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
