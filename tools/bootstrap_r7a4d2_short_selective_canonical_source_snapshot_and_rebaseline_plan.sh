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
  'R7A4D2_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN_START' \
  'MODE=READ_ONLY_AFFECTED_LANE_ONLY_CANONICAL_SNAPSHOT_AND_REBASELINE_PLAN' \
  'EXPECTED_REBASELINE_STRATEGY_COUNT=1' \
  'EXPECTED_AFFECTED_STRATEGY_LANE_COUNT=3' \
  'EXPECTED_PRESERVED_STRATEGY_LANE_COUNT=22' \
  'EXPECTED_PRESERVED_BENCHMARK_LANE_COUNT=11' \
  'SELECTIVE_RAW_GEOMETRY_SCAN_TARGET=72' \
  'PRESERVED_RAW_GEOMETRY_SCAN_COUNT=792' \
  'MERGED_RAW_GEOMETRY_SCAN_TARGET=864' \
  'SELECTIVE_REPAIR_ARM_TARGET=9' \
  'SELECTIVE_REPAIR_CELL_TARGET=54' \
  'PRESERVED_REPAIR_CELL_COUNT=396' \
  'MERGED_REPAIR_CELL_TARGET=450' \
  'FULL_864_REEXECUTION_ALLOWED=false' \
  'UNCHANGED_EVIDENCE_PRESERVATION_REQUIRED=true' \
  'AFFECTED_LANE_ONLY_REBASELINE_REQUIRED=true' \
  'CANONICAL_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_four_way_lineage_selective_rebaseline_audit/audit_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_trade_results_v1.jsonl"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

VWAP_PATH="$ROOT/backend/strategies/vwap_revert.py"
REGISTRY_PATH="$ROOT/backend/strategy25/canonical_strategy_registry_v1.json"
EXECUTION_PLAN_PATH="$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json"
if [[ ! -f "$VWAP_PATH" ]]; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VWAP_CANONICAL_SOURCE_MISSING"]'
  echo 'RC=2'
  exit 2
fi

VWAP_BEFORE="$(sha256sum "$VWAP_PATH" | cut -d' ' -f1)"
REGISTRY_BEFORE="$(sha256sum "$REGISTRY_PATH" | cut -d' ' -f1)"
PLAN_BEFORE="$(sha256sum "$EXECUTION_PLAN_PATH" | cut -d' ' -f1)"

TMP="$(mktemp -d /tmp/r7a4d2-short-selective-rebaseline-plan.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py" \
  > "$TMP/tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py"; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py"; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py" --self-test; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SELECTIVE_REBASELINE_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

VWAP_AFTER="$(sha256sum "$VWAP_PATH" | cut -d' ' -f1)"
REGISTRY_AFTER="$(sha256sum "$REGISTRY_PATH" | cut -d' ' -f1)"
PLAN_AFTER="$(sha256sum "$EXECUTION_PLAN_PATH" | cut -d' ' -f1)"
if [[ "$VWAP_BEFORE" != "$VWAP_AFTER" || "$REGISTRY_BEFORE" != "$REGISTRY_AFTER" || "$PLAN_BEFORE" != "$PLAN_AFTER" ]]; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_REBASELINE_PLAN_MUTATION_GUARD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PROTECTED_INPUT_MUTATION_DETECTED"]'
  echo 'RC=2'
  exit 2
fi

echo 'CANONICAL_SOURCE_MUTATION_GUARDED=true'
echo 'REGISTRY_MUTATION_GUARDED=true'
echo 'EXECUTION_PLAN_MUTATION_GUARDED=true'
echo 'R7A4D2_SHORT_SELECTIVE_CANONICAL_SOURCE_SNAPSHOT_AND_REBASELINE_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
