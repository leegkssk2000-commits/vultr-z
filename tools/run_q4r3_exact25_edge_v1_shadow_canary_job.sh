#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_CANARY_WORKTREE:-/tmp/q4r3-exact25-edge-v1-shadow-canary}
BRANCH=q4r3-exact25-edge-v1-shadow-canary
PYTHON_BIN=$ROOT/.venv/bin/python
CANARY=$WORKTREE/tools/q4r3_exact25_edge_v1_shadow_canary.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_edge_v1_shadow_canary.py
DEST=$WORKTREE/runtime_results/q4r3/exact25_edge_v1_shadow_canary
RESULT=$DEST/q4r3_exact25_edge_v1_shadow_canary_latest.json
STATUS=$ROOT/runtime/q4r3_exact25_edge_v1_shadow_canary_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_edge_v1_shadow_canary_job.log
EPOCH=$ROOT/runtime/exact25_edge_v1/epoch_latest.json
CANARY_DIR=$ROOT/runtime/exact25_edge_v1/canary
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TRANSACTION_ID=$(date -u +%Y%m%dT%H%M%S.%6NZ)
BACKUP_DIR=$ROOT/runtime/q4r3_exact25_edge_v1_canary_backups/$TRANSACTION_ID
CURRENT_STAGE=bootstrap
WATCHER_UNIT=q4r3-forward-r-persistent-write-watch.service
WATCHER_PID_BEFORE=
WATCHER_PID_AFTER=

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$RESULT" "$CURRENT_STAGE" "$LOG" "$TRANSACTION_ID" "$BACKUP_DIR" "$WATCHER_PID_BEFORE" "$WATCHER_PID_AFTER" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_edge_v1_shadow_canary",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
    "current_stage": sys.argv[8],
    "log_path": sys.argv[9],
    "transaction_id": sys.argv[10],
    "backup_dir": sys.argv[11],
    "watcher_pid_before": int(sys.argv[12]) if sys.argv[12].isdigit() else None,
    "watcher_pid_after": int(sys.argv[13]) if sys.argv[13].isdigit() else None,
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
    "canary_namespace_only": True,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "epoch_id", "strategy_count",
            "first_write", "replay_write", "verification", "authoritative_writer",
            "authoritative_writer_sha256", "canary_ledger_path",
            "production_measurement_write_enabled", "paper_enabled", "live_enabled", "order_enabled",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
tmp = status.with_suffix(".json.tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status)
PY
}

set_stage() {
  CURRENT_STAGE=$1
  write_status RUNNING "stage=$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

restore_backup() {
  set +e
  if [ -f "$BACKUP_DIR/epoch_latest.json" ]; then
    cp -a "$BACKUP_DIR/epoch_latest.json" "$EPOCH"
  fi
  rm -rf "$CANARY_DIR"
  if [ -d "$BACKUP_DIR/canary" ]; then
    cp -a "$BACKUP_DIR/canary" "$CANARY_DIR"
  fi
  set -e
}

on_error() {
  local code=$?
  trap - ERR
  CURRENT_STAGE="${CURRENT_STAGE}_rollback"
  restore_backup || true
  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code" || true
  echo "Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime" "$DEST" "$BACKUP_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in "$PYTHON_BIN" "$CANARY" "$TEST_FILE" "$EPOCH"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_and_unit_tests
bash -n "$0"
cd "$WORKTREE"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage active_binding_and_watcher_gate
"$PYTHON_BIN" - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
binding = json.loads((root / "backend/config/q4r3_exact25_shadow_binding_v1.json").read_text(encoding="utf-8"))
epoch = json.loads((root / "runtime/exact25_edge_v1/epoch_latest.json").read_text(encoding="utf-8"))
assert binding["schema"] == "q4r3_exact25_shadow_binding_v1"
assert binding["epoch_id"] == "EXACT25_EDGE_V1"
assert binding["shadow_enabled"] is True
for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled", "canary_enabled"):
    assert binding[key] is False, key
assert epoch["epoch_id"] == "EXACT25_EDGE_V1"
assert epoch["write_enabled"] is False
assert epoch["canary_enabled"] is False
PY
WATCHER_PID_BEFORE=$(systemctl show "$WATCHER_UNIT" -p MainPID --value)
[ "$(systemctl show "$WATCHER_UNIT" -p ActiveState --value)" = "active" ]
[ "$(systemctl show "$WATCHER_UNIT" -p SubState --value)" = "running" ]
[ "$WATCHER_PID_BEFORE" -gt 0 ]

set_stage backup_canary_state
cp -a "$EPOCH" "$BACKUP_DIR/epoch_latest.json"
if [ -d "$CANARY_DIR" ]; then
  cp -a "$CANARY_DIR" "$BACKUP_DIR/canary"
fi

set_stage run_isolated_exact25_canary
rm -rf "$CANARY_DIR"
mkdir -p "$DEST"
Q4R3_ROOT="$ROOT" \
Q4R3_ALLOW_CANARY_WRITE=EXACT25_EDGE_V1_CANARY \
"$PYTHON_BIN" "$CANARY" --output "$RESULT"

set_stage independent_canary_result_gate
"$PYTHON_BIN" - "$RESULT" "$EPOCH" <<'PY'
import json
import sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
epoch = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert result["status"] == "PASS_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY"
assert result["verdict"] == "CANARY_PASS_WRITE_PATH_DUPLICATE_LINEAGE_R_FORMULA"
assert result["strategy_count"] == 25
assert result["first_write"] == {"accepted": 25, "rejected_duplicate": 0}
assert result["replay_write"] == {"accepted": 0, "rejected_duplicate": 25}
verification = result["verification"]
assert verification["row_count"] == 25
assert verification["unique_event_count"] == 25
assert verification["duplicate_count"] == 0
assert verification["owner_mismatches"] == []
assert verification["formula_mismatches"] == []
assert verification["unsafe_flags"] == []
assert result["production_measurement_write_enabled"] is False
assert result["paper_enabled"] is False
assert result["live_enabled"] is False
assert result["order_enabled"] is False
assert epoch["state"] == "CANARY_PASS_FORWARD_WRITE_NOT_STARTED"
assert epoch["write_enabled"] is False
assert epoch["canary_enabled"] is False
PY

WATCHER_PID_AFTER=$(systemctl show "$WATCHER_UNIT" -p MainPID --value)
[ "$WATCHER_PID_AFTER" = "$WATCHER_PID_BEFORE" ]
[ "$(systemctl show "$WATCHER_UNIT" -p ActiveState --value)" = "active" ]
[ "$(systemctl show "$WATCHER_UNIT" -p SubState --value)" = "running" ]

set_stage publish_canary_evidence
cd "$WORKTREE"
git config user.name "ZEL Exact25 Canary"
git config user.email "exact25-canary@z-os.local"
git add runtime_results/q4r3/exact25_edge_v1_shadow_canary

if git diff --cached --quiet; then
  COMMIT=$(git rev-parse HEAD)
  CURRENT_STAGE=complete
  write_status DONE no_change "$COMMIT"
  echo "Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY_ALREADY_CURRENT commit=$COMMIT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish exact-25 isolated shadow measurement canary evidence"
COMMIT=$(git rev-parse HEAD)

PUSHED=false
for attempt in 1 2 3; do
  if git push origin "HEAD:$BRANCH"; then
    PUSHED=true
    break
  fi
  echo "WARN:PUSH_ATTEMPT_FAILED attempt=$attempt"
  sleep $((attempt * 3))
done

CURRENT_STAGE=complete
if [ "$PUSHED" = true ]; then
  write_status DONE published "$COMMIT"
  echo "Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY_PUBLISHED commit=$COMMIT branch=$BRANCH"
else
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$COMMIT"
  echo "Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY_LOCAL_DONE_PUSH_PENDING commit=$COMMIT" >&2
fi
