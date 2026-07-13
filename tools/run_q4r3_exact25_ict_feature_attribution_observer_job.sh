#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_ICT_FEATURE_OBSERVER_WORKTREE:-/tmp/q4r3-exact25-ict-feature-attribution-observer}
BRANCH=q4r3-exact25-ict-feature-attribution-observer
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_OBSERVER=$WORKTREE/tools/q4r3_exact25_ict_feature_attribution_observer.py
SOURCE_SSOT=$WORKTREE/backend/config/q4r3_exact25_ict_feature_observer_ssot_v1.json
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_ict_feature_attribution_observer.py
ACTIVE_OBSERVER=$ROOT/tools/q4r3_exact25_ict_feature_attribution_observer.py
ACTIVE_SSOT=$ROOT/backend/config/q4r3_exact25_ict_feature_observer_ssot_v1.json
FORMAL_ROOT=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement
LEDGER=$FORMAL_ROOT/forward_r_ledger.jsonl
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
OBSERVER_UNIT_NAME=q4r3-exact25-ict-feature-attribution-observer.service
OBSERVER_TIMER_NAME=q4r3-exact25-ict-feature-attribution-observer.timer
OBSERVER_UNIT=/etc/systemd/system/$OBSERVER_UNIT_NAME
OBSERVER_TIMER=/etc/systemd/system/$OBSERVER_TIMER_NAME
OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/ict_feature_attribution_observer
REPORT=$OUTPUT_ROOT/attribution_latest.json
VIOLATIONS=$OUTPUT_ROOT/violations_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_ict_feature_attribution_observer_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_ict_feature_attribution_observer_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_ict_feature_attribution_observer
RESULT=$RESULT_DIR/q4r3_exact25_ict_feature_attribution_observer_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_ict_feature_attribution_observer_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
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

path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_ict_feature_attribution_observer",
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
    "action": "hold",
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "strategy_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "measurement_ledger_modified_by_job": False,
    "historical_backfill_allowed": False,
    "attribution_decision_enabled": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        payload.update({key: result.get(key) for key in (
            "status", "verdict", "next_action", "ledger_row_count",
            "entry_complete_count", "exit_complete_count", "violation_count",
            "violation_severity", "violation_notify", "observer_timer_active",
            "writer_pid_unchanged", "producer_pid_unchanged",
        )})
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
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
  echo "Q4R3_EXACT25_ICT_FEATURE_ATTRIBUTION_OBSERVER_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$SOURCE_OBSERVER" "$SOURCE_SSOT" "$TEST_FILE" "$LEDGER" "$PRODUCER_STATUS"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_compile_and_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_OBSERVER"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_measurement_safety_gate
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$PRODUCER_UNIT"
"$PYTHON_BIN" - "$PRODUCER_STATUS" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("state") != "RUNNING": raise SystemExit(f"PRODUCER_NOT_RUNNING:{payload.get('state')}")
if payload.get("feature_filter_enabled") not in (False, None): raise SystemExit("FEATURE_FILTER_ENABLED")
if payload.get("cycle_errors") not in ({}, None): raise SystemExit(f"PRODUCER_CYCLE_ERRORS:{payload.get('cycle_errors')}")
for key in ("paper_enabled", "live_enabled", "order_enabled"):
    if payload.get(key) not in (False, None): raise SystemExit(f"UNSAFE_PRODUCER_FLAG:{key}")
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

set_stage install_readonly_ict_feature_observer
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
Description=Q4R3 Exact25 Read-Only ICT Feature Attribution Observer
After=$WRITER_UNIT $PRODUCER_UNIT
Requires=$WRITER_UNIT $PRODUCER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_OBSERVER --ledger $LEDGER --producer-status $PRODUCER_STATUS --ssot $ACTIVE_SSOT --report $REPORT --violations $VIOLATIONS
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$LEDGER $PRODUCER_STATUS $ACTIVE_SSOT
ReadWritePaths=$OUTPUT_ROOT
EOF
chmod 0644 "$OBSERVER_UNIT.tmp"
mv -f "$OBSERVER_UNIT.tmp" "$OBSERVER_UNIT"

cat > "$OBSERVER_TIMER.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 ICT Feature Attribution Observer Every Minute

[Timer]
OnBootSec=45
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

set_stage verify_outputs_and_source_stability
for _ in $(seq 1 20); do
  if [ -s "$REPORT" ] && [ -s "$VIOLATIONS" ]; then break; fi
  sleep 2
done
[ -s "$REPORT" ]
[ -s "$VIOLATIONS" ]
systemctl is-active --quiet "$OBSERVER_TIMER_NAME"
UNIT_RESULT=$(systemctl show "$OBSERVER_UNIT_NAME" -p Result --value)
[ "$UNIT_RESULT" = success ]
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ]
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ]

"$PYTHON_BIN" - "$REPORT" "$VIOLATIONS" <<'PY'
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
violations = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if report.get("feature_observer_only") is not True: raise SystemExit("OBSERVER_ONLY_FLAG_MISSING")
if report.get("attribution_decision_enabled") is not False: raise SystemExit("ATTRIBUTION_DECISION_UNSAFE")
if report.get("strategy_promotion_enabled") is not False: raise SystemExit("STRATEGY_PROMOTION_UNSAFE")
if report.get("historical_backfill_allowed") is not False: raise SystemExit("BACKFILL_UNSAFE")
if report.get("action") != "hold": raise SystemExit("ACTION_NOT_HOLD")
if report.get("status") not in {"PASS", "HOLD"}: raise SystemExit(f"REPORT_STATUS_INVALID:{report.get('status')}")
if violations.get("action") != "hold": raise SystemExit("VIOLATION_ACTION_NOT_HOLD")
PY

set_stage publish_sanitized_result
"$PYTHON_BIN" - "$REPORT" "$VIOLATIONS" "$RESULT" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
violations = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
entry = report.get("coverage", {}).get("entry", {})
exit_ = report.get("coverage", {}).get("exit", {})
payload = {
    "schema": "q4r3_exact25_ict_feature_attribution_observer_result_v1",
    "status": "PASS" if report.get("status") in {"PASS", "HOLD"} else "FAIL",
    "verdict": report.get("verdict"),
    "action": "hold",
    "next_action": report.get("next_action"),
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "ledger_row_count": report.get("ledger_row_count"),
    "entry_complete_count": entry.get("complete_count"),
    "entry_complete_coverage_pct": entry.get("complete_coverage_pct"),
    "exit_complete_count": exit_.get("complete_count"),
    "exit_complete_coverage_pct": exit_.get("complete_coverage_pct"),
    "minimum_bucket_sample": report.get("minimum_bucket_sample"),
    "violation_count": violations.get("count"),
    "violation_severity": violations.get("severity"),
    "violation_notify": violations.get("notify"),
    "observer_timer_active": True,
    "writer_pid_unchanged": sys.argv[4] == sys.argv[5],
    "producer_pid_unchanged": sys.argv[6] == sys.argv[7],
    "feature_observer_only": True,
    "attribution_decision_enabled": False,
    "strategy_promotion_enabled": False,
    "measurement_ledger_modified_by_job": False,
    "historical_backfill_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}
path = Path(sys.argv[3])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

git -C "$WORKTREE" add "$RESULT"
if ! git -C "$WORKTREE" diff --cached --quiet; then
  git -C "$WORKTREE" commit -m "Record Exact25 ICT feature observer result"
  git -C "$WORKTREE" push origin "HEAD:$BRANCH"
fi
REPORT_COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)
CURRENT_STAGE=complete
write_job_status PASS "ICT feature observer installed; attribution remains observer-only" "$REPORT_COMMIT"
echo "Q4R3_EXACT25_ICT_FEATURE_ATTRIBUTION_OBSERVER_PASS commit=$REPORT_COMMIT"
