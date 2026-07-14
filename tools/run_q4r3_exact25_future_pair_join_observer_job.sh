#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
TRIGGER_TIMER=q4r3-exact25-skill-trigger-lineage-observer.timer
PROJECTION_TIMER=q4r3-exact25-six-profile-projection-observer.timer
UNIT=q4r3-exact25-future-pair-join-observer

TRIGGER_ROOT="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer"
TRIGGER_STATUS="$TRIGGER_ROOT/status_latest.json"
ACTIVATION="$TRIGGER_ROOT/activation.json"
EVENTS="$TRIGGER_ROOT/skill_events.jsonl"
PROJECTION_STATUS="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_future_pair_join_observer.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer"
OUTPUT="$OUTDIR/pairs_latest.json"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_future_pair_join_observer_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_future_pair_join_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_future_pair_join_observer.py"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$TRIGGER_STATUS" "$ACTIVATION" "$PROJECTION_STATUS" "$LEDGER" "$STORAGE_STATUS"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
systemctl is-active --quiet "$TRIGGER_TIMER"
systemctl is-active --quiet "$PROJECTION_TIMER"

"$PY" - "$TRIGGER_STATUS" "$PROJECTION_STATUS" "$ACTIVATION" "$STORAGE_STATUS" <<'PY'
import json, sys
trigger=json.load(open(sys.argv[1],encoding='utf-8'))
projection=json.load(open(sys.argv[2],encoding='utf-8'))
activation=json.load(open(sys.argv[3],encoding='utf-8'))
storage=json.load(open(sys.argv[4],encoding='utf-8'))
assert trigger.get('state')=='PASS', trigger
assert trigger.get('observer_only') is True, trigger
assert trigger.get('formal_ledger_modified') is False, trigger
assert projection.get('state')=='PASS', projection
assert projection.get('profile_count')==6, projection
assert projection.get('formal_ledger_modified') is False, projection
assert activation.get('historical_backfill_allowed') is False, activation
assert storage.get('state')=='PASS', storage
assert storage.get('verdict')=='STORAGE_REGROWTH_GUARD_HEALTHY', storage
print('PREFLIGHT_CONTRACT=PASS')
PY

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_BEFORE="$(sha256sum "$LEDGER" | awk '{print $1}')"
TRIGGER_STATUS_HASH_BEFORE="$(sha256sum "$TRIGGER_STATUS" | awk '{print $1}')"
PROJECTION_STATUS_HASH_BEFORE="$(sha256sum "$PROJECTION_STATUS" | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Future Pair Join Read-Only Observer
After=$TRIGGER_TIMER $PROJECTION_TIMER
Requires=$TRIGGER_TIMER $PROJECTION_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --trigger-status $TRIGGER_STATUS --projection-status $PROJECTION_STATUS --activation $ACTIVATION --events $EVENTS --ledger $LEDGER --output $OUTPUT --status $STATUS --violations $VIOLATIONS
User=root
Group=root
Nice=15
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$ROOT
ReadWritePaths=$OUTDIR
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
EOF

cat > "/etc/systemd/system/$UNIT.timer" <<EOF
[Unit]
Description=Q4R3 Exact25 Future Pair Join Observer Timer

[Timer]
OnBootSec=105s
OnUnitActiveSec=60s
AccuracySec=5s
Persistent=true
Unit=$UNIT.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl start "$UNIT.service" || {
  code="$?"
  [[ "$code" -eq 2 && -f "$STATUS" ]] || exit "$code"
}

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_AFTER="$(sha256sum "$LEDGER" | awk '{print $1}')"
TRIGGER_STATUS_HASH_AFTER="$(sha256sum "$TRIGGER_STATUS" | awk '{print $1}')"
PROJECTION_STATUS_HASH_AFTER="$(sha256sum "$PROJECTION_STATUS" | awk '{print $1}')"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER"
test "$TRIGGER_STATUS_HASH_BEFORE" = "$TRIGGER_STATUS_HASH_AFTER"
test "$PROJECTION_STATUS_HASH_BEFORE" = "$PROJECTION_STATUS_HASH_AFTER"
systemctl is-active --quiet "$UNIT.timer"

"$PY" - "$STATUS" "$VIOLATIONS" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status=json.load(open(sys.argv[1],encoding='utf-8'))
violations=json.load(open(sys.argv[2],encoding='utf-8'))
assert status.get('state')=='PASS', status
assert status.get('observer_only') is True, status
assert status.get('formal_ledger_modified') is False, status
assert status.get('historical_backfill_performed') is False, status
assert violations.get('count')==0, violations
payload={
    'job':'q4r3_exact25_future_pair_join_observer',
    'state':'PASS',
    'current_stage':'complete',
    'status':'PASS_Q4R3_EXACT25_FUTURE_PAIR_JOIN_OBSERVER',
    'verdict':status.get('verdict'),
    'updated_at':datetime.now(timezone.utc).isoformat(),
    'trigger_count':status.get('trigger_count'),
    'exact_pair_count':status.get('exact_pair_count'),
    'pending_close_count':status.get('pending_close_count'),
    'orphan_close_count':status.get('orphan_close_count'),
    'observer_only':True,
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
    'action':'hold',
}
path=Path(sys.argv[3])
path.parent.mkdir(parents=True,exist_ok=True)
tmp=path.with_suffix(path.suffix+'.tmp')
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
os.replace(tmp,path)
PY

echo Q4R3_EXACT25_FUTURE_PAIR_JOIN_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "PAIRS=$OUTPUT"
echo "VIOLATIONS=$VIOLATIONS"
echo "JOB=$JOB"
