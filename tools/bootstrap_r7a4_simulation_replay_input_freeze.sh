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

printf '%s\n' \
  'R7A4_START' \
  'MODE=READ_ONLY_REPRODUCIBLE_INPUT_SET_FREEZE' \
  'EVIDENCE_MUTATION_ALLOWED=true' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SIMULATION_REPLAY_EXECUTION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4.XXXXXX)" || exit 2
for path in \
  backend/contracts/ZOS_R7A4_SIMULATION_REPLAY_INPUT_FREEZE_v1.json \
  tools/r7a4_simulation_replay_input_freeze.py \
  tests/test_r7a4_simulation_replay_input_freeze.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A4_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4_simulation_replay_input_freeze.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP" python3 -m pytest -q "$TMP/tests/test_r7a4_simulation_replay_input_freeze.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4_simulation_replay_input_freeze.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A4_SIMULATION_REPLAY_INPUT_FREEZE_v1.json"
RC=$?

echo 'R7A4_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
