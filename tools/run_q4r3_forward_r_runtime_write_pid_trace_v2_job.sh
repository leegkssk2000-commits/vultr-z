#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-runtime-write-pid-trace}
BASE_RUNNER=$WORKTREE/tools/run_q4r3_forward_r_runtime_write_pid_trace_job.sh
V2_MODULE=$WORKTREE/tools/q4r3_forward_r_runtime_write_pid_trace_v2.py
V2_TEST=$WORKTREE/tests/test_q4r3_forward_r_runtime_write_pid_trace_v2.py

for required in "$BASE_RUNNER" "$V2_MODULE" "$V2_TEST"; do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

cd "$WORKTREE"
echo '=== RUNTIME WRITE PID TRACE V2 FREEZE CONTRACT TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  "$PYTHON_BIN" -m pytest -q "$V2_TEST"

TMP_RUNNER=$(mktemp /tmp/q4r3-forward-r-runtime-write-pid-trace-v2.XXXXXX.sh)
cleanup() {
  rm -f "$TMP_RUNNER"
}
trap cleanup EXIT

sed 's#q4r3_forward_r_runtime_write_pid_trace.py#q4r3_forward_r_runtime_write_pid_trace_v2.py#g' \
  "$BASE_RUNNER" > "$TMP_RUNNER"
chmod +x "$TMP_RUNNER"

/usr/bin/bash "$TMP_RUNNER"
