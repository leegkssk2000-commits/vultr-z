#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_PRODUCER_WORKTREE:-/tmp/q4r3-exact25-dedicated-shadow-producer-canary}
BRANCH=q4r3-exact25-dedicated-shadow-producer-canary
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_PRODUCER=$WORKTREE/tools/q4r3_exact25_dedicated_shadow_producer.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_dedicated_shadow_producer.py
ACTIVE_PRODUCER=$ROOT/tools/q4r3_exact25_dedicated_shadow_producer.py
PRODUCER_ENV=/etc/default/q4r3-exact25-shadow-producer
PRODUCER_UNIT_NAME=q4r3-exact25-shadow-producer.service
PRODUCER_UNIT=/etc/systemd/system/$PRODUCER_UNIT_NAME
CANARY_UNIT_NAME=q4r3-exact25-forward-measurement-writer.service
CANARY_UNIT=/etc/systemd/system/$CANARY_UNIT_NAME
WATCHER_UNIT=q4r3-forward-r-persistent-write-watch.service
MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
BINDING=$ROOT/backend/config/q4r3_exact25_shadow_binding_v1.json
LOADER=$ROOT/backend/engine/q4r3_exact25_shadow_manifest_loader.py
AUTHORITY_STATUS=$ROOT/runtime/q4r3_exact25_close_source_authority_lock_job_latest.json
CANARY_STATUS=$ROOT/runtime/exact25_edge_v1/first_real_forward_canary/status_latest.json
PRODUCER_ROOT=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer
PRODUCER_STATE=$PRODUCER_ROOT/state.json
PRODUCER_STATUS=$PRODUCER_ROOT/status_latest.json
OPEN_LATEST=$PRODUCER_ROOT/open_positions_latest.json
CLOSE_LATEST=$PRODUCER_ROOT/close_latest.json
PRODUCER_LEDGER=$PRODUCER_ROOT/ledger.jsonl
PROBE_RESULT=$PRODUCER_ROOT/probe_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_dedicated_shadow_producer_canary_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_dedicated_shadow_producer_canary_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_dedicated_shadow_producer_canary
RESULT=$RESULT_DIR/q4r3_exact25_dedicated_shadow_producer_canary_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_dedicated_shadow_producer_canary_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
ROLLBACK_DONE=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR" "$PRODUCER_ROOT"
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
    "job": "q4r3_exact25_dedicated_shadow_producer_canary",
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
    "measurement_writer_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
    "dedicated_shadow_producer_modified": True,
    "canary_source_modified": True,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "producer_active",
            "producer_substate", "producer_main_pid", "producer_state",
            "strategy_count", "symbol_count", "processed_symbol_count",
            "feature_observer_enabled", "feature_filter_enabled",
            "canary_active", "canary_substate", "canary_writer_invocation_count",
            "watcher_pid_unchanged", "rollback_available",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = f"{type(exc).__name__}:{exc}"
temp = status_path.with_suffix(status_path.suffix + ".tmp")
temp.parent.mkdir(parents=True, exist_ok=True)
temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temp.replace(status_path)
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
  echo "=== ROLLBACK ==="
  systemctl stop "$PRODUCER_UNIT_NAME" 2>/dev/null || true
  systemctl stop "$CANARY_UNIT_NAME" 2>/dev/null || true
  restore_file "$ACTIVE_PRODUCER" active_producer
  restore_file "$PRODUCER_ENV" producer_env
  restore_file "$PRODUCER_UNIT" producer_unit
  restore_file "$CANARY_UNIT" canary_unit
  restore_file "$PRODUCER_STATE" producer_state
  restore_file "$PRODUCER_STATUS" producer_status
  restore_file "$OPEN_LATEST" open_latest
  restore_file "$CLOSE_LATEST" close_latest
  restore_file "$PRODUCER_LEDGER" producer_ledger
  restore_file "$PROBE_RESULT" probe_result
  systemctl daemon-reload || true
  if [ "$(cat "$BACKUP_DIR/canary_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$CANARY_UNIT_NAME" 2>/dev/null || true
  fi
  if [ "$(cat "$BACKUP_DIR/producer_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$PRODUCER_UNIT_NAME" 2>/dev/null || true
  fi
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_DEDICATED_SHADOW_PRODUCER_CANARY_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" \
  "$SOURCE_PRODUCER" \
  "$TEST_FILE" \
  "$MANIFEST" \
  "$BINDING" \
  "$LOADER" \
  "$AUTHORITY_STATUS" \
  "$CANARY_STATUS" \
  "$CANARY_UNIT"
do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_python_and_unit_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$SOURCE_PRODUCER"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage prerequisite_authority_canary_and_safety_gate
"$PYTHON_BIN" - "$AUTHORITY_STATUS" "$CANARY_STATUS" "$MANIFEST" "$BINDING" <<'PY'
import json
import sys
from pathlib import Path

authority = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if authority.get("status") != "PASS_Q4R3_EXACT25_CLOSE_SOURCE_AUTHORITY_LOCK":
    raise SystemExit("CLOSE_AUTHORITY_STATUS_NOT_PASS")
if authority.get("verdict") != "NO_PROVEN_EXACT25_SHADOW_CLOSE_AUTHORITY":
    raise SystemExit(f"UNEXPECTED_CLOSE_AUTHORITY_VERDICT:{authority.get('verdict')}")
canary = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if canary.get("state") != "WAITING_REAL_FORWARD_OPEN_CLOSE":
    raise SystemExit(f"CANARY_NOT_WAITING:{canary.get('state')}")
if int(canary.get("writer_invocation_count", -1)) != 0:
    raise SystemExit("CANARY_WRITER_ALREADY_INVOKED")
manifest = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
strategies = manifest.get("strategies")
if not isinstance(strategies, list) or len(strategies) != 25:
    raise SystemExit("MANIFEST_NOT_EXACT25")
binding = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
if binding.get("shadow_enabled") is not True:
    raise SystemExit("SHADOW_BINDING_DISABLED")
for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled"):
    if binding.get(key) is not False:
        raise SystemExit(f"UNSAFE_BINDING_FLAG:{key}:{binding.get(key)}")
PY

set_stage public_bingx_exact25_probe
rm -f "$PROBE_RESULT"
env \
  Q4R3_SHADOW_ONLY=1 \
  Q4R3_PAPER_ENABLED=0 \
  Q4R3_LIVE_ENABLED=0 \
  Q4R3_ORDER_ENABLED=0 \
  Q4R3_HISTORICAL_BACKFILL_ALLOWED=0 \
  Q4R3_EPOCH_ID=EXACT25_EDGE_V1 \
  Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY \
  "$PYTHON_BIN" "$SOURCE_PRODUCER" \
    --root "$ROOT" \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
    --timeframe 1m \
    --candle-limit 420 \
    --probe-output "$PROBE_RESULT" \
    --probe-only

"$PYTHON_BIN" - "$PROBE_RESULT" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "PASS":
    raise SystemExit(f"PROBE_NOT_PASS:{payload.get('status')}")
if payload.get("strategy_count") != 25 or payload.get("pass_count") != 25 or payload.get("failure_count") != 0:
    raise SystemExit("PROBE_NOT_25_OF_25")
if payload.get("private_credentials_used") is not False:
    raise SystemExit("PRIVATE_CREDENTIAL_SIGNAL")
for key in ("paper_enabled", "live_enabled", "order_enabled"):
    if payload.get(key) is not False:
        raise SystemExit(f"UNSAFE_PROBE_FLAG:{key}")
PY

set_stage backup_active_surfaces
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$PRODUCER_UNIT_NAME"; then echo true > "$BACKUP_DIR/producer_was_active"; else echo false > "$BACKUP_DIR/producer_was_active"; fi
if systemctl is-active --quiet "$CANARY_UNIT_NAME"; then echo true > "$BACKUP_DIR/canary_was_active"; else echo false > "$BACKUP_DIR/canary_was_active"; fi
backup_file "$ACTIVE_PRODUCER" active_producer
backup_file "$PRODUCER_ENV" producer_env
backup_file "$PRODUCER_UNIT" producer_unit
backup_file "$CANARY_UNIT" canary_unit
backup_file "$PRODUCER_STATE" producer_state
backup_file "$PRODUCER_STATUS" producer_status
backup_file "$OPEN_LATEST" open_latest
backup_file "$CLOSE_LATEST" close_latest
backup_file "$PRODUCER_LEDGER" producer_ledger
backup_file "$PROBE_RESULT" probe_result
WATCHER_PID_BEFORE=$(systemctl show "$WATCHER_UNIT" -p MainPID --value 2>/dev/null || echo 0)

set_stage install_dedicated_shadow_producer_and_bind_canary_source
systemctl stop "$PRODUCER_UNIT_NAME" 2>/dev/null || true
systemctl stop "$CANARY_UNIT_NAME" 2>/dev/null || true
install -m 0755 "$SOURCE_PRODUCER" "$ACTIVE_PRODUCER.tmp"
mv -f "$ACTIVE_PRODUCER.tmp" "$ACTIVE_PRODUCER"

cat > "$PRODUCER_ENV.tmp" <<'EOF'
Q4R3_SHADOW_ONLY=1
Q4R3_PAPER_ENABLED=0
Q4R3_LIVE_ENABLED=0
Q4R3_ORDER_ENABLED=0
Q4R3_HISTORICAL_BACKFILL_ALLOWED=0
Q4R3_EPOCH_ID=EXACT25_EDGE_V1
Q4R3_PRODUCER_STAGE=FIRST_FORWARD_CANARY
Q4R3_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT
EOF
chmod 0644 "$PRODUCER_ENV.tmp"
mv -f "$PRODUCER_ENV.tmp" "$PRODUCER_ENV"

cat > "$PRODUCER_UNIT.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Dedicated Public-Market Shadow Producer Canary
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
EnvironmentFile=$PRODUCER_ENV
ExecStart=$PYTHON_BIN $ACTIVE_PRODUCER --root $ROOT --symbols \${Q4R3_SYMBOLS} --timeframe 1m --candle-limit 420 --poll-sec 15 --max-hold-min 120 --risk-unit-usdt 1.0 --fee-rate 0.0005 --slippage-bps 1.0 --state $PRODUCER_STATE --status $PRODUCER_STATUS --open-latest $OPEN_LATEST --close-latest $CLOSE_LATEST --ledger $PRODUCER_LEDGER
Restart=on-failure
RestartSec=15
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$ROOT/runtime

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$PRODUCER_UNIT.tmp"
mv -f "$PRODUCER_UNIT.tmp" "$PRODUCER_UNIT"

"$PYTHON_BIN" - "$CANARY_UNIT" "$CLOSE_LATEST" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
close_path = sys.argv[2]
text = path.read_text(encoding="utf-8")
if close_path not in text:
    marker = " --canary-ledger "
    if text.count(marker) != 1:
        raise SystemExit(f"CANARY_EXECSTART_MARKER_COUNT:{text.count(marker)}")
    text = text.replace(marker, f" --close-source {close_path}" + marker, 1)
path_tmp = path.with_suffix(path.suffix + ".tmp")
path_tmp.write_text(text, encoding="utf-8")
path_tmp.replace(path)
updated = path.read_text(encoding="utf-8")
if updated.count(close_path) != 1:
    raise SystemExit(f"DEDICATED_CLOSE_SOURCE_BIND_COUNT:{updated.count(close_path)}")
PY

systemctl daemon-reload
systemctl enable --now "$PRODUCER_UNIT_NAME"
systemctl restart "$CANARY_UNIT_NAME"

set_stage service_stability_and_fail_closed_gate
for _ in $(seq 1 36); do
  PRODUCER_ACTIVE=$(systemctl show "$PRODUCER_UNIT_NAME" -p ActiveState --value 2>/dev/null || echo unknown)
  PRODUCER_SUBSTATE=$(systemctl show "$PRODUCER_UNIT_NAME" -p SubState --value 2>/dev/null || echo unknown)
  if [ "$PRODUCER_ACTIVE" = active ] && [ "$PRODUCER_SUBSTATE" = running ] && [ -s "$PRODUCER_STATUS" ]; then
    break
  fi
  sleep 5
done

PRODUCER_ACTIVE=$(systemctl show "$PRODUCER_UNIT_NAME" -p ActiveState --value)
PRODUCER_SUBSTATE=$(systemctl show "$PRODUCER_UNIT_NAME" -p SubState --value)
PRODUCER_MAIN_PID=$(systemctl show "$PRODUCER_UNIT_NAME" -p MainPID --value)
CANARY_ACTIVE=$(systemctl show "$CANARY_UNIT_NAME" -p ActiveState --value)
CANARY_SUBSTATE=$(systemctl show "$CANARY_UNIT_NAME" -p SubState --value)
WATCHER_PID_AFTER=$(systemctl show "$WATCHER_UNIT" -p MainPID --value 2>/dev/null || echo 0)

[ "$PRODUCER_ACTIVE" = active ]
[ "$PRODUCER_SUBSTATE" = running ]
[ "${PRODUCER_MAIN_PID:-0}" -gt 0 ]
[ "$CANARY_ACTIVE" = active ]
[ "$CANARY_SUBSTATE" = running ]
[ "$WATCHER_PID_BEFORE" = "$WATCHER_PID_AFTER" ]

grep -F -- "$CLOSE_LATEST" "$CANARY_UNIT" >/dev/null

"$PYTHON_BIN" - "$PRODUCER_STATUS" "$CANARY_STATUS" <<'PY'
import json
import sys
from pathlib import Path
producer = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if producer.get("state") != "RUNNING":
    raise SystemExit(f"PRODUCER_NOT_RUNNING:{producer.get('state')}:{producer.get('cycle_errors')}")
if producer.get("strategy_count") != 25:
    raise SystemExit("PRODUCER_NOT_EXACT25")
if len(producer.get("symbols") or []) != 4:
    raise SystemExit("CORE4_CANARY_SYMBOL_COUNT_MISMATCH")
if producer.get("processed_symbol_count") != 4:
    raise SystemExit(f"PRODUCER_SYMBOL_PROCESSING_GAP:{producer.get('processed_symbol_count')}:{producer.get('cycle_errors')}")
if producer.get("feature_observer_enabled") is not True or producer.get("feature_filter_enabled") is not False:
    raise SystemExit("FEATURE_OBSERVER_GATE_MISMATCH")
if producer.get("measurement_writer_enabled") is not False:
    raise SystemExit("MEASUREMENT_WRITER_PREMATURELY_ENABLED")
if producer.get("private_credentials_used") is not False:
    raise SystemExit("PRIVATE_CREDENTIAL_SIGNAL")
for key in ("paper_enabled", "live_enabled", "order_enabled", "historical_backfill_allowed"):
    if producer.get(key) is not False:
        raise SystemExit(f"UNSAFE_PRODUCER_FLAG:{key}:{producer.get(key)}")
canary = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if canary.get("state") not in {"WAITING_REAL_FORWARD_OPEN_CLOSE", "CANARY_PASS"}:
    raise SystemExit(f"CANARY_STATE_UNEXPECTED:{canary.get('state')}")
if canary.get("state") == "WAITING_REAL_FORWARD_OPEN_CLOSE" and int(canary.get("writer_invocation_count", -1)) != 0:
    raise SystemExit("CANARY_WRITER_PREMATURELY_INVOKED")
PY

set_stage publish_sanitized_evidence
"$PYTHON_BIN" - "$RESULT" "$PRODUCER_STATUS" "$CANARY_STATUS" "$PROBE_RESULT" "$PRODUCER_ACTIVE" "$PRODUCER_SUBSTATE" "$PRODUCER_MAIN_PID" "$CANARY_ACTIVE" "$CANARY_SUBSTATE" "$WATCHER_PID_BEFORE" "$WATCHER_PID_AFTER" "$BACKUP_DIR" "$CLOSE_LATEST" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

result_path = Path(sys.argv[1])
producer = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
canary = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
probe = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
result = {
    "schema": "q4r3_exact25_dedicated_shadow_producer_canary_result_v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS_Q4R3_EXACT25_DEDICATED_SHADOW_PRODUCER_CANARY",
    "verdict": "DEDICATED_EXACT25_SHADOW_PRODUCER_RUNNING_CANARY_SOURCE_BOUND",
    "action": "HOLD",
    "next_action": "WAIT_FOR_FIRST_DEDICATED_EXACT25_SHADOW_CLOSE_THEN_VALIDATE_MEASUREMENT_CANARY",
    "producer_active": sys.argv[5],
    "producer_substate": sys.argv[6],
    "producer_main_pid": int(sys.argv[7]),
    "producer_state": producer.get("state"),
    "strategy_count": producer.get("strategy_count"),
    "symbol_count": len(producer.get("symbols") or []),
    "symbols": producer.get("symbols"),
    "timeframe": producer.get("timeframe"),
    "processed_symbol_count": producer.get("processed_symbol_count"),
    "cycle_count": producer.get("cycle_count"),
    "open_event_count": producer.get("open_event_count"),
    "close_event_count": producer.get("close_event_count"),
    "open_position_count": producer.get("open_position_count"),
    "feature_observer_enabled": producer.get("feature_observer_enabled"),
    "feature_filter_enabled": producer.get("feature_filter_enabled"),
    "observer_features": [
        "htf_bias", "swing_sequence", "dealing_range_position",
        "premium_discount_side", "ote_depth", "ltf_reversal_confirm",
        "session_window", "invalidation_swing_distance_pct",
    ],
    "core4_canary_only": True,
    "exact5_symbol_expansion_after_canary": True,
    "probe_pass_count": probe.get("pass_count"),
    "canary_active": sys.argv[8],
    "canary_substate": sys.argv[9],
    "canary_state": canary.get("state"),
    "canary_writer_invocation_count": canary.get("writer_invocation_count"),
    "dedicated_close_surface": sys.argv[13],
    "watcher_pid_unchanged": sys.argv[10] == sys.argv[11],
    "rollback_available": Path(sys.argv[12]).is_dir(),
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "binding_modified": False,
    "epoch_modified": False,
    "measurement_writer_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
    "historical_backfill_allowed": False,
}
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
PY

cd "$WORKTREE"
git config user.name "ZEL Exact25 Producer"
git config user.email "exact25-producer@z-os.local"
git add runtime_results/q4r3/exact25_dedicated_shadow_producer_canary
if git diff --cached --quiet; then
  REPORT_COMMIT=$(git rev-parse HEAD)
else
  git -c core.hooksPath=/dev/null commit -m "Publish Exact25 dedicated shadow producer canary evidence"
  REPORT_COMMIT=$(git rev-parse HEAD)
  git push origin "HEAD:refs/heads/$BRANCH"
fi

CURRENT_STAGE=complete
write_job_status DONE published "$REPORT_COMMIT"
echo "Q4R3_EXACT25_DEDICATED_SHADOW_PRODUCER_CANARY_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
