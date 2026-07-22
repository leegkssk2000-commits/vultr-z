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
  'R7A4D2_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_START' \
  'MODE=READ_ONLY_EXISTING_864_EVIDENCE_MUTATION_CLASSIFICATION_AND_PARETO_LANE_COMPARISON' \
  'RAW_GEOMETRY_REEXECUTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'ARBITRARY_PROMOTION_SCORE_ALLOWED=false' \
  'PARETO_COMPARISON_REQUIRED=true'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/aggregate_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-raw-geometry-lane-diagnose.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py" \
  > "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py" --self-test; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_RAW_GEOMETRY_MUTATION_AND_LANE_ECONOMIC_DIAGNOSE_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
