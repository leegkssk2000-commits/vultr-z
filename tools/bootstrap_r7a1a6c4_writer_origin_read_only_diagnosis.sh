#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"; SHA="${2:-}"; OBSERVE_SECONDS="${3:-180}"; POLL_MS="${4:-50}"; RC=0; TMPDIR_PATH=""
cleanup(){ [[ -n "$TMPDIR_PATH" ]] && rm -rf "$TMPDIR_PATH"; }; trap cleanup EXIT
show_file(){ local src="$1" dst="$2"; mkdir -p "$(dirname "$dst")"; git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$src" > "$dst"; }
if [[ -z "$SHA" ]]; then echo R7A1A6C4_BOOTSTRAP_FAILED; echo 'BLOCKERS=["MISSING_SHA"]'; RC=2; fi
if [[ "$RC" -eq 0 ]]; then
  TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c4.XXXXXXXX)"
  for path in tools/r7a1a6c4_diag_common.py tools/r7a1a6c4_diag_runtime.py tools/r7a1a6c4_writer_origin_read_only_diagnosis.py tests/test_r7a1a6c4_writer_origin_read_only_diagnosis.py backend/contracts/ZOS_R7A1A6C4_WRITER_ORIGIN_READ_ONLY_DIAGNOSIS_v1.json; do
    if ! show_file "$path" "$TMPDIR_PATH/$path"; then echo R7A1A6C4_BOOTSTRAP_FAILED; echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"; RC=2; break; fi
  done
fi
if [[ "$RC" -eq 0 ]] && ! python3 -m py_compile "$TMPDIR_PATH/tools/r7a1a6c4_diag_common.py" "$TMPDIR_PATH/tools/r7a1a6c4_diag_runtime.py" "$TMPDIR_PATH/tools/r7a1a6c4_writer_origin_read_only_diagnosis.py"; then echo R7A1A6C4_BOOTSTRAP_FAILED; echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'; RC=2; fi
if [[ "$RC" -eq 0 ]] && ! (cd "$TMPDIR_PATH" && python3 -m pytest -q tests/test_r7a1a6c4_writer_origin_read_only_diagnosis.py); then echo R7A1A6C4_BOOTSTRAP_FAILED; echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'; RC=2; fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A1A6C4_START; echo MODE=READ_ONLY_WRITER_AND_HTTP_ORIGIN_DIAGNOSIS; echo OBSERVE_SECONDS="$OBSERVE_SECONDS"; echo POLL_INTERVAL_MS="$POLL_MS"; echo REPAIR_ALLOWED=false; echo SERVICE_MUTATION_ALLOWED=false; echo ROUTE_MUTATION_ALLOWED=false; echo NO_TELEGRAM_COMMAND_REQUIRED=true
  PYTHONPATH="$TMPDIR_PATH/tools" python3 "$TMPDIR_PATH/tools/r7a1a6c4_writer_origin_read_only_diagnosis.py" --root "$ROOT" --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C4_WRITER_ORIGIN_READ_ONLY_DIAGNOSIS_v1.json" --observe-seconds "$OBSERVE_SECONDS" --poll-ms "$POLL_MS" || RC=$?
fi
echo R7A1A6C4_BOOTSTRAP_COMPLETE; echo RC="$RC"
