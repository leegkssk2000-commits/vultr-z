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
  'R7A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_START' \
  'MODE=READ_ONLY_ORDER_INDEPENDENT_MULTISET_PRESERVATION_VERIFICATION' \
  'PRIOR_EVIDENCE_REEXECUTION_ALLOWED=false' \
  'EXPECTED_PRIOR_BLOCKER=PRESERVED_GEOMETRY_CONTENT_CHANGED' \
  'EXPECTED_REPLACEMENT_SCAN_COUNT=72' \
  'EXPECTED_PRESERVED_SCAN_COUNT=792' \
  'EXPECTED_MERGED_SCAN_COUNT=864' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/replacement_scan_results_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/replacement_signal_geometry_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_scan_results_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_signal_geometry_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_aggregate_v2.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/proof_v2.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/effective_execution_plan_v2.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-preservation-verify.XXXXXX)" || exit 2
SCRIPT="$TMP/r7a4d2_short_selective_raw_geometry_preservation_verification_repair.py"

if ! git -C "$ROOT" show \
  "$SHA:tools/r7a4d2_short_selective_raw_geometry_preservation_verification_repair.py" \
  > "$SCRIPT"
then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:verification_repair"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$SCRIPT"; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$SCRIPT" --self-test; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VERIFICATION_REPAIR_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$SCRIPT" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_SELECTIVE_RAW_GEOMETRY_PRESERVATION_VERIFICATION_REPAIR_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
