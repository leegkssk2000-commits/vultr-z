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
  'R7A3E5_START' \
  'MODE=READ_ONLY_CANONICAL_CROSS_LAYER_REAUDIT' \
  'EVIDENCE_MUTATION_ALLOWED=true' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ADAPTER_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SIMULATION_REPLAY_EXECUTION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A3E5_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a3e5.XXXXXX)" || exit 2
for path in \
  backend/contracts/ZOS_R7A3E5_STRATEGY25_CANONICAL_REAUDIT_v1.json \
  tools/r7a3e5_strategy25_canonical_reaudit.py \
  tests/test_r7a3e5_strategy25_canonical_reaudit.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A3E5_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a3e5_strategy25_canonical_reaudit.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A3E5_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP" python3 -m pytest -q "$TMP/tests/test_r7a3e5_strategy25_canonical_reaudit.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A3E5_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a3e5_strategy25_canonical_reaudit.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A3E5_STRATEGY25_CANONICAL_REAUDIT_v1.json"
RC=$?

echo 'R7A3E5_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
