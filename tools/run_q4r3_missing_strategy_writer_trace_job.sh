#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-missing-writer-trace}
STATUS=$ROOT/runtime/q4r3_missing_strategy_writer_trace_job_latest.json
LOG=$ROOT/runtime/q4r3_missing_strategy_writer_trace_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PUBLISH_GITHUB_RESULTS=${Q4R3_PUBLISH_GITHUB_RESULTS:-0}

TRACE=$ROOT/runtime/q4r3_missing_strategy_writer_trace_latest.json
DECISION=$ROOT/runtime/q4r3_missing_strategy_writer_trace_decision_latest.json
HANDOFF=$ROOT/runtime/q4r3_missing_strategy_writer_trace_handoff_latest.json
HTML=$ROOT/runtime/q4r3_missing_strategy_writer_trace_latest.html
PUBLISH_STATUS=$ROOT/runtime/q4r3_missing_strategy_writer_trace_publish_latest.json

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$TRACE" "$DECISION" "$HANDOFF" "$HTML" "$PUBLISH_STATUS" "$PUBLISH_GITHUB_RESULTS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "trace": Path(sys.argv[5]),
    "decision": Path(sys.argv[6]),
    "handoff": Path(sys.argv[7]),
    "html": Path(sys.argv[8]),
    "publish": Path(sys.argv[9]),
}
publish_requested = sys.argv[10] == "1"
payload = {
    "job": "q4r3_missing_strategy_writer_trace",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
    "github_publish_requested": publish_requested,
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "final_holdout_opened": False,
}
if paths["decision"].exists():
    try:
        decision = json.loads(paths["decision"].read_text(errors="ignore"))
        payload["result_status"] = decision.get("status")
        payload["verdict"] = decision.get("verdict")
        payload["action"] = decision.get("action")
        payload["missing_strategy_count"] = decision.get("missing_strategy_count")
        payload["diagnosis_counts"] = decision.get("diagnosis_counts")
        payload["unresolved_count"] = decision.get("unresolved_count")
        payload["next_modules"] = decision.get("next_modules")
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
if paths["publish"].exists():
    try:
        publish = json.loads(paths["publish"].read_text(errors="ignore"))
        payload["github_publish_state"] = publish.get("state")
        payload["github_publish_reason"] = publish.get("reason")
        payload["github_publish_commit"] = publish.get("commit_sha")
        payload["github_publish_branch"] = publish.get("branch")
    except Exception as exc:
        payload["publish_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_MISSING_STRATEGY_WRITER_TRACE_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

mkdir -p $ROOT/runtime
: > $LOG
exec > >(tee -a $LOG) 2>&1

for required in \
  $WORKTREE/tools/q4r3_missing_strategy_writer_trace.py \
  $WORKTREE/tools/publish_q4r3_sanitized_runtime_results.sh \
  $WORKTREE/tests/test_q4r3_missing_strategy_writer_trace.py \
  $ROOT/runtime/q4r3_25_strategy_realized_r_coverage_latest.json \
  $ROOT/runtime/q4r3_25_strategy_realized_r_ledger_latest.json \
  $ROOT/runtime/q4r3_25_strategy_realized_r_source_audit_latest.json
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$TRACE" "$DECISION" "$HANDOFF" "$HTML" "$PUBLISH_STATUS"
write_status RUNNING tests

echo === MISSING STRATEGY WRITER TRACE TESTS ===
PYTHONPATH=$WORKTREE:$ROOT $PYTHON_BIN -m pytest -q $WORKTREE/tests/test_q4r3_missing_strategy_writer_trace.py

write_status RUNNING scan_and_classify_missing_writers

echo === MISSING STRATEGY WRITER TRACE ===
PYTHONPATH=$WORKTREE:$ROOT $PYTHON_BIN $WORKTREE/tools/q4r3_missing_strategy_writer_trace.py

for output in "$TRACE" "$DECISION" "$HANDOFF" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

publish_reason=publish_not_requested
if [ "$PUBLISH_GITHUB_RESULTS" = "1" ]; then
  write_status RUNNING publish_sanitized_handoff_to_github
  chmod +x "$WORKTREE/tools/publish_q4r3_sanitized_runtime_results.sh"
  if Q4R3_RESULT_BRANCH=q4r3-runtime-results "$WORKTREE/tools/publish_q4r3_sanitized_runtime_results.sh"; then
    publish_reason=github_publish_complete
  else
    publish_reason=local_trace_complete_github_publish_failed
  fi
fi

write_status DONE "$publish_reason"

echo === DECISION ===
jq . "$DECISION"
echo === SANITIZED HANDOFF ===
jq . "$HANDOFF"
echo === PUBLISH STATUS ===
if [ -s "$PUBLISH_STATUS" ]; then jq . "$PUBLISH_STATUS"; else echo PUBLISH_NOT_REQUESTED; fi
echo Q4R3_MISSING_STRATEGY_WRITER_TRACE_JOB_DONE
