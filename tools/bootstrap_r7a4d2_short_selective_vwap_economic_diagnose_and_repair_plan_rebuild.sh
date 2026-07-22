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
  'R7A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_START' \
  'MODE=READ_ONLY_NATIVE_VWAP_THREE_TIMEFRAME_ECONOMIC_DIAGNOSE_AND_STRATEGY_SPECIFIC_REPAIR_PLAN' \
  'EXPECTED_VWAP_LANE_COUNT=3' \
  'EXPECTED_REPAIR_ARM_COUNT=9' \
  'EXPECTED_STRESS_CELL_COUNT=54' \
  'ENTRY_AXIS_ARM_COUNT=3' \
  'REGIME_AXIS_ARM_COUNT=3' \
  'EXIT_AXIS_ARM_COUNT=3' \
  'NATIVE_SIGNAL_ONLY=true' \
  'SINGLE_AXIS_ARM_ONLY=true' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_aggregate_v3.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_effective_execution_plan_v3.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/proof_v3.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_signal_geometry_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_scan_results_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_canonical_source_snapshot_and_rebaseline_plan/snapshot_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-vwap-economic-plan.XXXXXX)" || exit 2
SCRIPT="$TMP/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild.py"

if ! git -C "$ROOT" show \
  "$SHA:tools/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild.py" \
  > "$SCRIPT"
then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:vwap_economic_plan"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$SCRIPT"; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$SCRIPT" --self-test; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VWAP_ECONOMIC_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$SCRIPT" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_SELECTIVE_VWAP_ECONOMIC_DIAGNOSE_AND_REPAIR_PLAN_REBUILD_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
