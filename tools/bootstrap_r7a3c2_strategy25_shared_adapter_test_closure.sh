#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=0
TMP=""
cleanup(){ [[ -n "$TMP" ]] && rm -rf "$TMP"; }
trap cleanup EXIT
show_file(){ local src="$1" dst="$2"; mkdir -p "$(dirname "$dst")"; git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$src" > "$dst"; }

[[ -n "$SHA" ]] || { echo 'BLOCKERS=["MISSING_SHA"]'; exit 2; }
TMP="$(mktemp -d /tmp/r7a3c2.XXXXXXXX)"
for path in \
  backend/strategy25/shared_strategy_adapter.py \
  tests/test_strategy25_shared_strategy_adapter.py \
  tools/r7a3c2_strategy25_shared_adapter_test_closure.py \
  backend/contracts/ZOS_R7A3C2_STRATEGY25_SHARED_ADAPTER_TEST_CLOSURE_v1.json
 do
  show_file "$path" "$TMP/$path" || RC=2
done

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/backend/strategy25/shared_strategy_adapter.py" "$TMP/tools/r7a3c2_strategy25_shared_adapter_test_closure.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  mkdir -p "$ROOT/backend/strategy25" "$ROOT/tests"
  install -m 0644 "$TMP/backend/strategy25/shared_strategy_adapter.py" "$ROOT/backend/strategy25/shared_strategy_adapter.py"
  install -m 0644 "$TMP/tests/test_strategy25_shared_strategy_adapter.py" "$ROOT/tests/test_strategy25_shared_strategy_adapter.py"
  echo R7A3C2_START
  echo STRATEGY_LOGIC_MUTATION_ALLOWED=false
  echo PARAMETER_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  PYTHONPATH="$ROOT/backend/strategy25" python3 "$TMP/tools/r7a3c2_strategy25_shared_adapter_test_closure.py" \
    --root "$ROOT" --contract "$TMP/backend/contracts/ZOS_R7A3C2_STRATEGY25_SHARED_ADAPTER_TEST_CLOSURE_v1.json" || RC=$?
fi
echo R7A3C2_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
