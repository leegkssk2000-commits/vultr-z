#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OBSERVE_SECONDS="${3:-180}"
RC=0
TMPDIR_PATH=""
cleanup(){ [[ -n "$TMPDIR_PATH" ]] && rm -rf "$TMPDIR_PATH"; }
trap cleanup EXIT
show_file(){ local src="$1" dst="$2"; mkdir -p "$(dirname "$dst")"; git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$src" > "$dst"; }
if [[ -z "$SHA" ]]; then echo R7A1A6C6B_BOOTSTRAP_FAILED; echo 'BLOCKERS=["MISSING_SHA"]'; RC=2; fi
if [[ "$RC" -eq 0 ]]; then
  TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c6b.XXXXXXXX)"
  for path in \
    tools/r7a1a6c6b_writer_count_contract_correction.py \
    tools/r7a1a6c6_exact_semantic_stability_verify.py \
    tools/r7a1a6c5_minimal_single_owner_route_correction.py \
    tools/r7a1a6_deployment_parity_command_smoke.py \
    tests/test_r7a1a6c6b_writer_count_contract_correction.py \
    backend/contracts/ZOS_R7A1A6C6B_WRITER_COUNT_CONTRACT_CORRECTION_v1.json \
    backend/contracts/ZOS_R7A1A6C6_EXACT_SEMANTIC_STABILITY_VERIFY_v1.json
  do
    if ! show_file "$path" "$TMPDIR_PATH/$path"; then
      echo R7A1A6C6B_BOOTSTRAP_FAILED
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi
if [[ "$RC" -eq 0 ]] && ! python3 -m py_compile \
  "$TMPDIR_PATH/tools/r7a1a6c6b_writer_count_contract_correction.py" \
  "$TMPDIR_PATH/tools/r7a1a6c6_exact_semantic_stability_verify.py"; then
  echo R7A1A6C6B_BOOTSTRAP_FAILED; echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'; RC=2
fi
if [[ "$RC" -eq 0 ]] && ! (cd "$TMPDIR_PATH" && python3 -m pytest -q tests/test_r7a1a6c6b_writer_count_contract_correction.py); then
  echo R7A1A6C6B_BOOTSTRAP_FAILED; echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'; RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A1A6C6B_START
  echo MODE=READ_ONLY_WRITER_COUNT_CONTRACT_CORRECTION
  echo OBSERVE_SECONDS="$OBSERVE_SECONDS"
  echo WRITER_COUNT_PROJECTION_REQUIRED=false
  echo WRITER_BINDING_REQUIRED=true
  echo ROUTE_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo WRITER_TIMER_MUTATION_ALLOWED=false
  echo TARGET_MUTATION_ALLOWED=false
  echo NO_TELEGRAM_COMMAND_REQUIRED=true
  PYTHONPATH="$TMPDIR_PATH/tools" python3 "$TMPDIR_PATH/tools/r7a1a6c6b_writer_count_contract_correction.py" \
    --root "$ROOT" \
    --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C6B_WRITER_COUNT_CONTRACT_CORRECTION_v1.json" \
    --c6-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C6_EXACT_SEMANTIC_STABILITY_VERIFY_v1.json" \
    --observe-seconds "$OBSERVE_SECONDS" || RC=$?
fi
echo R7A1A6C6B_BOOTSTRAP_COMPLETE
echo RC="$RC"
