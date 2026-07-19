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
  echo R7A2_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["MISSING_SHA"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  TMP="$(mktemp -d /tmp/r7a2.XXXXXXXX)"
  for path in \
    tools/r7a2_seven_axis_s_grade_contract_freeze.py \
    tests/test_r7a2_seven_axis_s_grade_contract_freeze.py \
    backend/contracts/ZOS_R7A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE_v1.json
  do
    if ! show_file "$path" "$TMP/$path"; then
      echo R7A2_BOOTSTRAP_FAILED
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi
if [[ "$RC" -eq 0 ]] && ! python3 -m py_compile "$TMP/tools/r7a2_seven_axis_s_grade_contract_freeze.py"; then
  echo R7A2_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]] && ! (cd "$TMP" && python3 -m pytest -q tests/test_r7a2_seven_axis_s_grade_contract_freeze.py); then
  echo R7A2_BOOTSTRAP_FAILED
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A2_START
  echo MODE=READ_ONLY_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE
  echo SERVICE_MUTATION_ALLOWED=false
  echo TELEGRAM_COMMAND_SEND_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  PYTHONPATH="$TMP/tools" python3 "$TMP/tools/r7a2_seven_axis_s_grade_contract_freeze.py" \
    --root "$ROOT" --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE_v1.json" || RC=$?
fi
echo R7A2_BOOTSTRAP_COMPLETE
echo RC="$RC"
