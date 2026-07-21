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
  'R7A4D2_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN_START' \
  'MODE=READ_ONLY_EXACT_MUTATION_PLAN' \
  'HISTORICAL_SIMULATION_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_PLAN_INPUT_INVALID'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-plan.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_strategy_specific_entry_chain_plan.py \
  tests/test_r7a4d2_strategy_specific_entry_chain_plan.py
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_PLAN_INPUT_INVALID'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_strategy_specific_entry_chain_plan.py"; then
  echo 'STATE=HOLD_PLAN_INPUT_INVALID'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q "$TMP/tests/test_r7a4d2_strategy_specific_entry_chain_plan.py"; then
  echo 'STATE=HOLD_PLAN_INPUT_INVALID'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_strategy_specific_entry_chain_plan.py" --root "$ROOT"
RC=$?
echo 'R7A4D2_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
