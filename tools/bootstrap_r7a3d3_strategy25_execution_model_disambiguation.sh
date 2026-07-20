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
git -C "$ROOT" -c safe.directory="$ROOT" cat-file -e "$SHA^{commit}" || exit 2
TMP="$(mktemp -d /tmp/r7a3d3.XXXXXXXX)"
for path in \
  tools/r7a3d3_strategy25_execution_model_disambiguation.py \
  tests/test_r7a3d3_strategy25_execution_model_disambiguation.py \
  backend/contracts/ZOS_R7A3D3_STRATEGY25_EXECUTION_MODEL_DISAMBIGUATION_v1.json
 do
  show_file "$path" "$TMP/$path" || RC=2
done

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/tools/r7a3d3_strategy25_execution_model_disambiguation.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  python3 -m pytest -q "$TMP/tests/test_r7a3d3_strategy25_execution_model_disambiguation.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3D3_START
  echo MODE=READ_ONLY_EXECUTION_MODEL_AND_RUNTIME_AUTHORITY_DISAMBIGUATION
  echo CANONICAL_MAPPING_MUTATION_ALLOWED=false
  echo STRATEGY_LOGIC_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  python3 "$TMP/tools/r7a3d3_strategy25_execution_model_disambiguation.py" \
    --root "$ROOT" \
    --contract "$TMP/backend/contracts/ZOS_R7A3D3_STRATEGY25_EXECUTION_MODEL_DISAMBIGUATION_v1.json" || RC=$?
fi

echo R7A3D3_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
