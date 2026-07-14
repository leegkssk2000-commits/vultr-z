#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_PREENTRY_CONTEXT_WORKTREE:-/tmp/q4r3-exact25-preentry-method-context-capture}
PYTHON_BIN=$ROOT/.venv/bin/python
INNER_RUNNER=$WORKTREE/tools/run_q4r3_exact25_preentry_method_context_capture_job.sh
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_preentry_method_context_capture.py
JOB_STATUS=$ROOT/runtime/q4r3_exact25_preentry_method_context_capture_job_latest.json

write_failure() {
  local stage=$1
  local reason=$2
  "$PYTHON_BIN" - "$JOB_STATUS" "$stage" "$reason" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({
  "job":"q4r3_exact25_preentry_method_context_capture",
  "state":"FAILED","current_stage":sys.argv[2],"reason":sys.argv[3],
  "updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

[ "$(id -u)" -eq 0 ] || { write_failure preflight RUN_AS_ROOT; exit 1; }
for required in "$WORKTREE" "$PYTHON_BIN" "$INNER_RUNNER" "$TEST_FILE"; do
  [ -e "$required" ] || { write_failure preflight "REQUIRED_INPUT_MISSING:$required"; exit 1; }
done

cd "$WORKTREE"
"$PYTHON_BIN" -m py_compile tools/q4r3_exact25_preentry_method_context_capture.py
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"
bash -n "$INNER_RUNNER"

Q4R3_PREENTRY_CONTEXT_WORKTREE="$WORKTREE" bash "$INNER_RUNNER"

echo Q4R3_EXACT25_PREENTRY_METHOD_CONTEXT_CAPTURE_V2_PASS
