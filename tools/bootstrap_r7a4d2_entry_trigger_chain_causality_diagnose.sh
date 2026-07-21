#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=2
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_START' \
  'MODE=READ_ONLY_PRESEGMENT_BOUNDARY_PREDICATE_AND_REACHABILITY_DIAGNOSE' \
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
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2_entry_chain.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_entry_trigger_chain_causality_diagnose.py \
  tools/r7a4d_historical_simulation_3600.py \
  tests/test_r7a4d2_entry_trigger_chain_causality_diagnose.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_entry_trigger_chain_causality_diagnose.py" \
  "$TMP/tools/r7a4d_historical_simulation_3600.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_entry_trigger_chain_causality_diagnose.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_COMPLETE'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 \
  "$TMP/tools/r7a4d2_entry_trigger_chain_causality_diagnose.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_ENTRY_TRIGGER_CHAIN_CAUSALITY_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
