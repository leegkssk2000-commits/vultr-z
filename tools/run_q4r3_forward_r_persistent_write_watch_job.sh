#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-persistent-write-watch}
TOTAL_SECONDS=${Q4R3_WATCH_TOTAL_SECONDS:-259200}
SLICE_SECONDS=${Q4R3_WATCH_SLICE_SECONDS:-21600}
POLL_SECONDS=${Q4R3_TRACE_POLL_SECONDS:-10}
RETRY_SLEEP_SECONDS=${Q4R3_WATCH_RETRY_SLEEP_SECONDS:-5}

TRACE_RUNNER=$WORKTREE/tools/run_q4r3_forward_r_runtime_write_pid_trace_v2_job.sh
CLASSIFIER=$WORKTREE/tools/q4r3_forward_r_persistent_write_watch_state.py
TEST_FILE=$WORKTREE/tests/test_q4r3_forward_r_persistent_write_watch_state.py
DECISION=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_decision_latest.json
TRACE=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_latest.json
HTML=$ROOT/runtime/q4r3_forward_r_runtime_write_pid_trace_latest.html
STATUS=$ROOT/runtime/q4r3_forward_r_persistent_write_watch_job_latest.json
LOG=$ROOT/runtime/q4r3_forward_r_persistent_write_watch_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)
CYCLE=0
LAST_CLASSIFICATION=NONE
LAST_VERDICT=""

write_status() {
  local state=$1
  local reason=$2
  local elapsed=$3
  local current_slice=$4
  local classification=${5:-$LAST_CLASSIFICATION}
  local verdict=${6:-$LAST_VERDICT}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$elapsed" "$TOTAL_SECONDS" "$SLICE_SECONDS" "$current_slice" "$CYCLE" "$classification" "$verdict" "$DECISION" "$TRACE" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
elapsed = int(sys.argv[5])
total = int(sys.argv[6])
slice_seconds = int(sys.argv[7])
current_slice = int(sys.argv[8])
cycle = int(sys.argv[9])
classification = sys.argv[10]
verdict = sys.argv[11] or None
decision_path = Path(sys.argv[12])
trace_path = Path(sys.argv[13])
html_path = Path(sys.argv[14])

payload = {
    "job": "q4r3_forward_r_persistent_write_watch",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "elapsed_sec": elapsed,
    "total_watch_sec": total,
    "slice_sec": slice_seconds,
    "current_slice_sec": current_slice,
    "cycle": cycle,
    "classification": classification,
    "verdict": verdict,
    "outputs": {
        "decision": str(decision_path),
        "trace": str(trace_path),
        "html": str(html_path),
    },
    "output_exists": {
        "decision": decision_path.exists() and decision_path.stat().st_size > 0,
        "trace": trace_path.exists() and trace_path.stat().st_size > 0,
        "html": html_path.exists() and html_path.stat().st_size > 0,
    },
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "final_holdout_opened": False,
}
if decision_path.exists() and decision_path.stat().st_size > 0:
    try:
        decision = json.loads(decision_path.read_text(errors="ignore"))
        for key in (
            "observed_event_count",
            "observed_target_count",
            "owner_counts",
            "target_owners",
            "next_action",
        ):
            payload[key] = decision.get(key)
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)

temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  local now elapsed
  now=$(date +%s)
  elapsed=$((now - START_EPOCH))
  write_status FAILED "exit_code=$code" "$elapsed" 0 "$LAST_CLASSIFICATION" "$LAST_VERDICT" || true
  echo Q4R3_FORWARD_R_PERSISTENT_WRITE_WATCH_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$TRACE_RUNNER" "$CLASSIFIER" "$TEST_FILE"; do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done
if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi
if [ "$TOTAL_SECONDS" -le 0 ] || [ "$SLICE_SECONDS" -le 0 ] || [ "$POLL_SECONDS" -le 0 ]; then
  echo INVALID_WATCH_INTERVAL >&2
  exit 2
fi

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

cd "$WORKTREE"
echo '=== PERSISTENT WRITE WATCH TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

write_status RUNNING persistent_watch_started 0 0 NONE ""
DEADLINE=$((START_EPOCH + TOTAL_SECONDS))

while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_EPOCH))
  REMAINING=$((DEADLINE - NOW))
  if [ "$REMAINING" -le 0 ]; then
    write_status DONE persistent_watch_timeout_no_event "$ELAPSED" 0 "$LAST_CLASSIFICATION" "$LAST_VERDICT"
    echo Q4R3_FORWARD_R_PERSISTENT_WRITE_WATCH_TIMEOUT_NO_EVENT
    exit 0
  fi

  CURRENT_SLICE=$SLICE_SECONDS
  if [ "$CURRENT_SLICE" -gt "$REMAINING" ]; then
    CURRENT_SLICE=$REMAINING
  fi
  CYCLE=$((CYCLE + 1))
  write_status RUNNING "trace_cycle_$CYCLE" "$ELAPSED" "$CURRENT_SLICE" "$LAST_CLASSIFICATION" "$LAST_VERDICT"
  echo === TRACE_CYCLE=$CYCLE SLICE_SECONDS=$CURRENT_SLICE REMAINING_SECONDS=$REMAINING ===

  set +e
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_TRACE_SECONDS="$CURRENT_SLICE" \
  Q4R3_TRACE_POLL_SECONDS="$POLL_SECONDS" \
    /usr/bin/bash "$TRACE_RUNNER"
  CHILD_CODE=$?
  set -e
  if [ "$CHILD_CODE" -ne 0 ]; then
    echo CHILD_TRACE_FAILED:$CHILD_CODE >&2
    exit "$CHILD_CODE"
  fi

  CLASS_JSON=$("$PYTHON_BIN" "$CLASSIFIER" "$DECISION")
  LAST_CLASSIFICATION=$(printf '%s' "$CLASS_JSON" | jq -r '.classification // "UNKNOWN"')
  LAST_VERDICT=$(printf '%s' "$CLASS_JSON" | jq -r '.verdict // ""')
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_EPOCH))

  case "$LAST_CLASSIFICATION" in
    EVIDENCE)
      write_status DONE authoritative_write_evidence_observed "$ELAPSED" "$CURRENT_SLICE" "$LAST_CLASSIFICATION" "$LAST_VERDICT"
      echo Q4R3_FORWARD_R_PERSISTENT_WRITE_WATCH_EVIDENCE_OBSERVED verdict="$LAST_VERDICT"
      exit 0
      ;;
    CONTINUE)
      write_status RUNNING no_event_continue_waiting "$ELAPSED" "$CURRENT_SLICE" "$LAST_CLASSIFICATION" "$LAST_VERDICT"
      ;;
    BLOCKED)
      write_status HOLD trace_backend_blocked "$ELAPSED" "$CURRENT_SLICE" "$LAST_CLASSIFICATION" "$LAST_VERDICT"
      echo Q4R3_FORWARD_R_PERSISTENT_WRITE_WATCH_BLOCKED verdict="$LAST_VERDICT" >&2
      exit 4
      ;;
    *)
      write_status HOLD unknown_trace_decision "$ELAPSED" "$CURRENT_SLICE" "$LAST_CLASSIFICATION" "$LAST_VERDICT"
      echo Q4R3_FORWARD_R_PERSISTENT_WRITE_WATCH_UNKNOWN_DECISION verdict="$LAST_VERDICT" >&2
      exit 5
      ;;
  esac

  sleep "$RETRY_SLEEP_SECONDS"
done
