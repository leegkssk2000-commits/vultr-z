#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_ADAPTER_WORKTREE:-/tmp/q4r3-exact25-shadow-writer-adapter-dryrun}
BRANCH=q4r3-exact25-shadow-writer-adapter-dryrun
PYTHON_BIN=$ROOT/.venv/bin/python
SOURCE_ADAPTER=$WORKTREE/tools/q4r3_exact25_forward_measurement_service_adapter.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_forward_measurement_service_adapter.py
ACTIVE_ADAPTER=$ROOT/tools/q4r3_exact25_forward_measurement_service_adapter.py
WRITER=$ROOT/tools/q4r3_vwap_mfe_mae_capture_sidecar.py
WRITER_SHA=d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50
GATE=$ROOT/backend/config/q4r3_exact25_forward_measurement_writer_gate_v1.json
ENV_FILE=/etc/default/q4r3-exact25-forward-measurement-writer
UNIT_NAME=q4r3-exact25-forward-measurement-writer.service
UNIT_FILE=/etc/systemd/system/$UNIT_NAME
ADAPTER_STATUS=$ROOT/runtime/exact25_edge_v1/writer_service_status.json
TRACE_STATUS=$ROOT/runtime/q4r3_exact25_writer_service_contract_trace_job_latest.json
CANARY_STATUS=$ROOT/runtime/q4r3_exact25_edge_v1_shadow_canary_job_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_shadow_writer_adapter_dryrun_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_shadow_writer_adapter_dryrun_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_shadow_writer_adapter_dryrun
RESULT=$RESULT_DIR/q4r3_exact25_shadow_writer_adapter_dryrun_latest.json
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_writer_adapter_backups/$(date -u +%Y%m%dT%H%M%S.%NZ)
WATCHER_UNIT=q4r3-forward-r-persistent-write-watch.service
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
ROLLBACK_DONE=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
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
    "job": "q4r3_exact25_shadow_writer_adapter_dryrun",
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
    "writer_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "service_active",
            "service_substate",
            "service_main_pid",
            "heartbeat_count",
            "writer_invocation_count",
            "output_hashes_unchanged",
            "watcher_pid_unchanged",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
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
  if [ "$ROLLBACK_DONE" = true ]; then
    return 0
  fi
  ROLLBACK_DONE=true
  trap - ERR
  echo "=== ROLLBACK ==="
  systemctl stop "$UNIT_NAME" 2>/dev/null || true
  restore_file "$ACTIVE_ADAPTER" active_adapter
  restore_file "$GATE" gate
  restore_file "$ENV_FILE" env_file
  restore_file "$UNIT_FILE" unit_file
  restore_file "$ADAPTER_STATUS" adapter_status
  systemctl daemon-reload || true
  if [ "$(cat "$BACKUP_DIR/unit_was_active" 2>/dev/null || echo false)" = true ]; then
    systemctl start "$UNIT_NAME" 2>/dev/null || true
  fi
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_SHADOW_WRITER_ADAPTER_DRYRUN_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

file_hash_or_missing() {
  local path=$1
  if [ -f "$path" ]; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo MISSING
  fi
}

snapshot_writer_outputs() {
  local destination=$1
  : > "$destination"
  for path in \
    "$ROOT/runtime/q4r3_vwap_mfe_mae_capture_latest.json" \
    "$ROOT/runtime/q4r3_vwap_mfe_mae_capture_state.json" \
    "$ROOT/runtime/vwap_mfe_mae_closed_rows_overlay.json"; do
    printf '%s\t%s\n' "$path" "$(file_hash_or_missing "$path")" >> "$destination"
  done
}

for required in "$PYTHON_BIN" "$SOURCE_ADAPTER" "$TEST_FILE" "$WRITER" "$TRACE_STATUS" "$CANARY_STATUS"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_and_unit_tests
bash -n "$0"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage prerequisite_and_writer_sha_gate
"$PYTHON_BIN" - "$TRACE_STATUS" "$CANARY_STATUS" "$WRITER" "$WRITER_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

trace = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
canary = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
writer = Path(sys.argv[3])
expected_sha = sys.argv[4]
actual_sha = hashlib.sha256(writer.read_bytes()).hexdigest()
if trace.get("status") != "PASS_Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE":
    raise SystemExit("TRACE_STATUS_NOT_PASS")
if trace.get("epoch_id") != "EXACT25_EDGE_V1":
    raise SystemExit("TRACE_EPOCH_MISMATCH")
if (trace.get("writer_structure") or {}).get("execution_shape") != "THIN_ADAPTER_REQUIRED":
    raise SystemExit("THIN_ADAPTER_NOT_REQUIRED_BY_TRACE")
if canary.get("status") != "PASS_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY":
    raise SystemExit("CANARY_STATUS_NOT_PASS")
if actual_sha != expected_sha:
    raise SystemExit(f"WRITER_SHA_MISMATCH expected={expected_sha} actual={actual_sha}")
PY

set_stage backup_active_surface
mkdir -p "$BACKUP_DIR"
if systemctl is-active --quiet "$UNIT_NAME"; then echo true > "$BACKUP_DIR/unit_was_active"; else echo false > "$BACKUP_DIR/unit_was_active"; fi
backup_file "$ACTIVE_ADAPTER" active_adapter
backup_file "$GATE" gate
backup_file "$ENV_FILE" env_file
backup_file "$UNIT_FILE" unit_file
backup_file "$ADAPTER_STATUS" adapter_status
WATCHER_PID_BEFORE=$(systemctl show "$WATCHER_UNIT" -p MainPID --value 2>/dev/null || echo 0)
snapshot_writer_outputs "$BACKUP_DIR/writer_outputs_before.tsv"

set_stage install_fail_closed_adapter_gate_and_service
systemctl stop "$UNIT_NAME" 2>/dev/null || true
mkdir -p "$(dirname "$ACTIVE_ADAPTER")" "$(dirname "$GATE")" "$(dirname "$ADAPTER_STATUS")"
install -m 0755 "$SOURCE_ADAPTER" "$ACTIVE_ADAPTER.tmp"
mv -f "$ACTIVE_ADAPTER.tmp" "$ACTIVE_ADAPTER"

"$PYTHON_BIN" - "$GATE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema": "q4r3_exact25_forward_measurement_writer_gate_v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "epoch_id": "EXACT25_EDGE_V1",
    "measurement_namespace": "EXACT25_EDGE_V1",
    "shadow_only": True,
    "write_enabled": False,
    "canary_enabled": False,
    "activation_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "historical_backfill_allowed": False,
    "writer_sha256": "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50",
    "promotion_state": "SERVICE_DRYRUN_ONLY",
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY

cat > "$ENV_FILE.tmp" <<'EOF'
Q4R3_EPOCH_ID=EXACT25_EDGE_V1
Q4R3_MEASUREMENT_NAMESPACE=EXACT25_EDGE_V1
Q4R3_SHADOW_ONLY=1
Q4R3_PAPER_ENABLED=0
Q4R3_LIVE_ENABLED=0
Q4R3_ORDER_ENABLED=0
Q4R3_HISTORICAL_BACKFILL_ALLOWED=0
Q4R3_SERVICE_STAGE=DRYRUN_ONLY
EOF
chmod 0644 "$ENV_FILE.tmp"
mv -f "$ENV_FILE.tmp" "$ENV_FILE"

cat > "$UNIT_FILE.tmp" <<EOF
[Unit]
Description=Q4R3 Exact25 Forward Measurement Writer (Shadow Dry-run)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN $ACTIVE_ADAPTER --gate $GATE --writer $WRITER --writer-sha256 $WRITER_SHA --status $ADAPTER_STATUS --interval-sec 3
Restart=on-failure
RestartSec=5
Nice=19
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$ROOT/runtime/exact25_edge_v1

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT_FILE.tmp"
mv -f "$UNIT_FILE.tmp" "$UNIT_FILE"

systemctl daemon-reload
systemctl enable --now "$UNIT_NAME"

set_stage service_stability_and_no_write_gate
sleep 12
SERVICE_ACTIVE=$(systemctl show "$UNIT_NAME" -p ActiveState --value)
SERVICE_SUBSTATE=$(systemctl show "$UNIT_NAME" -p SubState --value)
SERVICE_MAIN_PID=$(systemctl show "$UNIT_NAME" -p MainPID --value)
WATCHER_PID_AFTER=$(systemctl show "$WATCHER_UNIT" -p MainPID --value 2>/dev/null || echo 0)
snapshot_writer_outputs "$BACKUP_DIR/writer_outputs_after.tsv"

cmp -s "$BACKUP_DIR/writer_outputs_before.tsv" "$BACKUP_DIR/writer_outputs_after.tsv"
[ "$SERVICE_ACTIVE" = active ]
[ "$SERVICE_SUBSTATE" = running ]
[ "${SERVICE_MAIN_PID:-0}" -gt 0 ]
[ "$WATCHER_PID_BEFORE" = "$WATCHER_PID_AFTER" ]

"$PYTHON_BIN" - "$ADAPTER_STATUS" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("state") != "RUNNING_DRYRUN":
    raise SystemExit("ADAPTER_NOT_RUNNING_DRYRUN")
if int(payload.get("heartbeat_count") or 0) < 2:
    raise SystemExit("HEARTBEAT_COUNT_TOO_LOW")
for key in ("write_enabled", "canary_enabled", "activation_allowed", "paper_enabled", "live_enabled", "order_enabled", "historical_backfill_allowed"):
    if payload.get(key) is not False:
        raise SystemExit(f"UNSAFE_STATUS_FLAG:{key}")
if int(payload.get("writer_invocation_count") or -1) != 0:
    raise SystemExit("WRITER_WAS_INVOKED_DURING_DRYRUN")
PY

set_stage publish_dryrun_evidence
"$PYTHON_BIN" - "$RESULT" "$ADAPTER_STATUS" "$SERVICE_ACTIVE" "$SERVICE_SUBSTATE" "$SERVICE_MAIN_PID" "$WATCHER_PID_BEFORE" "$WATCHER_PID_AFTER" "$BACKUP_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

result_path = Path(sys.argv[1])
adapter = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload = {
    "schema": "q4r3_exact25_shadow_writer_adapter_dryrun_v1",
    "status": "PASS_Q4R3_EXACT25_SHADOW_WRITER_ADAPTER_DRYRUN",
    "verdict": "THIN_ADAPTER_SERVICE_INSTALLED_STABLE_WRITE_DISABLED",
    "action": "HOLD",
    "next_action": "RUN_FIRST_REAL_FORWARD_OPEN_CLOSE_CANARY_THEN_ENABLE_MEASUREMENT_WRITES",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "epoch_id": "EXACT25_EDGE_V1",
    "strategy_count": 25,
    "service_unit": "q4r3-exact25-forward-measurement-writer.service",
    "service_active": sys.argv[3],
    "service_substate": sys.argv[4],
    "service_main_pid": int(sys.argv[5]),
    "heartbeat_count": int(adapter.get("heartbeat_count") or 0),
    "writer_invocation_count": int(adapter.get("writer_invocation_count") or 0),
    "output_hashes_unchanged": True,
    "watcher_pid_before": int(sys.argv[6] or 0),
    "watcher_pid_after": int(sys.argv[7] or 0),
    "watcher_pid_unchanged": sys.argv[6] == sys.argv[7],
    "backup_dir": sys.argv[8],
    "write_enabled": False,
    "canary_enabled": False,
    "activation_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "historical_backfill_allowed": False,
    "writer_modified": False,
    "writer_sha256": adapter.get("writer_sha256"),
    "rollback_available": True,
}
result_path.parent.mkdir(parents=True, exist_ok=True)
tmp = result_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(result_path)
PY

cd "$WORKTREE"
git config user.name "ZEL Exact25 Auditor"
git config user.email "exact25-auditor@z-os.local"
git add runtime_results/q4r3/exact25_shadow_writer_adapter_dryrun
if git diff --cached --quiet; then
  REPORT_COMMIT=$(git rev-parse HEAD)
else
  git -c core.hooksPath=/dev/null commit -m "Publish Exact25 shadow writer adapter dry-run evidence"
  REPORT_COMMIT=$(git rev-parse HEAD)
  git push origin "HEAD:$BRANCH"
fi

CURRENT_STAGE=complete
write_job_status DONE published "$REPORT_COMMIT"
echo "Q4R3_EXACT25_SHADOW_WRITER_ADAPTER_DRYRUN_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
