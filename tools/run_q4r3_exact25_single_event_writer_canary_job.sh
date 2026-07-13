#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_SINGLE_EVENT_WORKTREE:-/tmp/q4r3-exact25-single-event-writer-canary}
BRANCH=q4r3-exact25-single-event-writer-canary
PYTHON_BIN=$ROOT/.venv/bin/python
ADAPTER=$WORKTREE/tools/q4r3_exact25_single_event_measurement_adapter.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_single_event_measurement_adapter.py
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
PRODUCER_STATUS=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/status_latest.json
CLOSE_SURFACE=$ROOT/runtime/exact25_edge_v1/dedicated_shadow_producer/close_latest.json
MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
FAILED_CANARY_STATUS=$ROOT/runtime/exact25_edge_v1/first_real_forward_canary/status_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_single_event_writer_canary_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_single_event_writer_canary_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_single_event_writer_canary
RESULT=$RESULT_DIR/q4r3_exact25_single_event_writer_canary_latest.json
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TRANSACTION_ID=$(date -u +%Y%m%dT%H%M%S.%NZ)
CANARY_ROOT=$ROOT/runtime/exact25_edge_v1/single_event_writer_canary/$TRANSACTION_ID
LEDGER=$CANARY_ROOT/ledger.jsonl
FIRST_RECEIPT=$CANARY_ROOT/first_receipt.json
REPLAY_RECEIPT=$CANARY_ROOT/replay_receipt.json
CURRENT_STAGE=bootstrap
ROLLBACK_DONE=false

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_job_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" "$CANARY_ROOT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_single_event_writer_canary",
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
    "canary_root": sys.argv[10],
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "binding_modified": False,
    "epoch_modified": False,
    "production_measurement_write_enabled": False,
    "historical_backfill_allowed": False,
    "isolated_canary_only": True,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "accepted_count",
            "duplicate_rejected_count", "ledger_row_count", "formula_verified",
            "owner_lineage_verified", "producer_pid_unchanged", "producer_active",
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

rollback() {
  if [ "$ROLLBACK_DONE" = true ]; then return 0; fi
  ROLLBACK_DONE=true
  trap - ERR
  echo "=== ROLLBACK ==="
  rm -rf "$CANARY_ROOT"
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  rollback || true
  CURRENT_STAGE=$failed_stage
  write_job_status FAILED "stage=$failed_stage exit_code=$code rollback=true" || true
  echo "Q4R3_EXACT25_SINGLE_EVENT_WRITER_CANARY_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" \
  "$ADAPTER" \
  "$TEST_FILE" \
  "$PRODUCER_STATUS" \
  "$CLOSE_SURFACE" \
  "$MANIFEST" \
  "$FAILED_CANARY_STATUS"
do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_python_and_unit_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$ADAPTER"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage failed_canary_and_producer_prerequisite_gate
PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
if [ -z "$PRODUCER_PID_BEFORE" ] || [ "$PRODUCER_PID_BEFORE" = 0 ]; then
  echo "PRODUCER_MAIN_PID_INVALID:$PRODUCER_PID_BEFORE" >&2
  exit 3
fi
if ! systemctl is-active --quiet "$PRODUCER_UNIT"; then
  echo "PRODUCER_NOT_ACTIVE" >&2
  exit 3
fi

MIN_EVENT_EPOCH=$(
  "$PYTHON_BIN" - "$FAILED_CANARY_STATUS" "$PRODUCER_STATUS" "$CLOSE_SURFACE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

failed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
producer = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
surface = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))

if failed.get("state") != "FAILED_BLOCKED_ROLLED_BACK":
    raise SystemExit(f"EXPECTED_FAILED_ROLLED_BACK_STATE:{failed.get('state')}")
if failed.get("rollback_complete") is not True:
    raise SystemExit("FAILED_CANARY_ROLLBACK_NOT_COMPLETE")
error = str(failed.get("error") or "")
if "WRITER_NEW_ROW_COUNT:" not in error:
    raise SystemExit(f"UNEXPECTED_FAILED_CANARY_ERROR:{error}")
if int(failed.get("writer_invocation_count") or 0) != 1:
    raise SystemExit(f"EXPECTED_ONE_WRITER_INVOCATION:{failed.get('writer_invocation_count')}")
if producer.get("state") != "RUNNING":
    raise SystemExit(f"PRODUCER_STATUS_NOT_RUNNING:{producer.get('state')}")
if int(producer.get("close_event_count") or 0) < 1:
    raise SystemExit("NO_DEDICATED_CLOSE_EVENT")
rows = surface.get("rows")
if not isinstance(rows, list) or not rows:
    raise SystemExit("CLOSE_SURFACE_ROWS_EMPTY")
started = failed.get("started_at") or producer.get("started_at")
if not started:
    raise SystemExit("CANARY_START_TIMESTAMP_MISSING")
parsed = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)
print(parsed.timestamp())
PY
)

set_stage create_isolated_single_event_namespace
mkdir -p "$CANARY_ROOT"

set_stage first_exact_one_event_write
"$PYTHON_BIN" "$ADAPTER" \
  --close-surface "$CLOSE_SURFACE" \
  --manifest "$MANIFEST" \
  --ledger "$LEDGER" \
  --receipt "$FIRST_RECEIPT" \
  --min-event-epoch "$MIN_EVENT_EPOCH"

set_stage replay_duplicate_rejection
"$PYTHON_BIN" "$ADAPTER" \
  --close-surface "$CLOSE_SURFACE" \
  --manifest "$MANIFEST" \
  --ledger "$LEDGER" \
  --receipt "$REPLAY_RECEIPT" \
  --min-event-epoch "$MIN_EVENT_EPOCH"

set_stage independent_integrity_gate
PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
"$PYTHON_BIN" - "$FIRST_RECEIPT" "$REPLAY_RECEIPT" "$LEDGER" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" <<'PY'
import json
import math
import sys
from pathlib import Path

first = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
replay = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
ledger_path = Path(sys.argv[3])
if first.get("state") != "ACCEPTED" or first.get("accepted_count") != 1 or first.get("row_delta") != 1:
    raise SystemExit(f"FIRST_WRITE_NOT_EXACT_ONE:{first}")
if replay.get("state") != "DUPLICATE_REJECTED" or replay.get("duplicate_rejected_count") != 1 or replay.get("row_delta") != 0:
    raise SystemExit(f"REPLAY_NOT_REJECTED:{replay}")
rows = []
for line in ledger_path.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    if isinstance(row, dict):
        rows.append(row)
if len(rows) != 1:
    raise SystemExit(f"LEDGER_ROW_COUNT_NOT_ONE:{len(rows)}")
row = rows[0]
for key in ("event_id", "position_id", "strategy_id", "owner_sha256", "symbol", "side", "entry_ts", "exit_ts"):
    if not row.get(key):
        raise SystemExit(f"LEDGER_REQUIRED_FIELD_MISSING:{key}")
risk = float(row["initial_risk_usdt"])
pnl = float(row["realized_pnl_usdt"])
r_value = float(row["realized_R"])
if not all(math.isfinite(value) for value in (risk, pnl, r_value)) or risk <= 0:
    raise SystemExit("LEDGER_NUMERIC_CONTRACT_INVALID")
expected = pnl / risk
if abs(r_value - expected) > max(1e-10, abs(expected) * 1e-9):
    raise SystemExit("LEDGER_R_FORMULA_INVALID")
if row.get("owner_lineage_verified") is not True or row.get("formula_verified") is not True:
    raise SystemExit("LEDGER_VERIFICATION_FLAGS_FALSE")
for key in ("paper_enabled", "live_enabled", "order_enabled"):
    if row.get(key) is not False:
        raise SystemExit(f"LEDGER_UNSAFE_FLAG:{key}")
if sys.argv[4] != sys.argv[5] or sys.argv[4] in {"", "0"}:
    raise SystemExit(f"PRODUCER_PID_CHANGED:{sys.argv[4]}:{sys.argv[5]}")
print("SINGLE_EVENT_INTEGRITY_PASS")
PY

set_stage publish_result
"$PYTHON_BIN" - "$RESULT" "$FIRST_RECEIPT" "$REPLAY_RECEIPT" "$LEDGER" "$PRODUCER_PID_BEFORE" "$PRODUCER_PID_AFTER" "$CANARY_ROOT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

result_path = Path(sys.argv[1])
first = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
replay = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
ledger_path = Path(sys.argv[4])
rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
row = rows[0]
payload = {
    "schema": "q4r3_exact25_single_event_writer_canary_result_v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS_Q4R3_EXACT25_SINGLE_EVENT_WRITER_CANARY",
    "verdict": "EXACT_ONE_FORWARD_CLOSE_ACCEPTED_REPLAY_DUPLICATE_REJECTED",
    "action": "HOLD",
    "next_action": "INSTALL_ROLLBACK_GUARDED_PERSISTENT_SINGLE_EVENT_FORWARD_WRITER_SHADOW_ONLY_AND_EXPAND_TO_EXACT5",
    "epoch_id": "EXACT25_EDGE_V1",
    "measurement_namespace": "EXACT25_EDGE_V1",
    "accepted_count": first.get("accepted_count"),
    "duplicate_rejected_count": replay.get("duplicate_rejected_count"),
    "ledger_row_count": len(rows),
    "event_hash": first.get("event_hash"),
    "strategy_id": row.get("strategy_id"),
    "symbol": row.get("symbol"),
    "formula_verified": row.get("formula_verified") is True,
    "owner_lineage_verified": row.get("owner_lineage_verified") is True,
    "initial_risk_positive": float(row.get("initial_risk_usdt")) > 0,
    "producer_active": "active",
    "producer_pid_before": int(sys.argv[5]),
    "producer_pid_after": int(sys.argv[6]),
    "producer_pid_unchanged": sys.argv[5] == sys.argv[6],
    "isolated_canary_root": sys.argv[7],
    "old_bulk_writer_invoked": False,
    "old_failed_canary_reenabled": False,
    "production_measurement_write_enabled": False,
    "historical_backfill_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}
result_path.parent.mkdir(parents=True, exist_ok=True)
tmp = result_path.with_suffix(result_path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(result_path)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

set_stage commit_and_push_evidence
cd "$WORKTREE"
git add "$RESULT"
if git diff --cached --quiet; then
  echo "NO_RESULT_CHANGE_TO_COMMIT"
else
  git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" \
    commit -m "Publish exact-one-event writer canary evidence"
fi
git push origin HEAD:"$BRANCH"
REPORT_COMMIT=$(git rev-parse HEAD)

CURRENT_STAGE=complete
write_job_status DONE published "$REPORT_COMMIT"
trap - ERR
ROLLBACK_DONE=true

echo "Q4R3_EXACT25_SINGLE_EVENT_WRITER_CANARY_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
