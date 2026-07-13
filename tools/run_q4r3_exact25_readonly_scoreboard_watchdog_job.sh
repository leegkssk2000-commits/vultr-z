#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_READONLY_OBSERVER_WORKTREE:-/tmp/q4r3-exact25-readonly-scoreboard-watchdog}
BRANCH=q4r3-exact25-readonly-scoreboard-watchdog
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_OBSERVER=$WORKTREE/tools/q4r3_exact25_readonly_scoreboard_watchdog.py
SOURCE_SSOT=$WORKTREE/backend/config/q4r3_exact25_readonly_observer_ssot_v1.json
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_readonly_scoreboard_watchdog.py
ACTIVE_OBSERVER=$ROOT/tools/q4r3_exact25_readonly_scoreboard_watchdog.py
ACTIVE_SSOT=$ROOT/backend/config/q4r3_exact25_readonly_observer_ssot_v1.json
MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
FORMAL_ROOT=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement
GATE=$FORMAL_ROOT/activation_gate.json
LEDGER=$FORMAL_ROOT/forward_r_ledger.jsonl
WRITER_STATUS=$FORMAL_ROOT/status_latest.json
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
OBSERVER_UNIT_NAME=q4r3-exact25-readonly-scoreboard-watchdog.service
OBSERVER_TIMER_NAME=q4r3-exact25-readonly-scoreboard-watchdog.timer
OBSERVER_UNIT=/etc/systemd/system/$OBSERVER_UNIT_NAME
OBSERVER_TIMER=/etc/systemd/system/$OBSERVER_TIMER_NAME
OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/readonly_scoreboard_watchdog
SCOREBOARD=$OUTPUT_ROOT/strategy_scoreboard_latest.json
SAMPLE_MATRIX=$OUTPUT_ROOT/sample_matrix_latest.json
OBSERVER_STATUS=$OUTPUT_ROOT/status_latest.json
VIOLATIONS=$OUTPUT_ROOT/violations_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_readonly_scoreboard_watchdog_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_readonly_scoreboard_watchdog_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_readonly_scoreboard_watchdog
RESULT=$RESULT_DIR/q4r3_exact25_readonly_scoreboard_watchdog_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_readonly_scoreboard_watchdog_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
MUTATION_STARTED=false
ROLLBACK_DONE=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$BACKUP_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_readonly_scoreboard_watchdog",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "report_commit": sys.argv[6] or None,
    "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
    "current_stage": sys.argv[8],
    "log_path": sys.argv[9],
    "backup_dir": sys.argv[10],
    "observer_mode": "read_only",
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "measurement_ledger_modified_by_job": False,
    "historical_backfill_allowed": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "observer_timer_active",
            "observer_state", "ledger_row_count", "strategy_count", "symbol_count",
            "violation_count", "violation_notify", "violation_severity",
            "comparison_decision_enabled", "comparison_ready",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
tmp = status_path.with_suffix(status_path.suffix + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

set_stage() {
  CURRENT_STAGE=$1
  write_job_status RUNNING "stage=$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

backup_path() {
  local source=$1
  local key=$2
  mkdir -p "$BACKUP_DIR/items"
  if [ -e "$source" ]; then
    cp -a "$source" "$BACKUP_DIR/items/$key"
    echo true > "$BACKUP_DIR/$key.existed"
  else
    echo false > "$BACKUP_DIR/$key.existed"
  fi
}

restore_path() {
  local target=$1
  local key=$2
  rm -rf "$target"
  if [ "$(cat "$BACKUP_DIR/$key.existed" 2>/dev/null || echo false)" = true ]; then
    mkdir -p "$(dirname "$target")"
    cp -a "$BACKUP_DIR/items/$key" "$target"
  fi
}

rollback() {
  if [ "$ROLLBACK_DONE" = true ]; then return 0; fi
  ROLLBACK_DONE=true
  trap - ERR
  if [ "$MUTATION_STARTED" != true ]; then return 0; fi
  echo "=== ROLLBACK ==="
  systemctl stop "$OBSERVER_TIMER_NAME" 2>/dev/null || true
  systemctl stop "$OBSERVER_UNIT_NAME" 2>/dev/null || true
  restore_path "$ACTIVE_OBSERVER" active_observer
  restore_path "$ACTIVE_SSOT" active_ssot
  restore_path "$OBSERVER_UNIT" observer_unit
  restore_path "$OBSERVER_TIMER" observer_timer
  restore_path "$OUTPUT_ROOT" output_root
  systemctl daemon-reload || true
  if [ "$(cat "$BACKUP_DIR/timer_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$OBSERVER_TIMER_NAME" 2>/dev/null || true
  fi
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_READONLY_SCOREBOARD_WATCHDOG_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" \
  "$SOURCE_OBSERVER" \
  "$SOURCE_SSOT" \
  "$TEST_FILE" \
  "$MANIFEST" \
  "$GATE" \
  "$LEDGER" \
  "$WRITER_STATUS" \
  "$PRODUCER_STATUS"
do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_python_and_unit_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_OBSERVER"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_measurement_prerequisite_gate
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$PRODUCER_UNIT"
"$PYTHON_BIN" - "$GATE" "$WRITER_STATUS" "$PRODUCER_STATUS" <<'PY'
import json
import sys
from pathlib import Path

gate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
writer = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
producer = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
if gate.get("state") != "ACTIVE": raise SystemExit(f"GATE_NOT_ACTIVE:{gate.get('state')}")
if gate.get("epoch_id") != "EXACT25_EDGE_V1": raise SystemExit("GATE_EPOCH_MISMATCH")
if len(gate.get("symbols") or []) != 5 or len(set(gate.get("symbols") or [])) != 5: raise SystemExit("GATE_NOT_EXACT5")
if gate.get("strategy_count") != 25: raise SystemExit("GATE_NOT_EXACT25")
for key in ("paper_enabled", "live_enabled", "order_enabled", "historical_backfill_allowed"):
    if gate.get(key) is not False: raise SystemExit(f"UNSAFE_GATE_FLAG:{key}")
if writer.get("state") != "RUNNING": raise SystemExit(f"WRITER_NOT_RUNNING:{writer.get('state')}")
if writer.get("production_measurement_write_enabled") is not True: raise SystemExit("WRITER_MEASUREMENT_DISABLED")
if writer.get("last_error") not in (None, ""): raise SystemExit(f"WRITER_LAST_ERROR:{writer.get('last_error')}")
if producer.get("state") != "RUNNING": raise SystemExit(f"PRODUCER_NOT_RUNNING:{producer.get('state')}")
if producer.get("processed_symbol_count") != 5: raise SystemExit("PRODUCER_NOT_EXACT5")
if producer.get("cycle_errors") not in ({}, None): raise SystemExit(f"PRODUCER_CYCLE_ERRORS:{producer.get('cycle_errors')}")
PY

WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
if [ "$WRITER_PID_BEFORE" = 0 ] || [ "$PRODUCER_PID_BEFORE" = 0 ]; then
  echo "SOURCE_SERVICE_PID_INVALID writer=$WRITER_PID_BEFORE producer=$PRODUCER_PID_BEFORE" >&2
  exit 3
fi

set_stage backup_observer_surfaces
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$OBSERVER_TIMER_NAME"; then echo true > "$BACKUP_DIR/timer_was_active"; else echo false > "$BACKUP_DIR/timer_was_active"; fi
backup_path "$ACTIVE_OBSERVER" active_observer
backup_path "$ACTIVE_SSOT" active_ssot
backup_path "$OBSERVER_UNIT" observer_unit
backup_path "$OBSERVER_TIMER" observer_timer
backup_path "$OUTPUT_ROOT" output_root
MUTATION_STARTED=true

set_stage install_readonly_observer_and_timer
systemctl stop "$OBSERVER_TIMER_NAME" 2>/dev/null || true
systemctl stop "$OBSERVER_UNIT_NAME" 2>/dev/null || true
install -m 0755 "$SOURCE_OBSERVER" "$ACTIVE_OBSERVER.tmp"
mv -f "$ACTIVE_OBSERVER.tmp" "$ACTIVE_OBSERVER"
install -m 0644 "$SOURCE_SSOT" "$ACTIVE_SSOT.tmp"
mv -f "$ACTIVE_SSOT.tmp" "$ACTIVE_SSOT"
mkdir -p "$OUTPUT_ROOT"
chmod 0750 "$OUTPUT_ROOT"

cat > "$OBSERVER_UNIT.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Read-Only Strategy Scoreboard and Measurement Watchdog
After=$WRITER_UNIT $PRODUCER_UNIT
Requires=$WRITER_UNIT $PRODUCER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_OBSERVER --ledger $LEDGER --manifest $MANIFEST --gate $GATE --writer-status $WRITER_STATUS --producer-status $PRODUCER_STATUS --ssot $ACTIVE_SSOT --scoreboard $SCOREBOARD --sample-matrix $SAMPLE_MATRIX --status $OBSERVER_STATUS --violations $VIOLATIONS
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$OUTPUT_ROOT
EOF
chmod 0644 "$OBSERVER_UNIT.tmp"
mv -f "$OBSERVER_UNIT.tmp" "$OBSERVER_UNIT"

cat > "$OBSERVER_TIMER.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 Read-Only Scoreboard Watchdog Every Minute

[Timer]
OnBootSec=30
OnUnitActiveSec=60
AccuracySec=5
Persistent=true
Unit=$OBSERVER_UNIT_NAME

[Install]
WantedBy=timers.target
EOF
chmod 0644 "$OBSERVER_TIMER.tmp"
mv -f "$OBSERVER_TIMER.tmp" "$OBSERVER_TIMER"

systemctl daemon-reload
systemctl start "$OBSERVER_UNIT_NAME"
systemctl enable --now "$OBSERVER_TIMER_NAME"

set_stage verify_observer_outputs_and_source_pid_stability
for _ in $(seq 1 20); do
  if [ -s "$OBSERVER_STATUS" ] && [ -s "$SCOREBOARD" ] && [ -s "$SAMPLE_MATRIX" ]; then break; fi
  sleep 2
done
systemctl is-active --quiet "$OBSERVER_TIMER_NAME"
UNIT_RESULT=$(systemctl show "$OBSERVER_UNIT_NAME" -p Result --value)
if [ "$UNIT_RESULT" != success ]; then
  echo "OBSERVER_UNIT_RESULT_NOT_SUCCESS:$UNIT_RESULT" >&2
  exit 4
fi
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
if [ "$WRITER_PID_BEFORE" != "$WRITER_PID_AFTER" ]; then
  echo "WRITER_PID_CHANGED:$WRITER_PID_BEFORE:$WRITER_PID_AFTER" >&2
  exit 5
fi
if [ "$PRODUCER_PID_BEFORE" != "$PRODUCER_PID_AFTER" ]; then
  echo "PRODUCER_PID_CHANGED:$PRODUCER_PID_BEFORE:$PRODUCER_PID_AFTER" >&2
  exit 6
fi

"$PYTHON_BIN" - "$OBSERVER_STATUS" "$SCOREBOARD" "$SAMPLE_MATRIX" "$VIOLATIONS" <<'PY'
import json
import sys
from pathlib import Path
status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
scoreboard = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
matrix = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
if status.get("observer_mode") != "read_only": raise SystemExit("OBSERVER_NOT_READ_ONLY")
if status.get("action") != "HOLD": raise SystemExit("OBSERVER_ACTION_NOT_HOLD")
if status.get("strategy_count") != 25: raise SystemExit("OBSERVER_STRATEGY_COUNT_NOT_25")
if len(status.get("symbols") or []) != 5: raise SystemExit("OBSERVER_SYMBOL_COUNT_NOT_5")
if status.get("comparison_decision_enabled") is not False: raise SystemExit("COMPARISON_DECISION_UNEXPECTEDLY_ENABLED")
if status.get("comparison_ready") is not False: raise SystemExit("COMPARISON_UNEXPECTEDLY_READY")
if scoreboard.get("strategy_count") != 25 or len(scoreboard.get("strategies") or []) != 25: raise SystemExit("SCOREBOARD_NOT_EXACT25")
if matrix.get("ledger_row_count") != status.get("ledger_row_count"): raise SystemExit("MATRIX_LEDGER_COUNT_MISMATCH")
violations = Path(sys.argv[4])
if status.get("violation_count", 0) > 0 and not violations.is_file(): raise SystemExit("VIOLATION_FILE_MISSING")
if status.get("violation_count", 0) == 0 and violations.exists(): raise SystemExit("STALE_VIOLATION_FILE_PRESENT")
PY

set_stage publish_installation_result
"$PYTHON_BIN" - "$RESULT" "$OBSERVER_STATUS" "$SCOREBOARD" "$VIOLATIONS" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
result = Path(sys.argv[1])
status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
scoreboard = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
violation_path = Path(sys.argv[4])
violations = json.loads(violation_path.read_text(encoding="utf-8")) if violation_path.exists() else None
count = int(status.get("violation_count") or 0)
payload = {
    "schema": "q4r3_exact25_readonly_scoreboard_watchdog_result_v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS_Q4R3_EXACT25_READONLY_SCOREBOARD_WATCHDOG",
    "verdict": "READONLY_SCOREBOARD_WATCHDOG_ACTIVE" if count == 0 else "READONLY_SCOREBOARD_WATCHDOG_ACTIVE_RUNTIME_VIOLATION_DETECTED",
    "action": "HOLD",
    "next_action": "ACCUMULATE_FORMAL_CLOSE_ROWS_WITH_OBSERVER_ACTIVE" if count == 0 else "INVESTIGATE_VIOLATION_SURFACE_WITHOUT_MODIFYING_STRATEGIES_OR_LEDGER",
    "observer_timer_active": True,
    "observer_state": status.get("state"),
    "observer_mode": status.get("observer_mode"),
    "ledger_row_count": status.get("ledger_row_count"),
    "strategy_count": status.get("strategy_count"),
    "symbol_count": len(status.get("symbols") or []),
    "symbols": status.get("symbols"),
    "violation_count": count,
    "violation_notify": status.get("violation_notify"),
    "violation_severity": status.get("violation_severity"),
    "violation_fingerprint": status.get("violation_fingerprint"),
    "comparison_decision_enabled": False,
    "comparison_ready": False,
    "zero_close_strategy_count": scoreboard.get("strategy_zero_close_count"),
    "strategy_closed_count_min": scoreboard.get("strategy_closed_count_min"),
    "strategy_closed_count_max": scoreboard.get("strategy_closed_count_max"),
    "writer_pid_before": int(sys.argv[5]),
    "writer_pid_after": int(sys.argv[6]),
    "producer_pid_before": int(sys.argv[7]),
    "producer_pid_after": int(sys.argv[8]),
    "source_pids_unchanged": sys.argv[5] == sys.argv[6] and sys.argv[7] == sys.argv[8],
    "violation_bundle": violations.get("bundle") if violations else None,
    "historical_backfill_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "measurement_ledger_modified_by_job": False,
}
result.parent.mkdir(parents=True, exist_ok=True)
result.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

set_stage commit_and_push_evidence
cd "$WORKTREE"
git add runtime_results/q4r3/exact25_readonly_scoreboard_watchdog
if git diff --cached --quiet; then
  REPORT_COMMIT=$(git rev-parse HEAD)
else
  git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" commit -m "Publish read-only scoreboard watchdog evidence"
  REPORT_COMMIT=$(git rev-parse HEAD)
  git push origin HEAD:"$BRANCH"
fi

CURRENT_STAGE=complete
write_job_status PASS "readonly scoreboard watchdog installed" "$REPORT_COMMIT"
echo "Q4R3_EXACT25_READONLY_SCOREBOARD_WATCHDOG_PASS report_commit=$REPORT_COMMIT"
