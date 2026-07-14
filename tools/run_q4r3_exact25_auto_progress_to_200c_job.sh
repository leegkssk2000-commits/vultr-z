#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PRE100_UNIT=q4r3-exact25-pre100-integrity-audit.service
PRE100_TIMER=q4r3-exact25-pre100-integrity-audit.timer
CHECKPOINT_UNIT=q4r3-exact25-100c-checkpoint-observer.service
CHECKPOINT_TIMER=q4r3-exact25-100c-checkpoint-observer.timer
UNIT=q4r3-exact25-auto-progress-to-200c

LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PRE100_STATUS="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json"
CHECKPOINT_STATUS="$ROOT/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_auto_progress_to_200c.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/auto_progress_to_200c"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_auto_progress_to_200c_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_auto_progress_to_200c.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_auto_progress_to_200c.py"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$LEDGER" "$PRE100_STATUS" "$CHECKPOINT_STATUS" "$STORAGE_STATUS"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

for unit in "$PRODUCER_UNIT" "$WRITER_UNIT" "$PRE100_TIMER" "$CHECKPOINT_TIMER"; do
  systemctl is-active --quiet "$unit"
done

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_BEFORE="$(sha256sum "$LEDGER" | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Automatic Progress Supervisor to 200C
After=$PRE100_TIMER $CHECKPOINT_TIMER
Requires=$PRE100_TIMER $CHECKPOINT_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStartPre=/usr/bin/systemctl start $PRE100_UNIT
ExecStartPre=/usr/bin/systemctl start $CHECKPOINT_UNIT
ExecStart=$PY $ACTIVE_SCRIPT --formal-ledger $LEDGER --pre100-status $PRE100_STATUS --checkpoint-status $CHECKPOINT_STATUS --storage-status $STORAGE_STATUS --status $STATUS --violations $VIOLATIONS
User=root
Group=root
Nice=15
IOSchedulingClass=idle
UMask=0022
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadOnlyPaths=$ROOT
ReadWritePaths=$OUTDIR
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
EOF

cat > "/etc/systemd/system/$UNIT.timer" <<EOF
[Unit]
Description=Q4R3 Exact25 Automatic Progress to 200C Timer

[Timer]
OnBootSec=180s
OnUnitActiveSec=60s
AccuracySec=5s
Persistent=true
Unit=$UNIT.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "$UNIT.timer"
systemctl start "$UNIT.service"

PRODUCER_PID_AFTER="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_AFTER="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_AFTER="$(sha256sum "$LEDGER" | awk '{print $1}')"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER"
systemctl is-active --quiet "$UNIT.timer"

"$PY" - "$STATUS" "$VIOLATIONS" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status=json.load(open(sys.argv[1],encoding='utf-8'))
violations=json.load(open(sys.argv[2],encoding='utf-8'))
assert status.get('state')=='PASS', status
assert status.get('auto_continue_enabled') is True, status
assert status.get('target_200c')==200, status
assert status.get('producer_stop_requested') is False, status
assert status.get('writer_stop_requested') is False, status
assert violations.get('count')==0, violations
payload={
  'job':'q4r3_exact25_auto_progress_to_200c',
  'state':'PASS',
  'current_stage':'complete',
  'status':'PASS_Q4R3_EXACT25_AUTO_PROGRESS_TO_200C',
  'phase':status.get('phase'),
  'verdict':status.get('verdict'),
  'updated_at':datetime.now(timezone.utc).isoformat(),
  'current_closed_count':status.get('current_closed_count'),
  'remaining_to_100c':status.get('remaining_to_100c'),
  'remaining_to_200c':status.get('remaining_to_200c'),
  'auto_continue_enabled':True,
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
  'action':'hold'
}
path=Path(sys.argv[3]); tmp=path.with_suffix(path.suffix+'.tmp')
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
os.replace(tmp,path)
PY

echo Q4R3_EXACT25_AUTO_PROGRESS_TO_200C_INSTALLED
echo "STATUS=$STATUS"
echo "VIOLATIONS=$VIOLATIONS"
echo "JOB=$JOB"
