#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
TRIGGER_UNIT=q4r3-exact25-skill-trigger-lineage-observer.service
PROJECTION_UNIT=q4r3-exact25-six-profile-projection-observer.service
PROJECTION_TIMER=q4r3-exact25-six-profile-projection-observer.timer
SCOREBOARD_UNIT=q4r3-exact25-method-scoreboard-observer.service
PRE100_UNIT=q4r3-exact25-pre100-integrity-audit.service
PRE100_TIMER=q4r3-exact25-pre100-integrity-audit.timer

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_six_profile_projection_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_six_profile_projection_observer.py"
ACTIVE_SCRIPT="$ROOT/tools/q4r3_exact25_observers/q4r3_exact25_six_profile_projection_observer.py"
TRIGGER_ROOT="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer"
TRIGGER_STATUS="$TRIGGER_ROOT/status_latest.json"
EVENTS="$TRIGGER_ROOT/skill_events.jsonl"
PROJECTION_ROOT="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer"
PROJECTION_STATUS="$PROJECTION_ROOT/status_latest.json"
PRE100_ROOT="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit"
PRE100_STATUS="$PRE100_ROOT/status_latest.json"
PRE100_VIOLATIONS="$PRE100_ROOT/violations_latest.json"
FIX_QUEUE="$PRE100_ROOT/fix_queue_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
JOB="$ROOT/runtime/q4r3_exact25_projection_blocked_counter_hotfix_job_latest.json"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$ACTIVE_SCRIPT" "$TRIGGER_STATUS" "$EVENTS" "$PROJECTION_STATUS" "$PRE100_STATUS" "$PRE100_VIOLATIONS" "$FIX_QUEUE" "$LEDGER"; do
  [[ -e "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

for unit in "$PRODUCER_UNIT" "$WRITER_UNIT" "$PROJECTION_TIMER" "$PRE100_TIMER"; do
  systemctl is-active --quiet "$unit" || { echo "REQUIRED_UNIT_INACTIVE=$unit"; exit 1; }
done

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_ROWS_BEFORE="$(awk 'NF{n++} END{print n+0}' "$LEDGER")"
LEDGER_PREFIX_HASH_BEFORE="$(head -n "$LEDGER_ROWS_BEFORE" "$LEDGER" | sha256sum | awk '{print $1}')"
ACTIVE_HASH_BEFORE="$(sha256sum "$ACTIVE_SCRIPT" | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"
systemctl start "$PROJECTION_UNIT"
systemctl start "$SCOREBOARD_UNIT"
systemctl start "$PRE100_UNIT" || true

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_ROWS_AFTER="$(awk 'NF{n++} END{print n+0}' "$LEDGER")"
LEDGER_PREFIX_HASH_AFTER="$(head -n "$LEDGER_ROWS_BEFORE" "$LEDGER" | sha256sum | awk '{print $1}')"
ACTIVE_HASH_AFTER="$(sha256sum "$ACTIVE_SCRIPT" | awk '{print $1}')"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
(( LEDGER_ROWS_AFTER >= LEDGER_ROWS_BEFORE ))
test "$LEDGER_PREFIX_HASH_BEFORE" = "$LEDGER_PREFIX_HASH_AFTER"
test "$ACTIVE_HASH_BEFORE" != "$ACTIVE_HASH_AFTER"

"$PY" - "$TRIGGER_STATUS" "$PROJECTION_STATUS" "$PRE100_STATUS" "$PRE100_VIOLATIONS" "$FIX_QUEUE" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

trigger=json.load(open(sys.argv[1],encoding='utf-8'))
projection=json.load(open(sys.argv[2],encoding='utf-8'))
pre100=json.load(open(sys.argv[3],encoding='utf-8'))
violations=json.load(open(sys.argv[4],encoding='utf-8'))
fix=json.load(open(sys.argv[5],encoding='utf-8'))

expected=int(trigger.get('skill_blocked_count') or 0)
observed=int(projection.get('total_blocked_count') or 0)
profile=int(projection.get('profile_blocked_count') or 0)
unassigned=int(projection.get('unassigned_blocked_count') or 0)
assert projection.get('state')=='PASS', projection
assert observed==expected, (observed, expected)
assert profile+unassigned==observed, (profile, unassigned, observed)
remaining=[row for row in (violations.get('violations') or []) if row.get('code')=='PROJECTION_BLOCKED_COUNT_MISMATCH']
assert not remaining, remaining
fix_remaining=[row for row in (fix.get('items') or []) if row.get('code')=='PROJECTION_BLOCKED_COUNT_MISMATCH']
assert not fix_remaining, fix_remaining

payload={
  'job':'q4r3_exact25_projection_blocked_counter_hotfix',
  'state':'PASS',
  'current_stage':'complete',
  'status':'PASS_Q4R3_EXACT25_PROJECTION_BLOCKED_COUNTER_HOTFIX',
  'updated_at':datetime.now(timezone.utc).isoformat(),
  'trigger_blocked_count':expected,
  'projection_total_blocked_count':observed,
  'projection_profile_blocked_count':profile,
  'projection_unassigned_blocked_count':unassigned,
  'projection_unassigned_blocked_method_ids':projection.get('unassigned_blocked_method_ids') or [],
  'pre100_state':pre100.get('state'),
  'pre100_verdict':pre100.get('verdict'),
  'pre100_critical_count':pre100.get('critical_count'),
  'pre100_major_count':pre100.get('major_count'),
  'pre100_violation_count':pre100.get('violation_count'),
  'strategy_modified':False,
  'trade_method_modified':False,
  'skill_registry_modified':False,
  'producer_modified':False,
  'writer_modified':False,
  'formal_ledger_modified':False,
  'paper_enabled':False,
  'live_enabled':False,
  'order_enabled':False,
  'order_authority':'blocked',
  'execution_authority':'none',
  'action':'hold'
}
path=Path(sys.argv[6]); tmp=path.with_suffix(path.suffix+'.tmp')
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
os.replace(tmp,path)
print(json.dumps(payload,ensure_ascii=False,sort_keys=True))
PY

echo Q4R3_EXACT25_PROJECTION_BLOCKED_COUNTER_HOTFIX_PASS
echo "PROJECTION_STATUS=$PROJECTION_STATUS"
echo "PRE100_STATUS=$PRE100_STATUS"
echo "FIX_QUEUE=$FIX_QUEUE"
echo "JOB=$JOB"
