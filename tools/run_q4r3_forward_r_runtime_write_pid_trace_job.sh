#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-runtime-write-pid-trace}
TRACE_SECONDS=${Q4R3_TRACE_SECONDS:-1200}
POLL_SECONDS=${Q4R3_TRACE_POLL_SECONDS:-2}

STATUS=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_job_latest.json
LOG=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_job.log
TRACE=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_latest.json
DECISION=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_decision_latest.json
HTML=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_latest.html
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

BACKEND=unavailable
BACKEND_REASON=TRACE_BACKEND_NOT_CHECKED
AUDIT_KEY=""
AUDIT_RULE_ACTIVE=0

write_status() {
  local state=$1
  local reason=${2:-}
  local backend=${3:-$BACKEND}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$backend" "$TRACE_SECONDS" "$TRACE" "$DECISION" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
backend = sys.argv[5]
duration = int(sys.argv[6])
paths = {
    "trace": Path(sys.argv[7]),
    "decision": Path(sys.argv[8]),
    "html": Path(sys.argv[9]),
}
payload = {
    "job": "q4r3_forward_r_runtime_write_pid_trace",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "trace_backend": backend,
    "trace_duration_requested_sec": duration,
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
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
        payload["next_action"] = decision.get("next_action")
        payload["observed_event_count"] = decision.get("observed_event_count")
        payload["observed_target_count"] = decision.get("observed_target_count")
        payload["owner_counts"] = decision.get("owner_counts")
        payload["target_owners"] = decision.get("target_owners")
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

cleanup_audit_rule() {
  if [ "$AUDIT_RULE_ACTIVE" -eq 1 ]; then
    auditctl -W "$ROOT/runtime" -k "$AUDIT_KEY" >/dev/null 2>&1 || true
    AUDIT_RULE_ACTIVE=0
  fi
}

on_error() {
  local code=$?
  trap - ERR
  cleanup_audit_rule
  write_status FAILED "exit_code=$code" "$BACKEND" || true
  echo Q4R3_FORWARD_R_RUNTIME_WRITE_PID_TRACE_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR
trap cleanup_audit_rule EXIT

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in \
  "$WORKTREE/tools/q4r3_forward_r_runtime_write_pid_trace.py" \
  "$WORKTREE/tests/test_q4r3_forward_r_runtime_write_pid_trace.py" \
  "$ROOT/runtime/q4r3_forward_r_source_authority_latest.json" \
  "$ROOT/runtime/q4r3_forward_r_entry_writer_owner_decision_latest.json" \
  "$ROOT/runtime/q4r3_raschke_freeze_manifest_latest.json"
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$TRACE" "$DECISION" "$HTML"
write_status RUNNING tests preflight

cd "$WORKTREE"
echo === RUNTIME WRITE PID TRACE TESTS ===
PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" "$PYTHON_BIN" -m pytest -q "$WORKTREE/tests/test_q4r3_forward_r_runtime_write_pid_trace.py"

if command -v auditctl >/dev/null 2>&1 && command -v ausearch >/dev/null 2>&1; then
  if auditctl -s >/dev/null 2>&1; then
    AUDIT_KEY="q4r3r_$(date +%s)"
    if auditctl -w "$ROOT/runtime" -p wa -k "$AUDIT_KEY" >/dev/null 2>&1; then
      BACKEND=audit
      BACKEND_REASON=AUDITD_RUNTIME_DIRECTORY_WATCH_ACTIVE
      AUDIT_RULE_ACTIVE=1
    else
      BACKEND_REASON=AUDITD_RULE_ADD_FAILED
    fi
  else
    BACKEND_REASON=AUDITD_STATUS_UNAVAILABLE
  fi
else
  BACKEND_REASON=AUDITD_TOOLS_MISSING
fi

if [ "$BACKEND" = unavailable ] && command -v inotifywait >/dev/null 2>&1; then
  BACKEND=inotify
  BACKEND_REASON=INOTIFY_WITH_PROC_FD_SNAPSHOT_FALLBACK
fi

write_status RUNNING "$BACKEND_REASON" "$BACKEND"
echo === RUNTIME WRITE PID TRACE ===
echo TRACE_BACKEND=$BACKEND TRACE_SECONDS=$TRACE_SECONDS

if [ "$BACKEND" = audit ]; then
  PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" "$PYTHON_BIN" "$WORKTREE/tools/q4r3_forward_r_runtime_write_pid_trace.py" --backend audit --audit-key "$AUDIT_KEY" --duration "$TRACE_SECONDS" --poll-seconds "$POLL_SECONDS"
elif [ "$BACKEND" = inotify ]; then
  PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" "$PYTHON_BIN" "$WORKTREE/tools/q4r3_forward_r_runtime_write_pid_trace.py" --backend inotify --duration "$TRACE_SECONDS" --poll-seconds "$POLL_SECONDS"
else
  PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" "$PYTHON_BIN" "$WORKTREE/tools/q4r3_forward_r_runtime_write_pid_trace.py" --backend unavailable --duration 1 --unavailable-reason "$BACKEND_REASON"
fi

cleanup_audit_rule

for output in "$TRACE" "$DECISION" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE runtime_write_pid_trace_complete "$BACKEND"
echo === DECISION ===
jq . "$DECISION"
echo === TRACE SUMMARY ===
jq '{backend,target_file_count,duration_actual_sec,event_count:(.events|length),events:[.events[]|{observed_at,matched_target_basenames,pid,owner_identity,comm,audit_exe,cmdline,systemd_units,repo_scripts}]}' "$TRACE"
echo Q4R3_FORWARD_R_RUNTIME_WRITE_PID_TRACE_JOB_DONE
