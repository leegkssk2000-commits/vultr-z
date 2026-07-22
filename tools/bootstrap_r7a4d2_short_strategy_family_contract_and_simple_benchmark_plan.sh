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
  'R7A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_START' \
  'MODE=READ_ONLY_FIVE_ROOT_CAUSE_ARCHITECTURE_REDESIGN' \
  'REDESIGN_TARGET_SELECTION=true' \
  'REDESIGN_UNIVERSAL_RR=true' \
  'REDESIGN_NATIVE_TIMEFRAME=true' \
  'REDESIGN_SIMPLE_BENCHMARK=true' \
  'REDESIGN_FIXED_CANDIDATE_QUOTA=true' \
  'RESIDUAL_ISSUE_BACKLOG_REQUIRED=true' \
  'NEW_STRATEGY_EXECUTION_ALLOWED=false' \
  'NEW_MARKET_REPLAY_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

REQUIRED="$ROOT/runtime/r7a4d2_short_architecture_economic_alignment_audit/alignment_audit_v1.json"
if [[ ! -f "$REQUIRED" ]]; then
  echo 'STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$REQUIRED"
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-family-benchmark-plan.XXXXXX)" || exit 2
PATH_IN_REPO="tools/r7a4d2_short_strategy_family_contract_and_simple_benchmark_plan.py"
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:$PATH_IN_REPO" > "$TMP/$PATH_IN_REPO"; then
  echo 'STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/$PATH_IN_REPO"; then
  echo 'STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/$PATH_IN_REPO" --self-test; then
  echo 'STATE=HOLD_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/$PATH_IN_REPO" --root "$ROOT"
RC=$?

echo 'R7A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
