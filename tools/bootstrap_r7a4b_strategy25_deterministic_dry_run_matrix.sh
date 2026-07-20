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
  'R7A4B_START' \
  'MODE=FAIL_CLOSED_DETERMINISTIC_CANONICAL_CALLABLE_DRY_RUN' \
  'DRY_RUN_EXECUTION_ALLOWED=true' \
  'HISTORICAL_MARKET_DATA_ALLOWED=false' \
  'EXECUTION_COST_APPLICATION_ALLOWED=false' \
  'HISTORICAL_REPLAY_ALLOWED=false' \
  'CANONICAL_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A4B_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4b.XXXXXX)" || exit 2
for path in \
  backend/contracts/ZOS_R7A4B_STRATEGY25_DETERMINISTIC_DRY_RUN_MATRIX_v1.json \
  tools/r7a4b_strategy25_deterministic_dry_run_matrix.py \
  tests/test_r7a4b_strategy25_deterministic_dry_run_matrix.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A4B_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4b_strategy25_deterministic_dry_run_matrix.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A4B_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q "$TMP/tests/test_r7a4b_strategy25_deterministic_dry_run_matrix.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A4B_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4b_strategy25_deterministic_dry_run_matrix.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A4B_STRATEGY25_DETERMINISTIC_DRY_RUN_MATRIX_v1.json"
RC=$?

echo 'R7A4B_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
