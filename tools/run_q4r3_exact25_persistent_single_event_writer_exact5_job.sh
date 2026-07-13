#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_PERSISTENT_WRITER_WORKTREE:-/tmp/q4r3-exact25-persistent-single-event-writer-exact5}
BRANCH=q4r3-exact25-persistent-single-event-writer-exact5
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_ADAPTER=$WORKTREE/tools/q4r3_exact25_single_event_measurement_adapter.py
SOURCE_WRITER=$WORKTREE/tools/q4r3_exact25_persistent_single_event_writer.py
SOURCE_RESOLVER=$WORKTREE/tools/q4r3_exact5_symbol_ssot_resolver.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_persistent_single_event_writer_exact5.py
ACTIVE_ADAPTER=$ROOT/tools/q4r3_exact25_single_event_measurement_adapter.py
ACTIVE_WRITER=$ROOT/tools/q4r3_exact25_persistent_single_event_writer.py
MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
CANARY_STATUS=$ROOT/runtime/q4r3_exact25_single_event_writer_canary_job_latest.json
PRODUCER_UNIT_NAME=q4r3-exact25-shadow-producer.service
PRODUCER_ENV=/etc/default/q4r3-exact25-shadow-producer
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
CLOSE_SURFACE=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/close_latest.json
WRITER_UNIT_NAME=q4r3-exact25-persistent-single-event-writer.service
WRITER_UNIT=/etc/systemd/system/$WRITER_UNIT_NAME
WRITER_ENV=/etc/default/q4r3-exact25-persistent-single-event-writer
FORMAL_ROOT=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement
GATE=$FORMAL_ROOT/activation_gate.json
LEDGER=$FORMAL_ROOT/forward_r_ledger.jsonl
WRITER_STATUS=$FORMAL_ROOT/status_latest.json
RESOLUTION=$FORMAL_ROOT/exact5_resolution_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_persistent_single_event_writer_exact5_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_persistent_single_event_writer_exact5_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_persistent_single_event_writer_exact5
RESULT=$RESULT_DIR/q4r3_exact25_persistent_single_event_writer_exact5_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_persistent_single_event_writer_exact5_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
TRANSACTION_ID=$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
ROLLBACK_DONE=false
MUTATION_STARTED=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR" "$FORMAL_ROOT"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$BACKUP_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_persistent_single_event_writer_exact5",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "report_commit": sys.argv[6] or None,
    "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
    "current_stage": sys.argv[8],
    "log_path": sys.argv[9],
    "backup_dir": sys.argv[10],
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "binding_modified": False,
    "epoch_modified": False,
    "historical_backfill_allowed": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "exact5_resolved",
            "symbols", "writer_active", "writer_substate", "writer_main_pid",
            "writer_state", "writer_heartbeat_count", "measurement_start_at",
            "production_measurement_write_enabled", "producer_active",
            "producer_substate", "producer_processed_symbol_count", "ledger_row_count",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
tmp = status_path.with_suffix(status_path.suffix + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

set_stage() {
  CURRENT_STAGE=$1
  write_job_status RUNNING "stage=$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

backup_file() {
  local source=$1
  local key=$2
  mkdir -p "$BACKUP_DIR/files"
  if [ -e "$source" ]; then
    cp -a "$source" "$BACKUP_DIR/files/$key"
    echo true > "$BACKUP_DIR/$key.existed"
  else
    echo false > "$BACKUP_DIR/$key.existed"
  fi
}

restore_file() {
  local target=$1
  local key=$2
  if [ "$(cat "$BACKUP_DIR/$key.existed" 2>/dev/null || echo false)" = true ]; then
    mkdir -p "$(dirname "$target")"
    cp -a "$BACKUP_DIR/files/$key" "$target"
  else
    rm -f "$target"
  fi
}

rollback() {
  if [ "$ROLLBACK_DONE" = true ]; then return 0; fi
  ROLLBACK_DONE=true
  trap - ERR
  if [ "$MUTATION_STARTED" != true ]; then return 0; fi
  echo "=== ROLLBACK ==="
  systemctl stop "$WRITER_UNIT_NAME" 2>/dev/null || true
  systemctl stop "$PRODUCER_UNIT_NAME" 2>/dev/null || true
  restore_file "$ACTIVE_ADAPTER" active_adapter
  restore_file "$ACTIVE_WRITER" active_writer
  restore_file "$WRITER_ENV" writer_env
  restore_file "$WRITER_UNIT" writer_unit
  restore_file "$PRODUCER_ENV" producer_env
  restore_file "$GATE" gate
  restore_file "$LEDGER" ledger
  restore_file "$WRITER_STATUS" writer_status
  restore_file "$RESOLUTION" resolution
  systemctl daemon-reload || true
  if [ "$(cat "$BACKUP_DIR/producer_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$PRODUCER_UNIT_NAME" 2>/dev/null || true
  fi
  if [ "$(cat "$BACKUP_DIR/writer_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$WRITER_UNIT_NAME" 2>/dev/null || true
  fi
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_PERSISTENT_SINGLE_EVENT_WRITER_EXACT5_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" \
  "$SOURCE_ADAPTER" \
  "$SOURCE_WRITER" \
  "$SOURCE_RESOLVER" \
  "$TEST_FILE" \
  "$MANIFEST" \
  "$CANARY_STATUS" \
  "$PRODUCER_ENV" \
  "$PRODUCER_STATUS" \
  "$CLOSE_SURFACE"
do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_python_and_unit_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_ADAPTER" "$SOURCE_WRITER" "$SOURCE_RESOLVER"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage exact_one_canary_prerequisite_gate
"$PYTHON_BIN" - "$CANARY_STATUS" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "PASS_Q4R3_EXACT25_SINGLE_EVENT_WRITER_CANARY":
    raise SystemExit(f"SINGLE_EVENT_CANARY_NOT_PASS:{payload.get('status')}")
checks = {
    "accepted_count": 1,
    "duplicate_rejected_count": 1,
    "ledger_row_count": 1,
}
for key, expected in checks.items():
    if payload.get(key) != expected:
        raise SystemExit(f"CANARY_COUNT_MISMATCH:{key}:{payload.get(key)}")
for key in ("formula_verified", "owner_lineage_verified", "producer_pid_unchanged"):
    if payload.get(key) is not True:
        raise SystemExit(f"CANARY_VERIFICATION_FALSE:{key}")
if payload.get("producer_active") != "active":
    raise SystemExit("PRODUCER_NOT_ACTIVE_IN_CANARY_RESULT")
PY

set_stage resolve_exact5_symbol_ssot
rm -f "$RESOLUTION"
"$PYTHON_BIN" "$SOURCE_RESOLVER" --root "$ROOT" --output "$RESOLUTION"

EXACT5_RESOLVED=$("$PYTHON_BIN" - "$RESOLUTION" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("true" if p.get("resolved") is True else "false")
PY
)

if [ "$EXACT5_RESOLVED" != true ]; then
  set_stage publish_exact5_unresolved_hold
  "$PYTHON_BIN" - "$RESULT" "$RESOLUTION" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
result_path=Path(sys.argv[1])
resolution=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload={
  "schema":"q4r3_exact25_persistent_single_event_writer_exact5_result_v1",
  "created_at":datetime.now(timezone.utc).isoformat(),
  "status":"PASS_Q4R3_EXACT25_PERSISTENT_WRITER_PRECHECK",
  "verdict":"EXACT5_SSOT_UNRESOLVED_NO_MUTATION",
  "action":"HOLD",
  "next_action":"REVIEW_EXACT5_CANDIDATES_AND_BIND_ONE_SSOT_THEN_RERUN",
  "exact5_resolved":False,
  "symbols":[],
  "resolver_verdict":resolution.get("verdict"),
  "resolver_candidates":resolution.get("candidates",[])[:20],
  "writer_active":"not_installed",
  "production_measurement_write_enabled":False,
  "producer_active":"unchanged",
  "historical_backfill_allowed":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none",
}
result_path.parent.mkdir(parents=True,exist_ok=True)
result_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
PY
else
  set_stage backup_active_surfaces
  mkdir -p "$BACKUP_DIR"
  if systemctl is-active --quiet "$PRODUCER_UNIT_NAME"; then echo true > "$BACKUP_DIR/producer_was_active"; else echo false > "$BACKUP_DIR/producer_was_active"; fi
  if systemctl is-active --quiet "$WRITER_UNIT_NAME"; then echo true > "$BACKUP_DIR/writer_was_active"; else echo false > "$BACKUP_DIR/writer_was_active"; fi
  backup_file "$ACTIVE_ADAPTER" active_adapter
  backup_file "$ACTIVE_WRITER" active_writer
  backup_file "$WRITER_ENV" writer_env
  backup_file "$WRITER_UNIT" writer_unit
  backup_file "$PRODUCER_ENV" producer_env
  backup_file "$GATE" gate
  backup_file "$LEDGER" ledger
  backup_file "$WRITER_STATUS" writer_status
  backup_file "$RESOLUTION" resolution
  PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT_NAME" -p MainPID --value)
  MUTATION_STARTED=true

  set_stage install_active_adapter_writer_and_exact5_producer_env
  systemctl stop "$WRITER_UNIT_NAME" 2>/dev/null || true
  systemctl stop "$PRODUCER_UNIT_NAME"
  install -m 0755 "$SOURCE_ADAPTER" "$ACTIVE_ADAPTER.tmp"
  mv -f "$ACTIVE_ADAPTER.tmp" "$ACTIVE_ADAPTER"
  install -m 0755 "$SOURCE_WRITER" "$ACTIVE_WRITER.tmp"
  mv -f "$ACTIVE_WRITER.tmp" "$ACTIVE_WRITER"

  SYMBOLS_CSV=$("$PYTHON_BIN" - "$RESOLUTION" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if p.get("resolved") is not True or len(p.get("symbols") or []) != 5:
    raise SystemExit("RESOLUTION_NOT_EXACT5")
print(",".join(p["symbols"]))
PY
)

  "$PYTHON_BIN" - "$PRODUCER_ENV" "$SYMBOLS_CSV" <<'PY'
import sys
from pathlib import Path
path=Path(sys.argv[1])
symbols=sys.argv[2]
lines=path.read_text(encoding="utf-8").splitlines()
out=[]
found=False
for line in lines:
    if line.startswith("Q4R3_SYMBOLS="):
        out.append("Q4R3_SYMBOLS="+symbols)
        found=True
    else:
        out.append(line)
if not found:
    out.append("Q4R3_SYMBOLS="+symbols)
tmp=path.with_suffix(path.suffix+".tmp")
tmp.write_text("\n".join(out)+"\n",encoding="utf-8")
tmp.replace(path)
PY

  systemctl daemon-reload
  systemctl start "$PRODUCER_UNIT_NAME"

  set_stage verify_exact5_producer_cycles
  for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$PRODUCER_UNIT_NAME"; then
      if "$PYTHON_BIN" - "$PRODUCER_STATUS" "$SYMBOLS_CSV" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected=sys.argv[2].split(",")
actual=p.get("symbols") or []
raise SystemExit(0 if p.get("state")=="RUNNING" and p.get("processed_symbol_count")==5 and set(actual)==set(expected) else 1)
PY
      then break; fi
    fi
    sleep 5
  done
  "$PYTHON_BIN" - "$PRODUCER_STATUS" "$SYMBOLS_CSV" <<'PY'
import json, sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected=sys.argv[2].split(",")
if p.get("state")!="RUNNING": raise SystemExit(f"PRODUCER_NOT_RUNNING:{p.get('state')}")
if p.get("processed_symbol_count")!=5: raise SystemExit(f"PRODUCER_NOT_5_SYMBOLS:{p.get('processed_symbol_count')}")
if set(p.get("symbols") or [])!=set(expected): raise SystemExit(f"PRODUCER_SYMBOL_SET_MISMATCH:{p.get('symbols')}")
if p.get("cycle_errors") not in ({}, None): raise SystemExit(f"PRODUCER_CYCLE_ERRORS:{p.get('cycle_errors')}")
PY

  set_stage create_fresh_exact5_measurement_gate
  if [ -s "$LEDGER" ]; then
    echo "FORMAL_LEDGER_ALREADY_NONEMPTY" >&2
    exit 4
  fi
  rm -f "$LEDGER" "$WRITER_STATUS"
  touch "$LEDGER"
  chmod 0600 "$LEDGER"
  "$PYTHON_BIN" - "$GATE" "$RESOLUTION" "$TRANSACTION_ID" <<'PY'
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
gate=Path(sys.argv[1])
resolution=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
now=time.time()
payload={
  "schema":"q4r3_exact25_formal_exact5_measurement_gate_v1",
  "state":"ACTIVE",
  "transaction_id":sys.argv[3],
  "created_at":datetime.now(timezone.utc).isoformat(),
  "start_epoch":now,
  "start_at":datetime.fromtimestamp(now,timezone.utc).isoformat(),
  "epoch_id":"EXACT25_EDGE_V1",
  "measurement_namespace":"EXACT25_EDGE_V1",
  "symbol_universe":"EXACT5",
  "symbols":resolution["symbols"],
  "symbol_ssot_path":resolution.get("source_path"),
  "symbol_ssot_location":resolution.get("source_location"),
  "strategy_count":25,
  "shadow_only":True,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "historical_backfill_allowed":False,
}
tmp=gate.with_suffix(gate.suffix+".tmp")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
tmp.replace(gate)
PY

  cat > "$WRITER_ENV.tmp" <<'EOF'
Q4R3_SHADOW_ONLY=1
Q4R3_PAPER_ENABLED=0
Q4R3_LIVE_ENABLED=0
Q4R3_ORDER_ENABLED=0
Q4R3_HISTORICAL_BACKFILL_ALLOWED=0
Q4R3_MEASUREMENT_WRITE_ENABLED=1
Q4R3_EPOCH_ID=EXACT25_EDGE_V1
Q4R3_SYMBOL_UNIVERSE=EXACT5
EOF
  chmod 0644 "$WRITER_ENV.tmp"
  mv -f "$WRITER_ENV.tmp" "$WRITER_ENV"

  cat > "$WRITER_UNIT.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Persistent Single-Event Forward Measurement Writer
After=network-online.target $PRODUCER_UNIT_NAME
Wants=network-online.target
Requires=$PRODUCER_UNIT_NAME

[Service]
Type=simple
WorkingDirectory=$ROOT
EnvironmentFile=$WRITER_ENV
ExecStart=$PYTHON_BIN $ACTIVE_WRITER --root $ROOT --close-surface $CLOSE_SURFACE --manifest $MANIFEST --ledger $LEDGER --status $WRITER_STATUS --gate $GATE --poll-sec 5
Restart=on-failure
RestartSec=10
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement

[Install]
WantedBy=multi-user.target
EOF
  chmod 0644 "$WRITER_UNIT.tmp"
  mv -f "$WRITER_UNIT.tmp" "$WRITER_UNIT"
  systemctl daemon-reload
  systemctl enable --now "$WRITER_UNIT_NAME"

  set_stage verify_persistent_writer_stability
  HEARTBEAT_BEFORE=0
  for _ in $(seq 1 24); do
    if [ -s "$WRITER_STATUS" ]; then
      HEARTBEAT_NOW=$("$PYTHON_BIN" - "$WRITER_STATUS" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(int(p.get("heartbeat_count") or 0))
PY
)
      if [ "$HEARTBEAT_NOW" -ge 3 ]; then break; fi
    fi
    sleep 5
  done
  WRITER_PID=$(systemctl show "$WRITER_UNIT_NAME" -p MainPID --value)
  "$PYTHON_BIN" - "$WRITER_STATUS" "$GATE" "$RESOLUTION" "$WRITER_PID" <<'PY'
import json,sys
from pathlib import Path
status=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
gate=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
resolution=json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
if status.get("state")!="RUNNING": raise SystemExit(f"WRITER_NOT_RUNNING:{status.get('state')}")
if int(status.get("heartbeat_count") or 0)<3: raise SystemExit("WRITER_HEARTBEAT_TOO_LOW")
if status.get("last_error") not in (None,""): raise SystemExit(f"WRITER_LAST_ERROR:{status.get('last_error')}")
if status.get("production_measurement_write_enabled") is not True: raise SystemExit("MEASUREMENT_WRITE_NOT_ENABLED")
if status.get("historical_backfill_allowed") is not False: raise SystemExit("BACKFILL_FLAG_UNSAFE")
if status.get("symbols")!=gate.get("symbols") or status.get("symbols")!=resolution.get("symbols"):
    raise SystemExit("WRITER_GATE_SYMBOL_MISMATCH")
if sys.argv[4] in {"","0"}: raise SystemExit("WRITER_MAIN_PID_INVALID")
PY

  set_stage publish_active_result
  PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT_NAME" -p MainPID --value)
  "$PYTHON_BIN" - "$RESULT" "$RESOLUTION" "$GATE" "$WRITER_STATUS" "$PRODUCER_STATUS" "$LEDGER" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$WRITER_PID" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
result=Path(sys.argv[1])
resolution=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
gate=json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
writer=json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
producer=json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
ledger=Path(sys.argv[6])
rows=sum(1 for line in ledger.read_text(encoding="utf-8",errors="ignore").splitlines() if line.strip())
payload={
  "schema":"q4r3_exact25_persistent_single_event_writer_exact5_result_v1",
  "created_at":datetime.now(timezone.utc).isoformat(),
  "status":"PASS_Q4R3_EXACT25_PERSISTENT_SINGLE_EVENT_WRITER_EXACT5",
  "verdict":"FORMAL_EXACT5_FORWARD_MEASUREMENT_ACTIVE",
  "action":"HOLD",
  "next_action":"ACCUMULATE_FORMAL_EXACT5_CLOSE_ROWS_THEN_BUILD_STRATEGY_COMPARISON_SCOREBOARD",
  "exact5_resolved":True,
  "symbols":resolution["symbols"],
  "symbol_ssot_path":resolution.get("source_path"),
  "measurement_start_at":gate.get("start_at"),
  "measurement_start_epoch":gate.get("start_epoch"),
  "strategy_count":25,
  "writer_active":"active",
  "writer_substate":"running",
  "writer_main_pid":int(sys.argv[9]),
  "writer_state":writer.get("state"),
  "writer_heartbeat_count":writer.get("heartbeat_count"),
  "production_measurement_write_enabled":True,
  "ledger_path":str(ledger),
  "ledger_row_count":rows,
  "producer_active":"active",
  "producer_substate":"running",
  "producer_processed_symbol_count":producer.get("processed_symbol_count"),
  "producer_pid_before":int(sys.argv[7]),
  "producer_pid_after":int(sys.argv[8]),
  "producer_restart_expected":sys.argv[7]!=sys.argv[8],
  "feature_observer_enabled":producer.get("feature_observer_enabled"),
  "feature_filter_enabled":producer.get("feature_filter_enabled"),
  "historical_backfill_allowed":False,
  "paper_enabled":False,
  "live_enabled":False,
  "order_enabled":False,
  "order_authority":"blocked",
  "execution_authority":"none",
}
result.parent.mkdir(parents=True,exist_ok=True)
result.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
PY
fi

set_stage commit_and_push_evidence
cd "$WORKTREE"
git add runtime_results/q4r3/exact25_persistent_single_event_writer_exact5
if git diff --cached --quiet; then
  REPORT_COMMIT=$(git rev-parse HEAD)
else
  git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" commit -m "Publish persistent Exact5 writer activation evidence"
  REPORT_COMMIT=$(git rev-parse HEAD)
  git push origin HEAD:"$BRANCH"
fi

CURRENT_STAGE=complete
write_job_status DONE published "$REPORT_COMMIT"
trap - ERR
ROLLBACK_DONE=true

echo "Q4R3_EXACT25_PERSISTENT_SINGLE_EVENT_WRITER_EXACT5_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
