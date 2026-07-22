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
  'R7A4D2_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_START' \
  'MODE=READ_ONLY_450_CELL_GATE_AND_CAUSAL_DECOMPOSITION' \
  'EXPECTED_STRATEGY_LANE_COUNT=25' \
  'EXPECTED_CANDIDATE_ARM_COUNT=75' \
  'EXPECTED_STRESS_CELL_COUNT=450' \
  'MINIMUM_DISCOVERY_TRADE_COUNT=8' \
  'MINIMUM_POSITIVE_STRESS_CELL_COUNT=4' \
  'ARBITRARY_SCORE_ALLOWED=false' \
  'REPAIR_EXECUTION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_lock_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_trade_results_v1.jsonl"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-second-order-causal-audit.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_second_order_repair_causal_audit.py" \
  > "$TMP/tools/r7a4d2_short_second_order_repair_causal_audit.py"; then
  echo 'STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_second_order_repair_causal_audit.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_second_order_repair_causal_audit.py"; then
  echo 'STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_second_order_repair_causal_audit.py" --self-test; then
  echo 'STATE=HOLD_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SECOND_ORDER_CAUSAL_AUDIT_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_second_order_repair_causal_audit.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_SECOND_ORDER_REPAIR_CAUSAL_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
