#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_TRADE_METHOD_CONSUMER_WORKTREE:-/tmp/q4r3-exact25-trade-method-consumer-proof}
BRANCH=q4r3-exact25-trade-method-lineage-observer
PYTHON_BIN=$ROOT/.venv/bin/python

SOURCE_TOOL=$WORKTREE/tools/q4r3_exact25_trade_method_consumer_proof_audit.py
SOURCE_SSOT=$WORKTREE/backend/config/q4r3_exact25_trade_method_consumer_proof_ssot_v1.json
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_trade_method_consumer_proof_audit.py
ACTIVE_TOOL=$ROOT/tools/q4r3_exact25_trade_method_consumer_proof_audit.py
ACTIVE_SSOT=$ROOT/backend/config/q4r3_exact25_trade_method_consumer_proof_ssot_v1.json

MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
WRITER_STATUS=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/status_latest.json
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service

OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/trade_method_consumer_proof
CONSUMER_AUDIT=$OUTPUT_ROOT/consumer_audit_latest.json
MAPPING_INVENTORY=$OUTPUT_ROOT/mapping_inventory_latest.json
RUNTIME_LINKAGE=$OUTPUT_ROOT/runtime_linkage_latest.json
VIOLATIONS=$OUTPUT_ROOT/violations_latest.json
STATUS=$OUTPUT_ROOT/status_latest.json

SERVICE_NAME=q4r3-exact25-trade-method-consumer-proof.service
TIMER_NAME=q4r3-exact25-trade-method-consumer-proof.timer
SERVICE_PATH=/etc/systemd/system/$SERVICE_NAME
TIMER_PATH=/etc/systemd/system/$TIMER_NAME

JOB_STATUS=$ROOT/runtime/q4r3_exact25_trade_method_consumer_proof_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_trade_method_consumer_proof_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_trade_method_consumer_proof
RESULT=$RESULT_DIR/q4r3_exact25_trade_method_consumer_proof_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_trade_method_consumer_proof_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
MUTATION_STARTED=false
ROLLBACK_DONE=false

[ "$(id -u)" -eq 0 ] || { echo RUN_AS_ROOT >&2; exit 1; }
mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1 reason=$2 report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" \
    "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$BACKUP_DIR" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]);r=Path(sys.argv[7])
x={
 "job":"q4r3_exact25_trade_method_consumer_proof","state":sys.argv[2],"reason":sys.argv[3],
 "started_at":sys.argv[4],"updated_at":datetime.now(timezone.utc).isoformat(),"branch":sys.argv[5],
 "report_commit":sys.argv[6] or None,"result_path":str(r),"result_exists":r.exists() and r.stat().st_size>0,
 "current_stage":sys.argv[8],"log_path":sys.argv[9],"backup_dir":sys.argv[10],"action":"hold",
 "strategy_modified":False,"trade_method_modified":False,"producer_modified":False,"writer_modified":False,
 "formal_ledger_modified_by_job":False,"historical_backfill_performed":False,
 "paper_enabled":False,"live_enabled":False,"order_enabled":False,
 "order_authority":"blocked","execution_authority":"none"
}
if x["result_exists"]:
 try:x.update(json.loads(r.read_text(encoding="utf-8")))
 except Exception as e:x["result_read_error"]=f"{type(e).__name__}:{e}"
t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8");t.replace(p)
PY
}
set_stage(){ CURRENT_STAGE=$1; write_job_status RUNNING "stage=$CURRENT_STAGE"; echo "=== STAGE: $CURRENT_STAGE ==="; }
backup_path(){ local src=$1 key=$2; mkdir -p "$BACKUP_DIR/items"; if [ -e "$src" ]; then cp -a "$src" "$BACKUP_DIR/items/$key"; echo true > "$BACKUP_DIR/$key.existed"; else echo false > "$BACKUP_DIR/$key.existed"; fi; }
restore_path(){ local dst=$1 key=$2; rm -rf "$dst"; if [ "$(cat "$BACKUP_DIR/$key.existed" 2>/dev/null || echo false)" = true ]; then mkdir -p "$(dirname "$dst")"; cp -a "$BACKUP_DIR/items/$key" "$dst"; fi; }
rollback(){
 [ "$ROLLBACK_DONE" = true ] && return 0; ROLLBACK_DONE=true; trap - ERR
 [ "$MUTATION_STARTED" = true ] || return 0
 systemctl stop "$TIMER_NAME" "$SERVICE_NAME" 2>/dev/null || true
 restore_path "$ACTIVE_TOOL" active_tool; restore_path "$ACTIVE_SSOT" active_ssot
 restore_path "$SERVICE_PATH" service; restore_path "$TIMER_PATH" timer; restore_path "$OUTPUT_ROOT" output_root
 systemctl daemon-reload || true
 [ "$(cat "$BACKUP_DIR/timer_active" 2>/dev/null || echo false)" = true ] && systemctl start "$TIMER_NAME" 2>/dev/null || true
}
on_error(){ local code=$? failed=$CURRENT_STAGE; rollback || true; CURRENT_STAGE=$failed; write_job_status FAILED "stage=$failed exit_code=$code rollback=true" || true; echo "Q4R3_EXACT25_TRADE_METHOD_CONSUMER_PROOF_FAILED stage=$failed exit_code=$code" >&2; exit "$code"; }
trap on_error ERR

for f in "$PYTHON_BIN" "$SOURCE_TOOL" "$SOURCE_SSOT" "$TEST_FILE" "$MANIFEST" "$PRODUCER_STATUS" "$WRITER_STATUS" "$FORMAL_LEDGER"; do
 [ -e "$f" ] || { CURRENT_STAGE=required_input_check; echo "REQUIRED_INPUT_MISSING:$f" >&2; exit 2; }
done

set_stage preflight_compile_and_tests
cd "$WORKTREE"
find "$WORKTREE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
export PYTHONPATH="$WORKTREE" PYTHONDONTWRITEBYTECODE=1
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_TOOL"
"$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_source_safety_gate
systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
[ "$PRODUCER_PID_BEFORE" != 0 ] && [ "$WRITER_PID_BEFORE" != 0 ]
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
"$PYTHON_BIN" - "$PRODUCER_STATUS" "$WRITER_STATUS" <<'PY'
import json,sys
from pathlib import Path
for p,n in ((Path(sys.argv[1]),"producer"),(Path(sys.argv[2]),"writer")):
 x=json.loads(p.read_text(encoding="utf-8"))
 if x.get("state")!="RUNNING":raise SystemExit(f"{n.upper()}_NOT_RUNNING:{x.get('state')}")
 for k in ("paper_enabled","live_enabled","order_enabled"):
  if x.get(k) not in (False,None):raise SystemExit(f"UNSAFE_{n.upper()}:{k}={x.get(k)}")
PY

set_stage backup_observer_surfaces
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$TIMER_NAME"; then echo true > "$BACKUP_DIR/timer_active"; else echo false > "$BACKUP_DIR/timer_active"; fi
backup_path "$ACTIVE_TOOL" active_tool; backup_path "$ACTIVE_SSOT" active_ssot
backup_path "$SERVICE_PATH" service; backup_path "$TIMER_PATH" timer; backup_path "$OUTPUT_ROOT" output_root
MUTATION_STARTED=true

set_stage install_readonly_consumer_proof_audit
systemctl stop "$TIMER_NAME" "$SERVICE_NAME" 2>/dev/null || true
install -m 0755 "$SOURCE_TOOL" "$ACTIVE_TOOL.tmp"; mv -f "$ACTIVE_TOOL.tmp" "$ACTIVE_TOOL"
install -m 0644 "$SOURCE_SSOT" "$ACTIVE_SSOT.tmp"; mv -f "$ACTIVE_SSOT.tmp" "$ACTIVE_SSOT"
mkdir -p "$OUTPUT_ROOT"; chmod 0750 "$OUTPUT_ROOT"
cat > "$SERVICE_PATH.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Trade Method Consumer and Runtime Proof Audit
After=$PRODUCER_UNIT $WRITER_UNIT
Requires=$PRODUCER_UNIT $WRITER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_TOOL --root $ROOT --ledger $FORMAL_LEDGER --manifest $MANIFEST --ssot $ACTIVE_SSOT --output-root $OUTPUT_ROOT --consumer-audit $CONSUMER_AUDIT --mapping-inventory $MAPPING_INVENTORY --runtime-linkage $RUNTIME_LINKAGE --violations $VIOLATIONS --status $STATUS
Nice=19
IOSchedulingClass=idle
CPUQuota=25%
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$ROOT/backend $ROOT/tools $ROOT/runtime $ACTIVE_SSOT
ReadWritePaths=$OUTPUT_ROOT
EOF
install -m 0644 "$SERVICE_PATH.tmp" "$SERVICE_PATH"; rm -f "$SERVICE_PATH.tmp"
cat > "$TIMER_PATH.tmp" <<EOF
[Unit]
Description=Run Q4R3 Exact25 Trade Method Consumer Proof Every Five Minutes

[Timer]
OnBootSec=75
OnUnitActiveSec=300
AccuracySec=10
Persistent=true
Unit=$SERVICE_NAME

[Install]
WantedBy=timers.target
EOF
install -m 0644 "$TIMER_PATH.tmp" "$TIMER_PATH"; rm -f "$TIMER_PATH.tmp"
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
for f in "$CONSUMER_AUDIT" "$MAPPING_INVENTORY" "$RUNTIME_LINKAGE" "$VIOLATIONS" "$STATUS"; do [ -s "$f" ]; done

"$PYTHON_BIN" - "$STATUS" "$VIOLATIONS" "$RESULT" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$WRITER_PID_BEFORE" "$WRITER_PID_AFTER" "$FORMAL_HASH_BEFORE" "$FORMAL_HASH_AFTER" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
s=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"));v=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for k in ("strategy_mutation_allowed","trade_method_mutation_allowed","producer_mutation_allowed","writer_mutation_allowed","formal_ledger_mutation_allowed","historical_backfill_allowed","filter_enabled","comparison_decision_enabled","promotion_enabled","paper_enabled","live_enabled","order_enabled"):
 if s.get(k) is not False:raise SystemExit(f"UNSAFE_STATUS_FLAG:{k}={s.get(k)}")
r={
 "schema":"q4r3_exact25_trade_method_consumer_proof_job_result_v1","status":"PASS",
 "verdict":"TRADE_METHOD_CONSUMER_PROOF_AUDIT_INSTALLED","observer_state":s.get("state"),
 "observer_verdict":s.get("verdict"),"next_action":s.get("next_action"),
 "generated_at":datetime.now(timezone.utc).isoformat(),"formal_ledger_row_count":s.get("formal_ledger_row_count"),
 "resolver_candidate_count":s.get("resolver_candidate_count"),"consumer_proof_state":s.get("consumer_proof_state"),
 "mapped_strategy_count":s.get("mapped_strategy_count"),"manifest_strategy_count":s.get("manifest_strategy_count"),
 "runtime_exact_linked_count":s.get("runtime_exact_linked_count"),"runtime_exact_linked_pct":s.get("runtime_exact_linked_pct"),
 "violation_count":v.get("count"),"violation_severity":v.get("severity"),"timer_active":True,
 "producer_pid_unchanged":sys.argv[4]==sys.argv[5],"writer_pid_unchanged":sys.argv[6]==sys.argv[7],
 "formal_ledger_hash_unchanged":sys.argv[8]==sys.argv[9],"strategy_modified":False,"trade_method_modified":False,
 "producer_modified":False,"writer_modified":False,"formal_ledger_modified_by_job":False,"historical_backfill_performed":False,
 "paper_enabled":False,"live_enabled":False,"order_enabled":False,"order_authority":"blocked","execution_authority":"none",
 "observer_only":True,"action":"hold","rollback_available":True
}
p=Path(sys.argv[3]);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(r,ensure_ascii=False,sort_keys=True))
PY

set_stage publish_sanitized_result
cd "$WORKTREE"
git add "$RESULT"
if ! git diff --cached --quiet; then
 git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" commit -m "Record Exact25 trade-method consumer proof result"
 git push origin HEAD:"$BRANCH"
fi
REPORT_COMMIT=$(git rev-parse HEAD)
CURRENT_STAGE=complete
write_job_status PASS published "$REPORT_COMMIT"
trap - ERR
echo "Q4R3_EXACT25_TRADE_METHOD_CONSUMER_PROOF_PASS commit=$REPORT_COMMIT"
