#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_SKILL_AUDIT_WORKTREE:-/tmp/q4r3-exact25-skill-registry-v2-audit}
PYTHON_BIN=$ROOT/.venv/bin/python

REGISTRY=$WORKTREE/backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json
RESOLVER=$WORKTREE/backend/engine/skill_resolver_v2_candidate.py
AUDITOR=$WORKTREE/tools/q4r3_exact25_skill_registry_v2_audit.py
ENTRYPOINT=$WORKTREE/tools/q4r3_exact25_skill_registry_v2_audit_entrypoint.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_skill_registry_v2.py

OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/skill_registry_v2_audit
REPORT=$OUTPUT_ROOT/report_latest.json
MATRIX=$OUTPUT_ROOT/compatibility_matrix_latest.csv
JOB_STATUS=$ROOT/runtime/q4r3_exact25_skill_registry_v2_audit_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_skill_registry_v2_audit_job.log

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
CAPTURE_TIMER=q4r3-exact25-preentry-method-context-capture.timer
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
ACTIVE_V1=$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json
ACTIVE_RESOLVER=$ROOT/backend/engine/skill_resolver.py
ACTIVE_PRODUCER=$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods
ACTIVE_STRATEGY_ROOT=$ROOT/backend/strategies
CLEANUP_STATUS=$ROOT/runtime/q4r3_deep_storage_hygiene_job_latest.json

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
  "job":"q4r3_exact25_skill_registry_v2_audit",
  "state":sys.argv[2],
  "current_stage":sys.argv[3],
  "reason":sys.argv[4],
  "updated_at":datetime.now(timezone.utc).isoformat(),
  "action":"hold",
  "strategy_modified":False,
  "trade_method_modified":False,
  "producer_modified":False,
  "writer_modified":False,
  "formal_ledger_modified":False,
  "active_skill_registry_modified":False,
  "active_skill_resolver_modified":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

fail() {
  local stage=$1
  local reason=$2
  trap - ERR
  write_status FAILED "$stage" "$reason"
  echo "SKILL_REGISTRY_V2_AUDIT_FAILED:$stage:$reason"
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in \
  "$WORKTREE" \
  "$PYTHON_BIN" \
  "$REGISTRY" \
  "$RESOLVER" \
  "$AUDITOR" \
  "$ENTRYPOINT" \
  "$TEST_FILE" \
  "$FORMAL_LEDGER" \
  "$ACTIVE_V1" \
  "$ACTIVE_RESOLVER" \
  "$ACTIVE_PRODUCER" \
  "$ACTIVE_METHOD_ROOT" \
  "$ACTIVE_STRATEGY_ROOT" \
  "$CLEANUP_STATUS"
do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done

systemctl is-active --quiet "$PRODUCER_UNIT" || fail preflight PRODUCER_NOT_ACTIVE
systemctl is-active --quiet "$WRITER_UNIT" || fail preflight WRITER_NOT_ACTIVE
systemctl is-active --quiet "$CAPTURE_TIMER" || fail preflight PREENTRY_CAPTURE_TIMER_NOT_ACTIVE

"$PYTHON_BIN" - "$CLEANUP_STATUS" <<'PY'
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if data.get("state") != "PASS":
    raise SystemExit(f"STORAGE_HYGIENE_NOT_PASS:{data.get('state')}:{data.get('current_stage')}")
PY

mkdir -p "$OUTPUT_ROOT"
write_status RUNNING preflight storage_hygiene_passed

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_BEFORE=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_V1_HASH_BEFORE=$(sha256sum "$ACTIVE_V1" | awk '{print $1}')
ACTIVE_RESOLVER_HASH_BEFORE=$(sha256sum "$ACTIVE_RESOLVER" | awk '{print $1}')
ACTIVE_PRODUCER_HASH_BEFORE=$(sha256sum "$ACTIVE_PRODUCER" | awk '{print $1}')
ACTIVE_METHOD_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 2 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
ACTIVE_STRATEGY_HASH_BEFORE=$(find "$ACTIVE_STRATEGY_ROOT" -maxdepth 2 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

write_status RUNNING compile_and_tests started
export PYTHONPATH="$WORKTREE${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON_BIN" -m py_compile "$RESOLVER" "$AUDITOR" "$ENTRYPOINT"
cd "$WORKTREE"
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"

write_status RUNNING static_audit tests_passed
"$PYTHON_BIN" "$ENTRYPOINT" \
  --worktree "$WORKTREE" \
  --output "$REPORT" \
  --matrix-output "$MATRIX"

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_AFTER=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_V1_HASH_AFTER=$(sha256sum "$ACTIVE_V1" | awk '{print $1}')
ACTIVE_RESOLVER_HASH_AFTER=$(sha256sum "$ACTIVE_RESOLVER" | awk '{print $1}')
ACTIVE_PRODUCER_HASH_AFTER=$(sha256sum "$ACTIVE_PRODUCER" | awk '{print $1}')
ACTIVE_METHOD_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 2 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')
ACTIVE_STRATEGY_HASH_AFTER=$(find "$ACTIVE_STRATEGY_ROOT" -maxdepth 2 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$ACTIVE_V1_HASH_BEFORE" = "$ACTIVE_V1_HASH_AFTER" ] || fail immutability ACTIVE_V1_REGISTRY_CHANGED
[ "$ACTIVE_RESOLVER_HASH_BEFORE" = "$ACTIVE_RESOLVER_HASH_AFTER" ] || fail immutability ACTIVE_RESOLVER_CHANGED
[ "$ACTIVE_PRODUCER_HASH_BEFORE" = "$ACTIVE_PRODUCER_HASH_AFTER" ] || fail immutability ACTIVE_PRODUCER_CHANGED
[ "$ACTIVE_METHOD_HASH_BEFORE" = "$ACTIVE_METHOD_HASH_AFTER" ] || fail immutability ACTIVE_TRADE_METHOD_CHANGED
[ "$ACTIVE_STRATEGY_HASH_BEFORE" = "$ACTIVE_STRATEGY_HASH_AFTER" ] || fail immutability ACTIVE_STRATEGY_CHANGED
[ "$FORMAL_ROWS_AFTER" -ge "$FORMAL_ROWS_BEFORE" ] || fail immutability FORMAL_LEDGER_ROWS_DECREASED

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

"$PYTHON_BIN" - "$REPORT" "$JOB_STATUS" "$FORMAL_HASH_UNCHANGED" "$FORMAL_EXTERNAL_APPEND" "$FORMAL_ROWS_BEFORE" "$FORMAL_ROWS_AFTER" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
report=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if report.get("state") != "PASS":
    raise SystemExit(f"AUDIT_REPORT_NOT_PASS:{report.get('state')}")
payload={
  "job":"q4r3_exact25_skill_registry_v2_audit",
  "state":"PASS",
  "current_stage":"complete",
  "status":"PASS_Q4R3_EXACT25_SKILL_REGISTRY_V2_STATIC_AUDIT",
  "verdict":report.get("verdict"),
  "grade_blockers":report.get("grade_blockers"),
  "updated_at":datetime.now(timezone.utc).isoformat(),
  "action":"hold",
  "registry_v1_skill_count":report.get("registry_v1",{}).get("skill_count"),
  "registry_v2_skill_count":report.get("registry_v2",{}).get("skill_count"),
  "expected_skill_count":report.get("expected_skill_count"),
  "strategy_binding_coverage_pct":report.get("strategy_binding_coverage_pct"),
  "compatibility_matrix_rows":report.get("compatibility_matrix_rows"),
  "compatibility_expected_rows":report.get("compatibility_expected_rows"),
  "compatibility_complete":report.get("compatibility_complete"),
  "active_resolver_findings":report.get("active_resolver_findings"),
  "producer_pid_unchanged":True,
  "writer_pid_unchanged":True,
  "formal_ledger_hash_unchanged":sys.argv[3].lower()=="true",
  "formal_ledger_external_append_detected":sys.argv[4].lower()=="true",
  "formal_ledger_rows_before":int(sys.argv[5]),
  "formal_ledger_rows_after":int(sys.argv[6]),
  "formal_ledger_not_modified_by_job":True,
  "active_skill_registry_modified":False,
  "active_skill_resolver_modified":False,
  "strategy_modified":False,
  "trade_method_modified":False,
  "producer_modified":False,
  "writer_modified":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none",
  "next_action":report.get("next_action")
}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q4R3_EXACT25_SKILL_REGISTRY_V2_STATIC_AUDIT_PASS")
PY

trap - ERR
echo Q4R3_EXACT25_SKILL_REGISTRY_V2_AUDIT_JOB_PASS
