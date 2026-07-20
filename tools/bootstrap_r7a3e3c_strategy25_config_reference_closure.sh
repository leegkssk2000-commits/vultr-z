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
TMP="$(mktemp -d /tmp/r7a3e3c.XXXXXXXX)"
mkdir -p "$TMP/tools" "$TMP/backend/contracts" "$TMP/tests"

for path in \
  tools/r7a3e3c_strategy25_config_reference_closure.py \
  tools/bootstrap_r7a3e3c_strategy25_config_reference_closure.sh \
  backend/contracts/ZOS_R7A3E3C_CONFIG_REFERENCE_CLOSURE_v1.json \
  tests/test_r7a3e3c_strategy25_config_reference_closure.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$path" > "$TMP/$path" || RC=2
done

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" || RC=2
  python3 -m pytest -q "$TMP/tests/test_r7a3e3c_strategy25_config_reference_closure.py" || RC=2
fi

if [[ "$RC" -eq 0 ]]; then
  grep -q 'CONFIG_HISTORY_AMBIGUOUS' "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" || RC=2
  grep -q 'SOURCE_ENGINE_MUTATION_DETECTED' "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" || RC=2
  grep -q 'ARTIFACT_CONFIG_REF_RETAINED' "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" || RC=2
  grep -q 'rollback(created, overwritten)' "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" || RC=2
fi

if [[ "$RC" -eq 0 ]]; then
  echo R7A3E3C_START
  echo MODE=ATOMIC_CONFIG_REFERENCE_CLOSURE
  echo CONFIG_INPUT=WORKTREE_TARGET_SHA_THEN_UNIQUE_GIT_HISTORY
  echo CANONICAL_CONFIG_PATH=backend/strategy25/canonical_strategy25_config_v1.json
  echo REGISTRY_MUTATION_ALLOWED=true
  echo CANONICAL_CONFIG_MUTATION_ALLOWED=true
  echo STRATEGY_SOURCE_MUTATION_ALLOWED=false
  echo ROUTER_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  python3 "$TMP/tools/r7a3e3c_strategy25_config_reference_closure.py" \
    --root "$ROOT" \
    --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7A3E3C_CONFIG_REFERENCE_CLOSURE_v1.json" \
    --apply || RC=$?
fi

echo R7A3E3C_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
