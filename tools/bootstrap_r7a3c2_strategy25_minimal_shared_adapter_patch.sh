#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=0
TMP=""
cleanup(){ [[ -n "$TMP" ]] && rm -rf "$TMP"; }
trap cleanup EXIT
show_file(){ local src="$1" dst="$2"; mkdir -p "$(dirname "$dst")"; git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$src" > "$dst"; }

if [[ -z "$SHA" ]]; then
  echo R7A3C2_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["MISSING_SHA"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  TMP="$(mktemp -d /tmp/r7a3c2.XXXXXXXX)"
  for path in backend/strategy25/canonical_shared_adapter.py tools/r7a3c2_strategy25_minimal_shared_adapter_patch.py tests/test_r7a3c2_strategy25_minimal_shared_adapter_patch.py backend/contracts/ZOS_R7A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_PATCH_v1.json; do
    if ! show_file "$path" "$TMP/$path"; then
      echo R7A3C2_BOOTSTRAP_FAILED
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi
if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/backend/strategy25/canonical_shared_adapter.py" "$TMP/tools/r7a3c2_strategy25_minimal_shared_adapter_patch.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  (cd "$TMP" && python3 -m pytest -q tests/test_r7a3c2_strategy25_minimal_shared_adapter_patch.py) || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3C2_START
  echo MODE=MINIMAL_SHARED_ADAPTER_AND_STATIC_ENTRYPOINT_BINDING
  echo STRATEGY_LOGIC_MUTATION_ALLOWED=false
  echo PARAMETER_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo RUNTIME_ACTIVATION_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  PYTHONPATH="$TMP/tools:$TMP/backend" python3 "$TMP/tools/r7a3c2_strategy25_minimal_shared_adapter_patch.py" --root "$ROOT" --target-sha "$SHA" --contract "$TMP/backend/contracts/ZOS_R7A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_PATCH_v1.json" || RC=$?
fi
echo R7A3C2_BOOTSTRAP_COMPLETE
echo RC="$RC"
