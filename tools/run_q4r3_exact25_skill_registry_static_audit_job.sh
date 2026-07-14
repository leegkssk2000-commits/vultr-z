#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_SKILL_AUDIT_WORKTREE:-/home/z/z/.worktrees/q4r3-exact25-skill-registry-static-audit}
PYTHON_BIN=$ROOT/.venv/bin/python
SCRIPT=$WORKTREE/tools/q4r3_exact25_skill_registry_static_audit.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_skill_registry_static_audit.py
OUTDIR=$ROOT/runtime/exact25_edge_v1/skill_registry_static_audit
REPORT=$OUTDIR/report_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_skill_registry_static_audit_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_skill_registry_static_audit_job.log

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
CAPTURE_TIMER=q4r3-exact25-preentry-method-context-capture.timer
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
ACTIVE_SKILL_REGISTRY=$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json
ACTIVE_SKILL_RESOLVER=$ROOT/backend/engine/skill_resolver.py

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
  "job":"q4r3_exact25_skill_registry_static_audit",
  "state":sys.argv[2],"current_stage":sys.argv[3],"reason":sys.argv[4],
  "updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "skill_registry_modified":False,"skill_resolver_modified":False,
  "strategy_modified":False,"producer_modified":False,"writer_modified":False,
  "formal_ledger_modified":False,"paper_enabled":False,"live_enabled":False,
  "order_enabled":False,"order_authority":"blocked","execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

fail() {
  local stage=$1
  local reason=$2
  trap - ERR
  write_status FAILED "$stage" "$reason"
  echo "SKILL_REGISTRY_STATIC_AUDIT_FAILED:$stage:$reason"
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$WORKTREE" "$PYTHON_BIN" "$SCRIPT" "$TEST_FILE" "$FORMAL_LEDGER" "$ACTIVE_SKILL_REGISTRY" "$ACTIVE_SKILL_RESOLVER"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done
systemctl is-active --quiet "$PRODUCER_UNIT" || fail preflight PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail preflight WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail preflight PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

mkdir -p "$OUTDIR"
write_status RUNNING compile_test_and_static_audit started

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_ROWS_BEFORE=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
REGISTRY_HASH_BEFORE=$(sha256sum "$ACTIVE_SKILL_REGISTRY" | awk '{print $1}')
RESOLVER_HASH_BEFORE=$(sha256sum "$ACTIVE_SKILL_RESOLVER" | awk '{print $1}')

"$PYTHON_BIN" -m py_compile "$SCRIPT"
cd "$WORKTREE"
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"
"$PYTHON_BIN" "$SCRIPT" --repo-root "$WORKTREE" --output "$REPORT"

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_ROWS_AFTER=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
REGISTRY_HASH_AFTER=$(sha256sum "$ACTIVE_SKILL_REGISTRY" | awk '{print $1}')
RESOLVER_HASH_AFTER=$(sha256sum "$ACTIVE_SKILL_RESOLVER" | awk '{print $1}')

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$REGISTRY_HASH_BEFORE" = "$REGISTRY_HASH_AFTER" ] || fail immutability ACTIVE_SKILL_REGISTRY_CHANGED
[ "$RESOLVER_HASH_BEFORE" = "$RESOLVER_HASH_AFTER" ] || fail immutability ACTIVE_SKILL_RESOLVER_CHANGED
[ "$FORMAL_ROWS_AFTER" -ge "$FORMAL_ROWS_BEFORE" ] || fail immutability FORMAL_LEDGER_ROWS_DECREASED

FORMAL_EXTERNAL_APPEND=false
if [ "$FORMAL_HASH_BEFORE" != "$FORMAL_HASH_AFTER" ]; then
  [ "$FORMAL_ROWS_AFTER" -gt "$FORMAL_ROWS_BEFORE" ] || fail immutability FORMAL_LEDGER_CHANGED_WITHOUT_APPEND
  FORMAL_EXTERNAL_APPEND=true
fi

"$PYTHON_BIN" - "$REPORT" "$JOB_STATUS" "$FORMAL_ROWS_BEFORE" "$FORMAL_ROWS_AFTER" "$FORMAL_EXTERNAL_APPEND" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
report=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload={
  "job":"q4r3_exact25_skill_registry_static_audit","state":"PASS","current_stage":"complete",
  "status":"PASS_Q4R3_EXACT25_SKILL_REGISTRY_STATIC_AUDIT",
  "observer_state":report.get("state"),"severity":report.get("severity"),
  "verdict":report.get("verdict"),"critical_findings":report.get("critical_findings"),
  "major_findings":report.get("major_findings"),
  "skill_count":report.get("registry",{}).get("skill_count"),
  "missing_required_skill_ids":report.get("registry",{}).get("missing_required_skill_ids"),
  "strategy_file_count":report.get("strategy_binding",{}).get("strategy_file_count"),
  "strategy_files_with_skill_refs_count":report.get("strategy_binding",{}).get("strategy_files_with_skill_refs_count"),
  "next_action":report.get("next_action"),"updated_at":datetime.now(timezone.utc).isoformat(),
  "producer_pid_unchanged":True,"writer_pid_unchanged":True,
  "active_skill_registry_hash_unchanged":True,"active_skill_resolver_hash_unchanged":True,
  "formal_ledger_rows_before":int(sys.argv[3]),"formal_ledger_rows_after":int(sys.argv[4]),
  "formal_ledger_external_append_detected":sys.argv[5].lower()=="true",
  "formal_ledger_not_modified_by_job":True,"skill_registry_modified":False,
  "skill_resolver_modified":False,"strategy_modified":False,"producer_modified":False,
  "writer_modified":False,"paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none","action":"hold"
}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q4R3_EXACT25_SKILL_REGISTRY_STATIC_AUDIT_PASS")
PY

trap - ERR
