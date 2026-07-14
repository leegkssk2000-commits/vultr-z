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
PAIR_TIMER=q4r3-exact25-future-pair-join-observer.timer
RISK_TIMER=q4r3-exact25-risk-scenario-grid-observer.timer
SCOREBOARD_TIMER=q4r3-exact25-method-scoreboard-observer.timer
UNIT=q4r3-exact25-100c-checkpoint-observer

LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
ACTIVATION="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/activation.json"
TRIGGER_STATUS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/status_latest.json"
PROJECTION_STATUS="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json"
PAIR_STATUS="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer/status_latest.json"
RISK_STATUS="$ROOT/runtime/exact25_edge_v1/risk_scenario_grid_observer/status_latest.json"
SCOREBOARD_STATUS="$ROOT/runtime/exact25_edge_v1/method_scoreboard_observer/status_latest.json"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_100c_checkpoint_observer.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/checkpoint_100c_observer"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_100c_checkpoint_observer_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_100c_checkpoint_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_100c_checkpoint_observer.py"

for required in "$SOURCE_SCRIPT" "$TEST_FILE" "$LEDGER" "$ACTIVATION" "$TRIGGER_STATUS" "$PROJECTION_STATUS" "$PAIR_STATUS" "$RISK_STATUS" "$SCOREBOARD_STATUS" "$STORAGE_STATUS"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

for unit in "$PRODUCER_UNIT" "$WRITER_UNIT" "$TRIGGER_TIMER" "$PROJECTION_TIMER" "$PAIR_TIMER" "$RISK_TIMER" "$SCOREBOARD_TIMER"; do
  systemctl is-active --quiet "$unit"
done

"$PY" - "$STORAGE_STATUS" "$SCOREBOARD_STATUS" <<'PY'
import json, sys
storage=json.load(open(sys.argv[1],encoding='utf-8'))
score=json.load(open(sys.argv[2],encoding='utf-8'))
assert storage.get('state')=='PASS', storage
assert storage.get('verdict')=='STORAGE_REGROWTH_GUARD_HEALTHY', storage
assert score.get('state')=='PASS', score
assert score.get('method_count')==6, score
assert score.get('observer_only') is True, score
print('PREFLIGHT_CONTRACT=PASS')
PY

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
LEDGER_HASH_BEFORE="$(sha256sum "$LEDGER" | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Read-Only 100C Checkpoint Observer
After=$SCOREBOARD_TIMER $RISK_TIMER $PAIR_TIMER
Requires=$SCOREBOARD_TIMER $RISK_TIMER $PAIR_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --formal-ledger $LEDGER --activation $ACTIVATION --trigger-status $TRIGGER_STATUS --projection-status $PROJECTION_STATUS --pair-status $PAIR_STATUS --risk-status $RISK_STATUS --scoreboard-status $SCOREBOARD_STATUS --status $STATUS --violations $VIOLATIONS
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
Description=Q4R3 Exact25 100C Checkpoint Timer

[Timer]
OnBootSec=150s
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
assert status.get('target_closed_count')==100, status
assert status.get('observer_only') is True, status
assert status.get('formal_ledger_modified') is False, status
assert violations.get('count')==0, violations
payload={
  'job':'q4r3_exact25_100c_checkpoint_observer',
  'state':'PASS',
  'current_stage':'complete',
  'status':'PASS_Q4R3_EXACT25_100C_CHECKPOINT_OBSERVER',
  'verdict':status.get('verdict'),
  'updated_at':datetime.now(timezone.utc).isoformat(),
  'target_closed_count':status.get('target_closed_count'),
  'current_closed_count':status.get('current_closed_count'),
  'remaining_closed_count':status.get('remaining_closed_count'),
  'checkpoint_reached':status.get('checkpoint_reached'),
  'observer_only':True,
  'deep_audit_enabled':False,
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

echo Q4R3_EXACT25_100C_CHECKPOINT_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "VIOLATIONS=$VIOLATIONS"
echo "JOB=$JOB"
