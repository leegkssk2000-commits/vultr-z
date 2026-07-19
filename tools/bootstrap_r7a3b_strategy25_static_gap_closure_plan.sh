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
  echo R7A3B_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["MISSING_SHA"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  TMP="$(mktemp -d /tmp/r7a3b.XXXXXXXX)"
  for path in \
    tools/r7a3b_strategy25_static_gap_closure_plan.py \
    tests/test_r7a3b_strategy25_static_gap_closure_plan.py \
    backend/contracts/ZOS_R7A3B_STRATEGY25_STATIC_GAP_CLOSURE_PLAN_v1.json
  do
    if ! show_file "$path" "$TMP/$path"; then
      echo R7A3B_BOOTSTRAP_FAILED
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi
if [[ "$RC" -eq 0 ]] && ! python3 -m py_compile "$TMP/tools/r7a3b_strategy25_static_gap_closure_plan.py"; then
  echo R7A3B_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]] && ! (cd "$TMP" && python3 -m pytest -q tests/test_r7a3b_strategy25_static_gap_closure_plan.py); then
  echo R7A3B_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3B_START
  echo MODE=READ_ONLY_EXACT_STATIC_GAP_CLOSURE_PLAN
  echo STRATEGY_MUTATION_ALLOWED=false
  echo TEST_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  PYTHONPATH="$TMP/tools" python3 "$TMP/tools/r7a3b_strategy25_static_gap_closure_plan.py" \
    --root "$ROOT" \
    --contract "$TMP/backend/contracts/ZOS_R7A3B_STRATEGY25_STATIC_GAP_CLOSURE_PLAN_v1.json" || RC=$?
fi
echo R7A3B_BOOTSTRAP_COMPLETE
echo RC="$RC"
