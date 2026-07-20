#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=0
TMP=""
cleanup(){ [[ -n "$TMP" ]] && rm -rf "$TMP"; }
trap cleanup EXIT

[[ -n "$SHA" ]] || { echo 'BLOCKERS=["MISSING_SHA"]'; exit 2; }
git -C "$ROOT" -c safe.directory="$ROOT" cat-file -e "$SHA^{commit}" || exit 2
TMP="$(mktemp -d /tmp/r7a3e3.XXXXXXXX)"
mkdir -p "$TMP/tools" "$TMP/backend/contracts" "$TMP/tests"

for path in \
  tools/r7a3e3_strategy25_contract_tests_after_restore25.py \
  backend/contracts/ZOS_R7A3E3_STRATEGY25_CONTRACT_TESTS_AFTER_RESTORE25_v1.json \
  tests/test_r7a3e3_strategy25_contract_tests.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$path" > "$TMP/$path" || RC=2
done

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" || RC=2
  python3 -m pytest -q "$TMP/tests/test_r7a3e3_strategy25_contract_tests.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  grep -q 'PASS_LIVE_CANONICAL' "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" || RC=2
  grep -q 'target_git_source_parity_count' "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" || RC=2
  grep -q 'receipt_contract_count' "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" || RC=2
  grep -q 'replay_contract_count' "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" || RC=2
fi

if [[ "$RC" -eq 0 ]]; then
  echo R7A3E3_START
  echo MODE=READ_ONLY_SEMANTIC_AND_GIT_PERSISTENCE_CONTRACT_TESTS
  echo STRATEGY_SOURCE_MUTATION_ALLOWED=false
  echo REGISTRY_MUTATION_ALLOWED=false
  echo ROUTER_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  python3 "$TMP/tools/r7a3e3_strategy25_contract_tests_after_restore25.py" \
    --root "$ROOT" \
    --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7A3E3_STRATEGY25_CONTRACT_TESTS_AFTER_RESTORE25_v1.json" || RC=$?
fi

echo R7A3E3_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
