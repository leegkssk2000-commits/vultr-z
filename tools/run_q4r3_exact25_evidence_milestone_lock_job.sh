#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_EVIDENCE_LOCK_WORKTREE:-/tmp/q4r3-exact25-evidence-milestone-lock}
BRANCH=q4r3-exact25-six-layer-observer-suite
PYTHON_BIN=$ROOT/.venv/bin/python

SOURCE_TOOL=$WORKTREE/tools/q4r3_exact25_evidence_milestone_lock.py
SOURCE_SSOT=$WORKTREE/backend/config/q4r3_exact25_evidence_milestone_lock_ssot_v1.json
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_evidence_milestone_lock.py
ACTIVE_TOOL=$ROOT/tools/q4r3_exact25_evidence_milestone_lock.py
ACTIVE_SSOT=$ROOT/backend/config/q4r3_exact25_evidence_milestone_lock_ssot_v1.json

MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
WRITER_STATUS=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/status_latest.json
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service

OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/evidence_milestone_lock
BASELINE=$OUTPUT_ROOT/protected_surface_baseline.json
SNAPSHOT_DIR=$OUTPUT_ROOT/snapshots
EVIDENCE_LATEST=$OUTPUT_ROOT/evidence_latest.json
GATE_LATEST=$OUTPUT_ROOT/gate_latest.json
STATUS_LATEST=$OUTPUT_ROOT/status_latest.json

SERVICE_NAME=q4r3-exact25-evidence-milestone-lock.service
TIMER_NAME=q4r3-exact25-evidence-milestone-lock.timer
SERVICE_PATH=/etc/systemd/system/$SERVICE_NAME
TIMER_PATH=/etc/systemd/system/$TIMER_NAME

JOB_STATUS=$ROOT/runtime/q4r3_exact25_evidence_milestone_lock_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_evidence_milestone_lock_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_evidence_milestone_lock
RESULT=$RESULT_DIR/q4r3_exact25_evidence_milestone_lock_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_evidence_milestone_lock_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
MUTATION_STARTED=false
ROLLBACK_DONE=false

if [ "$(id -u)" -ne 0 ]; then
  echo RUN_AS_ROOT >&2
  exit 1
fi

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1 reason=$2 report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$BACKUP_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_evidence_milestone_lock",
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
    "action": "hold",
    "order_authority": "blocked",
    "execution_authority": "none",
    "strategy_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified_by_job": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        payload.update({key: result.get(key) for key in (
            "status", "verdict", "next_action", "lock_count",
            "formal_ledger_row_count", "formal_ledger_hash_unchanged",
            "producer_pid_unchanged", "writer_pid_unchanged",
            "timer_active", "observer_state", "violation_count",
            "milestone_next", "remaining_to_next",
        )})
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
tmp = path.with_suffix(path.suffix + ".tmp")
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
  local source=$1 key=$2
  mkdir -p "$BACKUP_DIR/items"
  if [ -e "$source" ]; then
    cp -a "$source" "$BACKUP_DIR/items/$key"
    echo true > "$BACKUP_DIR/$key.existed"
  else
    echo false > "$BACKUP_DIR/$key.existed"
  fi
}

restore_path() {
  local target=$1 key=$2
  rm -rf "$target"
  if [ "$(cat "$BACKUP_DIR/$key.existed" 2>/dev/null || echo false)" = true ]; then
    mkdir -p "$(dirname "$target")"
    cp -a "$BACKUP_DIR/items/$key" "$target"
  fi
}

rollback() {
  [ "$ROLLBACK_DONE" = true ] && return 0
  ROLLBACK_DONE=true
  trap - ERR
  [ "$MUTATION_STARTED" = true ] || return 0
  systemctl stop "$TIMER_NAME" "$SERVICE_NAME" 2>/dev/null || true
  restore_path "$ACTIVE_TOOL" active_tool
  restore_path "$ACTIVE_SSOT" active_ssot
  restore_path "$SERVICE_PATH" service
  restore_path "$TIMER_PATH" timer
  restore_path "$OUTPUT_ROOT" output_root
  systemctl daemon-reload || true
  [ "$(cat "$BACKUP_DIR/timer_active" 2>/dev/null || echo false)" = true ] &&
    systemctl start "$TIMER_NAME" 2>/dev/null || true
}

on_error() {
  local code=$? failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_EVIDENCE_MILESTONE_LOCK_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" "$SOURCE_TOOL" "$SOURCE_SSOT" "$TEST_FILE" \
  "$MANIFEST" "$PRODUCER_STATUS" "$WRITER_STATUS" "$FORMAL_LEDGER"; do
  [ -e "$required" ] || {
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  }
done

set_stage preflight_compile_and_tests
cd "$WORKTREE"
find "$WORKTREE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
export PYTHONPATH="$WORKTREE"
export PYTHONDONTWRITEBYTECODE=1
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_TOOL"
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_source_safety_gate
systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
[ "$PRODUCER_PID_BEFORE" != 0 ]
[ "$WRITER_PID_BEFORE" != 0 ]
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
"$PYTHON_BIN" - "$PRODUCER_STATUS" "$WRITER_STATUS" <<'PY'
import json
import sys
from pathlib import Path
for path, name in ((Path(sys.argv[1]), "producer"), (Path(sys.argv[2]), "writer")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("state") != "RUNNING":
        raise SystemExit(f"{name.upper()}_NOT_RUNNING:{payload.get('state')}")
    for key in ("paper_enabled", "live_enabled", "order_enabled"):
        if payload.get(key) not in (False, None):
            raise SystemExit(f"UNSAFE_{name.upper()}_FLAG:{key}={payload.get(key)}")
PY

set_stage backup_surfaces
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$TIMER_NAME"; then
  echo true > "$BACKUP_DIR/timer_active"
else
  echo false > "$BACKUP_DIR/timer_active"
fi
backup_path "$ACTIVE_TOOL" active_tool
backup_path "$ACTIVE_SSOT" active_ssot
backup_path "$SERVICE_PATH" service
backup_path "$TIMER_PATH" timer
backup_path "$OUTPUT_ROOT" output_root
MUTATION_STARTED=true

set_stage install_two_readonly_locks
systemctl stop "$TIMER_NAME" "$SERVICE_NAME" 2>/dev/null || true
install -m 0755 "$SOURCE_TOOL" "$ACTIVE_TOOL.tmp"
mv -f "$ACTIVE_TOOL.tmp" "$ACTIVE_TOOL"
install -m 0644 "$SOURCE_SSOT" "$ACTIVE_SSOT.tmp"
mv -f "$ACTIVE_SSOT.tmp" "$ACTIVE_SSOT"
mkdir -p "$OUTPUT_ROOT" "$SNAPSHOT_DIR"
chmod 0750 "$OUTPUT_ROOT" "$SNAPSHOT_DIR"

cat > "$SERVICE_PATH.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Immutable Evidence and Milestone Gate Lock
After=$PRODUCER_UNIT $WRITER_UNIT
Requires=$PRODUCER_UNIT $WRITER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_TOOL --root $ROOT --ledger $FORMAL_LEDGER --manifest $MANIFEST --producer-status $PRODUCER_STATUS --writer-status $WRITER_STATUS --ssot $ACTIVE_SSOT --baseline $BASELINE --snapshot-dir $SNAPSHOT_DIR --evidence-latest $EVIDENCE_LATEST --gate-latest $GATE_LATEST --status $STATUS_LATEST
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$FORMAL_LEDGER $MANIFEST $PRODUCER_STATUS $WRITER_STATUS $ACTIVE_SSOT $ROOT/backend/strategies
ReadWritePaths=$OUTPUT_ROOT
EOF
install -m 0644 "$SERVICE_PATH.tmp" "$SERVICE_PATH"
rm -f "$SERVICE_PATH.tmp"

cat > "$TIMER_PATH.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 Evidence and Milestone Lock Every Minute

[Timer]
OnBootSec=45
OnUnitActiveSec=60
AccuracySec=5
Persistent=true
Unit=$SERVICE_NAME

[Install]
WantedBy=timers.target
EOF
install -m 0644 "$TIMER_PATH.tmp" "$TIMER_PATH"
rm -f "$TIMER_PATH.tmp"

systemctl daemon-reload
systemctl enable --now "$TIMER_NAME"
systemctl start "$SERVICE_NAME"

set_stage verify_runtime_and_immutability
[ "$(systemctl show "$SERVICE_NAME" -p Result --value)" = success ]
systemctl is-active --quiet "$TIMER_NAME"
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ]
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ]
[ "$FORMAL_HASH_BEFORE" = "$FORMAL_HASH_AFTER" ]

"$PYTHON_BIN" - "$STATUS_LATEST" "$GATE_LATEST" "$EVIDENCE_LATEST" "$RESULT" \
  "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" \
  "$FORMAL_HASH_BEFORE" "$FORMAL_HASH_AFTER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
gate = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
evidence = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
result = {
    "schema": "q4r3_exact25_evidence_milestone_lock_job_result_v1",
    "status": "PASS" if status.get("state") == "CLEAR" else "HOLD",
    "verdict": "EVIDENCE_AND_MILESTONE_LOCKS_ACTIVE_CLEAR" if status.get("state") == "CLEAR" else "EVIDENCE_AND_MILESTONE_LOCKS_ACTIVE_WITH_VIOLATION",
    "action": "hold",
    "next_action": "ACCUMULATE_TO_NEXT_MILESTONE",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "lock_count": 2,
    "installed_locks": ["IMMUTABLE_EVIDENCE_SNAPSHOT", "EPOCH_MILESTONE_GATE_LOCK"],
    "observer_state": status.get("state"),
    "violation_count": status.get("violation_count"),
    "violation_severity": status.get("violation_severity"),
    "formal_ledger_row_count": evidence.get("formal_ledger_row_count"),
    "formal_ledger_sha256": evidence.get("formal_ledger_sha256"),
    "milestone_next": gate.get("milestone_state", {}).get("next"),
    "remaining_to_next": gate.get("milestone_state", {}).get("remaining_to_next"),
    "repair_fork_creation_allowed": gate.get("repair_fork_creation_allowed"),
    "final_candidate_decision_allowed": gate.get("final_candidate_decision_allowed"),
    "timer_active": True,
    "producer_pid_unchanged": sys.argv[5] == sys.argv[6],
    "writer_pid_unchanged": sys.argv[7] == sys.argv[8],
    "formal_ledger_hash_unchanged": sys.argv[9] == sys.argv[10],
    "strategy_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified_by_job": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "rollback_available": True,
}
path = Path(sys.argv[4])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

set_stage publish_sanitized_result
cd "$WORKTREE"
git add "$RESULT"
if ! git diff --cached --quiet; then
  git -c user.name="Q4R3 Exact25 Audit" \
      -c user.email="q4r3-audit@localhost" \
      commit -m "Record Exact25 evidence and milestone lock install result"
  git push origin HEAD:"$BRANCH"
fi
REPORT_COMMIT=$(git rev-parse HEAD)
CURRENT_STAGE=complete
write_job_status PASS published "$REPORT_COMMIT"
trap - ERR
echo "Q4R3_EXACT25_EVIDENCE_MILESTONE_LOCK_PASS commit=$REPORT_COMMIT"
