#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_PREENTRY_CONTEXT_WORKTREE:-/tmp/q4r3-exact25-preentry-method-context-capture}
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_SCRIPT=$WORKTREE/tools/q4r3_exact25_preentry_method_context_capture.py
ACTIVE_SCRIPT=$ROOT/tools/q4r3_exact25_preentry_method_context_capture.py

PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service
PRODUCER_ROOT=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer
OPEN_POSITIONS=$PRODUCER_ROOT/open_positions_latest.json
PRODUCER_STATE=$PRODUCER_ROOT/state.json
FORMAL_LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
ACTIVE_METHOD_ROOT=$ROOT/backend/trade_methods

OUTPUT_ROOT=$ROOT/runtime/exact25_edge_v1/preentry_method_context
ACTIVATION=$OUTPUT_ROOT/activation.json
CAPTURE_LEDGER=$OUTPUT_ROOT/context.jsonl
STATUS=$OUTPUT_ROOT/status_latest.json
EXECUTION_CONTRACT=$OUTPUT_ROOT/producer_execution_contract.json
EXECSTART_CAPTURE=$OUTPUT_ROOT/producer_execstart.txt

UNIT_NAME=q4r3-exact25-preentry-method-context-capture.service
TIMER_NAME=q4r3-exact25-preentry-method-context-capture.timer
UNIT_PATH=/etc/systemd/system/$UNIT_NAME
TIMER_PATH=/etc/systemd/system/$TIMER_NAME

JOB_STATUS=$ROOT/runtime/q4r3_exact25_preentry_method_context_capture_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_preentry_method_context_capture_job.log
BACKUP=$ROOT/runtime/q4r3_exact25_preentry_method_context_capture_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)

exec > >(tee -a "$LOG") 2>&1

MARKET_CONTEXT=
for candidate in \
  "$ROOT/runtime/exact25_edge_v1/six_layer_observer_suite/market_context_snapshots.jsonl" \
  "$ROOT/runtime/exact25_edge_v1/market_context_observer/market_context_snapshots.jsonl"
do
  if [ -s "$candidate" ]; then
    MARKET_CONTEXT=$candidate
    break
  fi
done

write_failure() {
  local stage=$1
  local reason=$2
  "$PYTHON_BIN" - "$JOB_STATUS" "$stage" "$reason" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
path=Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps({
  "job":"q4r3_exact25_preentry_method_context_capture",
  "state":"FAILED","current_stage":sys.argv[2],"reason":sys.argv[3],
  "updated_at":datetime.now(timezone.utc).isoformat(),"action":"hold",
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none"
},ensure_ascii=False,indent=2),encoding="utf-8")
PY
}

backup_path() {
  local path=$1
  local name=$2
  if [ -e "$path" ]; then
    cp -a "$path" "$BACKUP/$name"
    printf true > "$BACKUP/$name.existed"
  else
    printf false > "$BACKUP/$name.existed"
  fi
}

restore_path() {
  local path=$1
  local name=$2
  if [ "$(cat "$BACKUP/$name.existed" 2>/dev/null || echo false)" = true ]; then
    mkdir -p "$(dirname "$path")"
    cp -a "$BACKUP/$name" "$path"
  else
    rm -f "$path"
  fi
}

rollback() {
  local reason=${1:-UNKNOWN}
  trap - ERR
  systemctl stop "$TIMER_NAME" 2>/dev/null || true
  systemctl stop "$UNIT_NAME" 2>/dev/null || true
  restore_path "$ACTIVE_SCRIPT" active_script
  restore_path "$UNIT_PATH" unit
  restore_path "$TIMER_PATH" timer
  restore_path "$ACTIVATION" activation
  restore_path "$CAPTURE_LEDGER" capture_ledger
  restore_path "$STATUS" status
  restore_path "$EXECUTION_CONTRACT" execution_contract
  restore_path "$EXECSTART_CAPTURE" execstart_capture
  systemctl daemon-reload || true
  write_failure rollback "$reason rollback=true"
  echo ROLLBACK_COMPLETE
  exit 1
}

trap 'rollback "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || { write_failure preflight RUN_AS_ROOT; exit 1; }
for required in "$WORKTREE" "$PYTHON_BIN" "$SOURCE_SCRIPT" "$OPEN_POSITIONS" "$PRODUCER_STATE" "$FORMAL_LEDGER"; do
  [ -e "$required" ] || { write_failure preflight "REQUIRED_INPUT_MISSING:$required"; exit 1; }
done
[ -n "$MARKET_CONTEXT" ] || { write_failure preflight MARKET_CONTEXT_INPUT_MISSING; exit 1; }
systemctl is-active --quiet "$PRODUCER_UNIT"
systemctl is-active --quiet "$WRITER_UNIT"

mkdir -p "$BACKUP" "$OUTPUT_ROOT" "$ROOT/tools"
for spec in \
  "$ACTIVE_SCRIPT:active_script" \
  "$UNIT_PATH:unit" \
  "$TIMER_PATH:timer" \
  "$ACTIVATION:activation" \
  "$CAPTURE_LEDGER:capture_ledger" \
  "$STATUS:status" \
  "$EXECUTION_CONTRACT:execution_contract" \
  "$EXECSTART_CAPTURE:execstart_capture"
do
  backup_path "${spec%%:*}" "${spec##*:}"
done

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_BEFORE=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_BEFORE=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_METHOD_HASH_BEFORE=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

"$PYTHON_BIN" - "$JOB_STATUS" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({
  "job":"q4r3_exact25_preentry_method_context_capture","state":"RUNNING",
  "current_stage":"install_future_only_capture","updated_at":datetime.now(timezone.utc).isoformat(),
  "action":"hold"
},indent=2),encoding="utf-8")
PY

install -m 0755 "$SOURCE_SCRIPT" "$ACTIVE_SCRIPT"
"$PYTHON_BIN" -m py_compile "$ACTIVE_SCRIPT"
"$PYTHON_BIN" "$ACTIVE_SCRIPT" --self-test

systemctl show "$PRODUCER_UNIT" -p ExecStart --value > "$EXECSTART_CAPTURE.tmp"
mv -f "$EXECSTART_CAPTURE.tmp" "$EXECSTART_CAPTURE"

"$PYTHON_BIN" - "$EXECSTART_CAPTURE" "$EXECUTION_CONTRACT" <<'PY'
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
raw=Path(sys.argv[1]).read_text(encoding="utf-8",errors="replace")
def number(flag):
    m=re.search(rf"{re.escape(flag)}(?:=|\s+)([-+]?[0-9]*\.?[0-9]+)",raw)
    return float(m.group(1)) if m else None
fee=number("--fee-rate")
slippage=number("--slippage-bps")
payload={
  "schema":"q4r3_exact25_producer_execution_contract_v1",
  "captured_at":datetime.now(timezone.utc).isoformat(),
  "fee_rate_per_leg":fee,
  "fee_bps_round_trip":fee*20000.0 if fee is not None else None,
  "slippage_bps_per_leg":slippage,
  "slippage_bps_round_trip":slippage*2.0 if slippage is not None else None,
  "interpretation":{"fee":"producer_fee_rate_per_leg_x2","slippage":"producer_slippage_bps_per_leg_x2"},
  "source":"systemd_execstart","observer_only":True
}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
PY

if [ ! -s "$ACTIVATION" ]; then
  "$PYTHON_BIN" - "$ACTIVATION" "$FORMAL_HASH_BEFORE" "$FORMAL_ROWS_BEFORE" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
now=datetime.now(timezone.utc)
payload={
  "schema":"q4r3_exact25_preentry_method_context_activation_v1",
  "activation_at":now.isoformat(),"activation_epoch":now.timestamp(),
  "formal_baseline_hash":sys.argv[2],"formal_baseline_rows":int(sys.argv[3]),
  "historical_backfill_allowed":False,"pre_activation_rows_frozen":True,
  "method_neutral_capture":True,"strategy_method_mapping_applied":False,
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none"
}
Path(sys.argv[1]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
PY
else
  "$PYTHON_BIN" - "$ACTIVATION" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert d.get("historical_backfill_allowed") is False
assert d.get("method_neutral_capture") is True
PY
fi

touch "$CAPTURE_LEDGER"
chmod 0644 "$ACTIVATION" "$CAPTURE_LEDGER" "$EXECUTION_CONTRACT" "$EXECSTART_CAPTURE"

cat > "$UNIT_PATH.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Future-Only Pre-entry Method Context Capture
After=$PRODUCER_UNIT $WRITER_UNIT
Requires=$PRODUCER_UNIT $WRITER_UNIT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON_BIN $ACTIVE_SCRIPT --activation $ACTIVATION --execution-contract $EXECUTION_CONTRACT --open-positions $OPEN_POSITIONS --producer-state $PRODUCER_STATE --market-context $MARKET_CONTEXT --ledger $CAPTURE_LEDGER --status $STATUS
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadOnlyPaths=$OPEN_POSITIONS
ReadOnlyPaths=$PRODUCER_STATE
ReadOnlyPaths=$MARKET_CONTEXT
ReadOnlyPaths=$ACTIVATION
ReadOnlyPaths=$EXECUTION_CONTRACT
ReadWritePaths=$OUTPUT_ROOT
EOF
install -m 0644 "$UNIT_PATH.tmp" "$UNIT_PATH"
rm -f "$UNIT_PATH.tmp"

cat > "$TIMER_PATH.tmp" <<EOF
[Unit]
Description=Run Exact25 Pre-entry Method Context Capture Every 2 Seconds

[Timer]
OnBootSec=2s
OnUnitActiveSec=2s
AccuracySec=1s
Persistent=false
Unit=$UNIT_NAME

[Install]
WantedBy=timers.target
EOF
install -m 0644 "$TIMER_PATH.tmp" "$TIMER_PATH"
rm -f "$TIMER_PATH.tmp"

systemctl daemon-reload
systemctl enable --now "$TIMER_NAME"
systemctl start "$UNIT_NAME"
sleep 3
systemctl is-active --quiet "$TIMER_NAME"

"$PYTHON_BIN" - "$STATUS" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert d.get("state") == "HEALTHY", d
assert d.get("method_neutral") is True, d
assert d.get("historical_backfill_allowed") is False, d
assert d.get("paper_enabled") is False, d
assert d.get("live_enabled") is False, d
assert d.get("order_enabled") is False, d
PY

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
FORMAL_HASH_AFTER=$(sha256sum "$FORMAL_LEDGER" | awk '{print $1}')
FORMAL_ROWS_AFTER=$(grep -cve '^[[:space:]]*$' "$FORMAL_LEDGER" || true)
ACTIVE_METHOD_HASH_AFTER=$(find "$ACTIVE_METHOD_ROOT" -maxdepth 1 -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || rollback PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || rollback WRITER_PID_CHANGED
[ "$ACTIVE_METHOD_HASH_BEFORE" = "$ACTIVE_METHOD_HASH_AFTER" ] || rollback ACTIVE_TRADE_METHOD_SOURCE_CHANGED
[ "$FORMAL_ROWS_AFTER" -ge "$FORMAL_ROWS_BEFORE" ] || rollback FORMAL_LEDGER_ROW_COUNT_DECREASED

FORMAL_HASH_UNCHANGED=false
FORMAL_EXTERNAL_APPEND=false
if [ "$FORMAL_HASH_BEFORE" = "$FORMAL_HASH_AFTER" ]; then
  FORMAL_HASH_UNCHANGED=true
elif [ "$FORMAL_ROWS_AFTER" -gt "$FORMAL_ROWS_BEFORE" ]; then
  FORMAL_EXTERNAL_APPEND=true
else
  rollback FORMAL_LEDGER_CHANGED_WITHOUT_APPEND
fi

"$PYTHON_BIN" - "$STATUS" "$JOB_STATUS" "$FORMAL_HASH_UNCHANGED" "$FORMAL_EXTERNAL_APPEND" "$FORMAL_ROWS_BEFORE" "$FORMAL_ROWS_AFTER" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
status=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload={
  "job":"q4r3_exact25_preentry_method_context_capture","state":"PASS","current_stage":"complete",
  "status":"PASS_Q4R3_EXACT25_PREENTRY_METHOD_CONTEXT_CAPTURE","verdict":status.get("verdict"),
  "updated_at":datetime.now(timezone.utc).isoformat(),"formal_baseline_rows":status.get("formal_baseline_rows"),
  "capture_count":status.get("capture_count"),"market_context_join_count":status.get("market_context_join_count"),
  "method_neutral":True,"historical_backfill_allowed":False,
  "producer_pid_unchanged":True,"writer_pid_unchanged":True,
  "formal_ledger_hash_unchanged":sys.argv[3].lower()=="true",
  "formal_ledger_external_append_detected":sys.argv[4].lower()=="true",
  "formal_ledger_rows_before":int(sys.argv[5]),"formal_ledger_rows_after":int(sys.argv[6]),
  "formal_ledger_not_modified_by_job":True,"active_trade_method_hash_unchanged":True,
  "strategy_modified":False,"trade_method_modified":False,"producer_modified":False,
  "writer_modified":False,"formal_ledger_modified_by_job":False,
  "paper_enabled":False,"live_enabled":False,"order_enabled":False,
  "order_authority":"blocked","execution_authority":"none","action":"hold",
  "next_action":status.get("next_action")
}
Path(sys.argv[2]).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
print("Q4R3_EXACT25_PREENTRY_METHOD_CONTEXT_CAPTURE_PASS")
PY

trap - ERR
echo Q4R3_EXACT25_PREENTRY_METHOD_CONTEXT_CAPTURE_INSTALL_PASS
