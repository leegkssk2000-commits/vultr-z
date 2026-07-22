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
  'R7A4D2_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_START' \
  'MODE=READ_ONLY_ELEVEN_NATIVE_STRATEGY_COMPLETE_ARCHITECTURE_BUNDLE_REBUILD_PLAN' \
  'EXPECTED_STRATEGY_COUNT=11' \
  'EXPECTED_ARCHITECTURE_BUNDLE_COUNT=22' \
  'STRESS_CELL_PER_BUNDLE=6' \
  'EXPECTED_DISCOVERY_CELL_TARGET=132' \
  'GENERIC_SINGLE_AXIS_ARM_REUSE_ALLOWED=false' \
  'CROSS_STRATEGY_SIGNAL_CONTRACT_ALIAS_ALLOWED=false' \
  'STANDALONE_1M_PROMOTION_ALLOWED=false' \
  'RETIREMENT_BEFORE_BUNDLE_EXECUTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit/economic_execution_and_uplift_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_second_order_repair_causal_audit/causal_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_effective_execution_plan_v3.json" \
  "$ROOT/runtime/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild/repair_plan_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-native-family-rebuild.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan.py" > "$TMP/tools/plan.py"; then
  echo 'STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:plan.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/plan.py"; then
  echo 'STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/plan.py" --self-test; then
  echo 'STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["NATIVE_FAMILY_REBUILD_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/plan.py" --root "$ROOT" --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
