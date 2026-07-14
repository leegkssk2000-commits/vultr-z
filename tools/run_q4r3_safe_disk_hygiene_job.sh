#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_DISK_HYGIENE_WORKTREE:-/tmp/q4r3-safe-disk-hygiene}
PYTHON_BIN=$ROOT/.venv/bin/python
SCRIPT=$WORKTREE/tools/q4r3_safe_disk_hygiene.py
TEST_FILE=$WORKTREE/tests/test_q4r3_safe_disk_hygiene.py

OUTDIR=$ROOT/runtime/q4r3_safe_disk_hygiene
AUDIT_REPORT=$OUTDIR/audit_latest.json
APPLY_REPORT=$OUTDIR/apply_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_safe_disk_hygiene_job_latest.json
LOG=$ROOT/runtime/q4r3_safe_disk_hygiene_job.log

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
CAPTURE_TIMER=q4r3-exact25-preentry-method-context-capture.timer
CAPTURE_STATUS=$ROOT/runtime/exact25_edge_v1/preentry_method_context/status_latest.json
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods

exec > >(tee -a "$LOG") 2>&1

write_status() {
  local state=$1
  local stage=$2
  local reason=$3
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$stage" "$reason" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path=Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps({
  "job":"q4r3_safe_disk_hygiene","state":sys.argv[2],"current_stage":sys.argv[3],
  "reason":sys.argv[4],"updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "runtime_deleted":False,"backup_deleted":False,"repository_source_deleted":False,
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

fail() {
  local stage=$1
  local reason=$2
  trap - ERR
  write_status FAILED "$stage" "$reason"
  echo "SAFE_DISK_HYGIENE_FAILED:$stage:$reason"
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$WORKTREE" "$PYTHON_BIN" "$SCRIPT" "$TEST_FILE" "$FORMAL_LEDGER" "$CAPTURE_STATUS"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done
systemctl is-active --quiet "$PRODUCER_UNIT" || fail preflight PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail preflight WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail preflight PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

"$PYTHON_BIN" - "$CAPTURE_STATUS" <<'PY'
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data.get("state") == "HEALTHY", data
assert data.get("method_neutral") is True, data
assert data.get("historical_backfill_allowed") is False, data
PY

mkdir -p "$OUTDIR"
write_status RUNNING preflight_and_audit started

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_BEFORE=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_METHOD_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
DISK_BEFORE=$(df -B1 --output=used,avail,pcent / | tail -1 | xargs)

"$PYTHON_BIN" -m py_compile "$SCRIPT"
cd "$WORKTREE"
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"

"$PYTHON_BIN" "$SCRIPT" --output "$AUDIT_REPORT"

# Allowlisted system caches only. No runtime, backups, source, registry, ledger,
# snapshots, or evidence directories are touched.
apt-get clean
journalctl --vacuum-size=256M --no-pager || true

"$PYTHON_BIN" "$SCRIPT" --apply --output "$APPLY_REPORT"

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_AFTER=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_METHOD_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
DISK_AFTER=$(df -B1 --output=used,avail,pcent / | tail -1 | xargs)

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$ACTIVE_METHOD_HASH_BEFORE" = "$ACTIVE_METHOD_HASH_AFTER" ] || fail immutability ACTIVE_TRADE_METHOD_SOURCE_CHANGED
[ "$FORMAL_ROWS_AFTER" -ge "$FORMAL_ROWS_BEFORE" ] || fail immutability FORMAL_LEDGER_ROW_COUNT_DECREASED

FORMAL_HASH_UNCHANGED=false
FORMAL_EXTERNAL_APPEND=false
if [ "$FORMAL_HASH_BEFORE" = "$FORMAL_HASH_AFTER" ]; then
  FORMAL_HASH_UNCHANGED=true
elif [ "$FORMAL_ROWS_AFTER" -gt "$FORMAL_ROWS_BEFORE" ]; then
  FORMAL_EXTERNAL_APPEND=true
else
  fail immutability FORMAL_LEDGER_CHANGED_WITHOUT_APPEND
fi

systemctl is-active --quiet "$PRODUCER_UNIT" || fail postcheck PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail postcheck WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail postcheck PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

"$PYTHON_BIN" - "$APPLY_REPORT" "$JOB_STATUS" "$DISK_BEFORE" "$DISK_AFTER" "$FORMAL_HASH_UNCHANGED" "$FORMAL_EXTERNAL_APPEND" "$FORMAL_ROWS_BEFORE" "$FORMAL_ROWS_AFTER" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
report=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload={
  "job":"q4r3_safe_disk_hygiene","state":"PASS","current_stage":"complete",
  "status":"PASS_Q4R3_SAFE_DISK_HYGIENE","verdict":"ALLOWLISTED_TRANSIENT_CLEANUP_COMPLETE",
  "updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "disk_before":sys.argv[3],"disk_after":sys.argv[4],
  "free_bytes_delta":report.get("free_bytes_delta"),"removed_count":report.get("removed_count"),
  "removed_declared_bytes":report.get("removed_declared_bytes"),
  "candidate_count":report.get("candidate_count"),
  "runtime_deleted":False,"backup_deleted":False,"repository_source_deleted":False,
  "producer_pid_unchanged":True,"writer_pid_unchanged":True,
  "active_trade_method_hash_unchanged":True,
  "formal_ledger_hash_unchanged":sys.argv[5].lower()=="true",
  "formal_ledger_external_append_detected":sys.argv[6].lower()=="true",
  "formal_ledger_rows_before":int(sys.argv[7]),"formal_ledger_rows_after":int(sys.argv[8]),
  "formal_ledger_not_modified_by_job":True,"capture_timer_active":True,
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none",
  "next_action":"REVIEW_LARGEST_REMAINING_PROTECTED_ROOTS_BEFORE_ANY_BACKUP_RETENTION_CLEANUP"
}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q4R3_SAFE_DISK_HYGIENE_PASS")
PY

trap - ERR
echo Q4R3_SAFE_DISK_HYGIENE_INSTALL_PASS
