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
TMP="$(mktemp -d /tmp/r7a3d2.XXXXXXXX)"
for p in tools/r7a3d2_strategy25_canonical_mapping_closure_plan.py tests/test_r7a3d2_strategy25_canonical_mapping_closure_plan.py backend/contracts/ZOS_R7A3D2_STRATEGY25_CANONICAL_MAPPING_CLOSURE_PLAN_v1.json; do show_file "$p" "$TMP/$p" || RC=2; done
if [[ "$RC" -eq 0 ]]; then python3 -m py_compile "$TMP/tools/r7a3d2_strategy25_canonical_mapping_closure_plan.py" || RC=2; fi
if [[ "$RC" -eq 0 ]]; then python3 -m pytest -q "$TMP/tests/test_r7a3d2_strategy25_canonical_mapping_closure_plan.py" || RC=2; fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3D2_START
  echo MODE=READ_ONLY_CONFLICT_DEDUP_AND_CANONICAL_MAPPING_PLAN
  echo CANONICAL_MAPPING_MUTATION_ALLOWED=false
  echo STRATEGY_LOGIC_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  python3 "$TMP/tools/r7a3d2_strategy25_canonical_mapping_closure_plan.py" --root "$ROOT" --contract "$TMP/backend/contracts/ZOS_R7A3D2_STRATEGY25_CANONICAL_MAPPING_CLOSURE_PLAN_v1.json" || RC=$?
fi
echo R7A3D2_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
