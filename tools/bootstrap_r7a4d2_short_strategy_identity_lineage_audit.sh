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
  'R7A4D2_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_START' \
  'MODE=READ_ONLY_NATIVE_CALLABLE_SIGNAL_TIMEFRAME_AND_ALIAS_AUDIT' \
  'EXPECTED_STRATEGY_COUNT=11' \
  'EXPECTED_STRATEGY_LANE_COUNT=25' \
  'EXPECTED_CANDIDATE_ARM_COUNT=75' \
  'EXPECTED_STRESS_CELL_COUNT=450' \
  'CANONICAL_BINDING_ALIAS_CHECK=true' \
  'NATIVE_SIGNAL_FINGERPRINT_CHECK=true' \
  'REPAIR_OUTCOME_ALIAS_CHECK=true' \
  'BENCHMARK_RECONSTRUCTION_DISCLOSURE_REQUIRED=true' \
  'SIBLING_EXECUTION_DISCLOSURE_REQUIRED=true' \
  'PERFORMANCE_TUNING_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_plan/repair_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_lock_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_trade_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/aggregate_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-strategy-identity-lineage-audit.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_strategy_identity_lineage_audit.py" \
  > "$TMP/tools/r7a4d2_short_strategy_identity_lineage_audit.py"; then
  echo 'STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_strategy_identity_lineage_audit.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_strategy_identity_lineage_audit.py"; then
  echo 'STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_strategy_identity_lineage_audit.py" --self-test; then
  echo 'STATE=HOLD_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["STRATEGY_IDENTITY_LINEAGE_AUDIT_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_strategy_identity_lineage_audit.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_STRATEGY_IDENTITY_LINEAGE_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
