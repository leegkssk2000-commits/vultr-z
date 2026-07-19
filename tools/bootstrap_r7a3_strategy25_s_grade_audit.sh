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
  echo R7A3_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["MISSING_SHA"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  TMP="$(mktemp -d /tmp/r7a3.XXXXXXXX)"
  for path in \
    tools/r7a3_strategy25_s_grade_audit.py \
    tests/test_r7a3_strategy25_s_grade_audit.py \
    backend/contracts/ZOS_R7A3_STRATEGY25_S_GRADE_AUDIT_v1.json
  do
    if ! show_file "$path" "$TMP/$path"; then
      echo R7A3_BOOTSTRAP_FAILED
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi
if [[ "$RC" -eq 0 ]] && ! python3 -m py_compile "$TMP/tools/r7a3_strategy25_s_grade_audit.py"; then
  echo R7A3_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]] && ! (cd "$TMP" && python3 -m pytest -q tests/test_r7a3_strategy25_s_grade_audit.py); then
  echo R7A3_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3_START
  echo MODE=READ_ONLY_STRATEGY25_S_GRADE_EVIDENCE_AUDIT
  echo STRATEGY_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  PYTHONPATH="$TMP/tools" python3 "$TMP/tools/r7a3_strategy25_s_grade_audit.py" \
    --root "$ROOT" --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7A3_STRATEGY25_S_GRADE_AUDIT_v1.json" || RC=$?
fi
echo R7A3_BOOTSTRAP_COMPLETE
echo RC="$RC"
