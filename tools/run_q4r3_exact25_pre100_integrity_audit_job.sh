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
UNIT=q4r3-exact25-pre100-integrity-audit

STATIC_AUDIT="$ROOT/runtime/exact25_edge_v1/skill_active_lineage_audit/q4r3_exact25_skill_active_lineage_audit_latest.json"
STORAGE_STATUS="$ROOT/runtime/q4r3_storage_regrowth_guard/status_latest.json"
TRIGGER_ROOT="$ROOT/runtime/exact25_edge_v1/skill_trigger_lineage_observer"
ACTIVATION="$TRIGGER_ROOT/activation.json"
SKILL_EVENTS="$TRIGGER_ROOT/skill_events.jsonl"
TRIGGER_STATUS="$TRIGGER_ROOT/status_latest.json"
COVERAGE="$TRIGGER_ROOT/coverage_latest.json"
OPEN_POSITIONS="$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/open_positions_latest.json"
LEDGER="$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
PROJECTION_ROOT="$ROOT/runtime/exact25_edge_v1/six_profile_projection_observer"
PROJECTION_STATUS="$PROJECTION_ROOT/status_latest.json"
PROJECTION="$PROJECTION_ROOT/projection_latest.json"
PAIR_ROOT="$ROOT/runtime/exact25_edge_v1/future_pair_join_observer"
PAIR_STATUS="$PAIR_ROOT/status_latest.json"
PAIRS_REPORT="$PAIR_ROOT/pairs_latest.json"
RISK_ROOT="$ROOT/runtime/exact25_edge_v1/risk_scenario_grid_observer"
RISK_STATUS="$RISK_ROOT/status_latest.json"
RISK_GRID="$RISK_ROOT/grid_latest.json"
SCOREBOARD_ROOT="$ROOT/runtime/exact25_edge_v1/method_scoreboard_observer"
SCOREBOARD_STATUS="$SCOREBOARD_ROOT/status_latest.json"
SCOREBOARD="$SCOREBOARD_ROOT/scoreboard_latest.json"
CHECKPOINT_STATUS="$ROOT/runtime/exact25_edge_v1/checkpoint_100c_observer/status_latest.json"

INSTALL_DIR="$ROOT/tools/q4r3_exact25_observers"
ACTIVE_SCRIPT="$INSTALL_DIR/q4r3_exact25_pre100_integrity_audit.py"
OUTDIR="$ROOT/runtime/exact25_edge_v1/pre100_integrity_audit"
STATUS="$OUTDIR/status_latest.json"
VIOLATIONS="$OUTDIR/violations_latest.json"
FIX_QUEUE="$OUTDIR/fix_queue_latest.json"
JOB="$ROOT/runtime/q4r3_exact25_pre100_integrity_audit_job_latest.json"

SOURCE_SCRIPT="$WT/tools/q4r3_exact25_pre100_integrity_audit.py"
TEST_FILE="$WT/tests/test_q4r3_exact25_pre100_integrity_audit.py"

REQUIRED=(
  "$SOURCE_SCRIPT" "$TEST_FILE" "$STATIC_AUDIT" "$STORAGE_STATUS"
  "$ACTIVATION" "$SKILL_EVENTS" "$TRIGGER_STATUS" "$COVERAGE"
  "$OPEN_POSITIONS" "$LEDGER" "$PROJECTION_STATUS" "$PROJECTION"
  "$PAIR_STATUS" "$PAIRS_REPORT" "$RISK_STATUS" "$RISK_GRID"
  "$SCOREBOARD_STATUS" "$SCOREBOARD" "$CHECKPOINT_STATUS"
)
for required in "${REQUIRED[@]}"; do
  [[ -e "$required" ]] || { echo "REQUIRED_INPUT_MISSING=$required"; exit 1; }
done

for unit in \
  "$PRODUCER_UNIT" "$WRITER_UNIT" "$TRIGGER_TIMER" "$PROJECTION_TIMER" \
  "$PAIR_TIMER" "$RISK_TIMER" "$SCOREBOARD_TIMER" "$CHECKPOINT_TIMER"; do
  systemctl is-active --quiet "$unit" || { echo "REQUIRED_UNIT_INACTIVE=$unit"; exit 1; }
done

AVAILABLE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
(( AVAILABLE_KB >= 4194304 )) || { echo "INSUFFICIENT_FREE_SPACE_KB=$AVAILABLE_KB"; exit 1; }

"$PY" - "$STATIC_AUDIT" "$STORAGE_STATUS" "$CHECKPOINT_STATUS" <<'PY'
import json, sys
static=json.load(open(sys.argv[1],encoding='utf-8'))
storage=json.load(open(sys.argv[2],encoding='utf-8'))
checkpoint=json.load(open(sys.argv[3],encoding='utf-8'))
assert static.get('state')=='PASS', static
assert str(static.get('verdict') or '').startswith('ACTIVE_IMPORT_CALL_SURFACE_PASS'), static
assert static.get('strategy_import_pass_count')==25, static
assert static.get('strategy_empty_call_pass_count')==25, static
assert static.get('method_declaration_count')==6, static
assert static.get('resolver_pass_count')==18, static
assert static.get('compatibility_matrix_rows')==2700, static
assert storage.get('state')=='PASS', storage
assert storage.get('verdict')=='STORAGE_REGROWTH_GUARD_HEALTHY', storage
assert checkpoint.get('state')=='PASS', checkpoint
assert checkpoint.get('target_closed_count')==100, checkpoint
print('PREFLIGHT_CONTRACT=PASS')
PY

PROTECTED=(
  "$ROOT/backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
  "$ROOT/backend/engine/skill_resolver.py"
  "$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
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
LEDGER_PREFIX_HASH_BEFORE="$(head -n "$LEDGER_ROWS_BEFORE" "$LEDGER" | sha256sum | awk '{print $1}')"

PYTHONPATH="$WT" "$PY" -m pytest -q "$TEST_FILE"
PYTHONPATH="$WT" "$PY" -m py_compile "$SOURCE_SCRIPT"

mkdir -p "$INSTALL_DIR" "$OUTDIR"
install -m 0555 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"

cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Q4R3 Exact25 Read-Only Pre-100C Integrity Audit
After=$CHECKPOINT_TIMER $SCOREBOARD_TIMER $RISK_TIMER $PAIR_TIMER $PROJECTION_TIMER $TRIGGER_TIMER
Requires=$CHECKPOINT_TIMER $SCOREBOARD_TIMER $RISK_TIMER $PAIR_TIMER $PROJECTION_TIMER $TRIGGER_TIMER

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PY $ACTIVE_SCRIPT --static-audit $STATIC_AUDIT --storage-status $STORAGE_STATUS --activation $ACTIVATION --formal-ledger $LEDGER --skill-events $SKILL_EVENTS --open-positions $OPEN_POSITIONS --trigger-status $TRIGGER_STATUS --coverage $COVERAGE --projection-status $PROJECTION_STATUS --projection $PROJECTION --pair-status $PAIR_STATUS --pairs-report $PAIRS_REPORT --risk-status $RISK_STATUS --risk-grid $RISK_GRID --scoreboard-status $SCOREBOARD_STATUS --scoreboard $SCOREBOARD --checkpoint-status $CHECKPOINT_STATUS --status $STATUS --violations $VIOLATIONS --fix-queue $FIX_QUEUE
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
Description=Q4R3 Exact25 Pre-100C Integrity Audit Timer

[Timer]
OnBootSec=165s
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
LEDGER_PREFIX_HASH_AFTER="$(head -n "$LEDGER_ROWS_BEFORE" "$LEDGER" | sha256sum | awk '{print $1}')"

test "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER"
test "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER"
test "$PROTECTED_HASH_BEFORE" = "$PROTECTED_HASH_AFTER"
(( LEDGER_ROWS_AFTER >= LEDGER_ROWS_BEFORE ))
test "$LEDGER_PREFIX_HASH_BEFORE" = "$LEDGER_PREFIX_HASH_AFTER"
systemctl is-active --quiet "$UNIT.timer"

"$PY" - "$STATUS" "$VIOLATIONS" "$FIX_QUEUE" "$JOB" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
status=json.load(open(sys.argv[1],encoding='utf-8'))
violations=json.load(open(sys.argv[2],encoding='utf-8'))
fix_queue=json.load(open(sys.argv[3],encoding='utf-8'))
assert status.get('state') in {'PASS','HOLD'}, status
assert status.get('observer_only') is True, status
assert status.get('formal_ledger_modified') is False, status
assert status.get('target_closed_count')==100, status
assert violations.get('count')==status.get('violation_count'), (violations,status)
assert fix_queue.get('automatic_patch_allowed') is False, fix_queue
payload={
  'job':'q4r3_exact25_pre100_integrity_audit',
  'state':'PASS',
  'current_stage':'complete',
  'status':'PASS_Q4R3_EXACT25_PRE100_INTEGRITY_AUDIT_INSTALLED',
  'audit_state':status.get('state'),
  'audit_verdict':status.get('verdict'),
  'updated_at':datetime.now(timezone.utc).isoformat(),
  'current_closed_count':status.get('current_closed_count'),
  'remaining_closed_count':status.get('remaining_closed_count'),
  'lineage_coverage_pct':status.get('lineage_coverage_pct'),
  'uncovered_close_count':status.get('uncovered_close_count'),
  'open_without_lineage_count':status.get('open_without_lineage_count'),
  'critical_count':status.get('critical_count'),
  'major_count':status.get('major_count'),
  'integrity_gate_locked':status.get('integrity_gate_locked'),
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
path=Path(sys.argv[4]); tmp=path.with_suffix(path.suffix+'.tmp')
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
os.replace(tmp,path)
PY

echo Q4R3_EXACT25_PRE100_INTEGRITY_AUDIT_INSTALLED
echo "STATUS=$STATUS"
echo "VIOLATIONS=$VIOLATIONS"
echo "FIX_QUEUE=$FIX_QUEUE"
echo "JOB=$JOB"
