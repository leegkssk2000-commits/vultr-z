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
CHECKPOINT_TIMER=q4r3-exact25-100c-checkpoint-observer.timer
INTEGRITY_TIMER=q4r3-exact25-pre100-integrity-audit.timer
UNIT=q4r3-exact25-auto-progress-200c-observer

LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"
CHECKPOINT_STATUS="$ROOT/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json"
INTEGRITY_STATUS="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit/status_latest.json"
TRIGGER_STATUS="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer/status_latest.json"
PROJECTION_STATUS="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer/status_latest.json"
PAIR_STATUS="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer/status_latest.json"
RISK_STATUS="$ROOT/runtime/exact25_edge_v1/risk_scenario_grid_observer/status_latest.json"
SCOREBOARD_STATUS="$ROOT/runtime/exact25_edge_v1/method_scoreboard_observer/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_auto_progress_200c_observer.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/auto_progress_200c_observer"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
SNAPSHOT_100="$OUTDIR/checkpoint_100c_snapshot.json"
SNAPSHOT_200="$OUTDIR/checkpoint_200c_snapshot.json"
JOB="$ROOT/runtime/q4r3_exact25_auto_progress_200c_observer_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_auto_progress_200c_observer.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_auto_progress_200c_observer.py"

REQUIRED=(
  "$SOURCE_SCRIPT" "$TEST_FILE" "$LEDGER" "$STORAGE_STATUS"
  "$CHECKPOINT_STATUS" "$INTEGRITY_STATUS" "$TRIGGER_STATUS"
  "$PROJECTION_STATUS" "$PAIR_STATUS" "$RISK_STATUS" "$SCOREBOARD_STATUS"
)
for required in "${REQUIRED[@]}"; do
  [[ -s "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

for unit in \
  "$PRODUCER_UNIT" "$WRITER_UNIT" "$TRIGGER_TIMER" "$PROJECTION_TIMER" \
  "$PAIR_TIMER" "$RISK_TIMER" "$SCOREBOARD_TIMER" "$CHECKPOINT_TIMER" "$INTEGRITY_TIMER"; do
  systemctl is-active --quiet "$unit" || { echo "REQUIRED_UNIT_INACTIVE=$unit"; exit 1; }
done

AVAILABLE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
(( AVAILABLE_KB >= 4194304 )) || { echo "INSUFFICIENT_FREE_SPACE_KB=$AVAILABLE_KB"; exit 1; }

"$PY" - "$STORAGE_STATUS" "$INTEGRITY_STATUS" "$CHECKPOINT_STATUS" <<'PY'
import json, sys
storage=json.load(open(sys.argv[1],encoding='utf-8'))
integrity=json.load(open(sys.argv[2],encoding='utf-8'))
checkpoint=json.load(open(sys.argv[3],encoding='utf-8'))
assert storage.get('state')=='PASS', storage
assert storage.get('verdict')=='STORAGE_REGROWTH_GUARD_HEALTHY', storage
assert integrity.get('state')=='PASS', integrity
assert integrity.get('critical_count')==0, integrity
assert integrity.get('major_count')==0, integrity
assert integrity.get('integrity_gate_locked') is False, integrity
assert checkpoint.get('state')=='PASS', checkpoint
assert checkpoint.get('target_closed_count')==100, checkpoint
print('PREFLIGHT_CONTRACT=PASS')
PY

PROTECTED=(
  "$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
  "$ROOT/backend/engine/skill_resolver.py"
  "$ROOT/backend/trade_methods/policy.py"
  "$ROOT/backend/trade_methods/profiles.py"
  "$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py"
)
for path in "${PROTECTED[@]}"; do
  [[ -f "$path" ]] || { echo "PROTECTED_INPUT_MISSING=$path"; exit 1; }
done

PRODUCER_PID_BEFORE="$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)"
WRITER_PID_BEFORE="$(systemctl show "$WRITER_UNIT" -p MainPID --value)"
PROTECTED_HASH_BEFORE="$(sha256sum "${PROTECTED[@]}")"
LEDGER_ROWS_BEFORE="$(awk 'NF{n++} END{print n+0}' "$LEDGER")"
LEDGER_PREFIX_HASH_BEFORE="$(awk 'NF{print}' "$LEDGER" | head -n "$LEDGER_ROWS_BEFORE" | sha256sum | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Automatic Progress Observer Through 200C
After=$INTEGRITY_TIMER $CHECKPOINT_TIMER $SCOREBOARD_TIMER $RISK_TIMER $PAIR_TIMER $PROJECTION_TIMER $TRIGGER_TIMER $PRODUCER_UNIT $WRITER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --formal-ledger $LEDGER --storage-status $STORAGE_STATUS --checkpoint-100-status $CHECKPOINT_STATUS --integrity-status $INTEGRITY_STATUS --trigger-status $TRIGGER_STATUS --projection-status $PROJECTION_STATUS --pair-status $PAIR_STATUS --risk-status $RISK_STATUS --scoreboard-status $SCOREBOARD_STATUS --snapshot-100 $SNAPSHOT_100 --snapshot-200 $SNAPSHOT_200 --status $STATUS --violations $VIOLATIONS
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
Description=Q4R3 Exact25 Automatic Progress Timer Through 200C

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
PROTECTED_HASH_AFTER="$(sha256sum "${PROTECTED[@]}")"
LEDGER_ROWS_AFTER="$(awk 'NF{n++} END{print n+0}' "$LEDGER")"
LEDGER_PREFIX_HASH_AFTER="$(awk 'NF{print}' "$LEDGER" | head -n "$LEDGER_ROWS_BEFORE" | sha256sum | awk '{print $1}')"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$PROTECTED_HASH_BEFORE" = "$PROTECTED_HASH_AFTER"
(( LEDGER_ROWS_AFTER >= LEDGER_ROWS_BEFORE ))
test "$LEDGER_PREFIX_HASH_BEFORE" = "$LEDGER_PREFIX_HASH_AFTER"
systemctl is-active --quiet "$UNIT.timer"

"$PY" - "$STATUS" "$VIOLATIONS" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status=json.load(open(sys.argv[1],encoding='utf-8'))
violations=json.load(open(sys.argv[2],encoding='utf-8'))
assert status.get('state')=='PASS', status
assert status.get('automatic_progress_enabled') is True, status
assert status.get('target_100c')==100, status
assert status.get('target_200c')==200, status
assert status.get('producer_stop_at_100c') is False, status
assert status.get('producer_stop_at_200c') is False, status
assert status.get('observer_only') is True, status
assert status.get('formal_ledger_modified') is False, status
assert violations.get('count')==0, violations
payload={
  'job':'q4r3_exact25_auto_progress_200c_observer',
  'state':'PASS',
  'current_stage':'complete',
  'status':'PASS_Q4R3_EXACT25_AUTO_PROGRESS_200C_OBSERVER_INSTALLED',
  'verdict':status.get('verdict'),
  'updated_at':datetime.now(timezone.utc).isoformat(),
  'stage':status.get('stage'),
  'current_closed_count':status.get('current_closed_count'),
  'remaining_to_100c':status.get('remaining_to_100c'),
  'remaining_to_200c':status.get('remaining_to_200c'),
  'automatic_progress_enabled':True,
  'producer_stop_at_100c':False,
  'producer_stop_at_200c':False,
  'snapshot_100_ready':status.get('snapshot_100_ready'),
  'snapshot_200_ready':status.get('snapshot_200_ready'),
  'observer_only':True,
  'automatic_patch_allowed':False,
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

echo Q4R3_EXACT25_AUTO_PROGRESS_200C_OBSERVER_INSTALLED
echo "STATUS=$STATUS"
echo "VIOLATIONS=$VIOLATIONS"
echo "SNAPSHOT_100=$SNAPSHOT_100"
echo "SNAPSHOT_200=$SNAPSHOT_200"
echo "JOB=$JOB"
