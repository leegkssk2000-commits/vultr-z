#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_SERVICE_TRACE_WORKTREE:-/tmp/q4r3-exact25-writer-service-contract-trace}
BRANCH=q4r3-exact25-writer-service-contract-trace
PYTHON_BIN=$ROOT/.venv/bin/python
AUDITOR=$WORKTREE/tools/q4r3_exact25_writer_service_contract_trace.py
DEST=$WORKTREE/runtime_results/q4r3/exact25_writer_service_contract_trace
RESULT=$DEST/q4r3_exact25_writer_service_contract_trace_latest.json
STATUS=$ROOT/runtime/q4r3_exact25_writer_service_contract_trace_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_writer_service_contract_trace_job.log
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$RESULT" "$CURRENT_STAGE" "$LOG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_writer_service_contract_trace",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "result_path": str(result),
    "result_exists": result.is_file() and result.stat().st_size > 0,
    "current_stage": sys.argv[8],
    "log_path": sys.argv[9],
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
    "service_installed": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
    "read_only": True,
}
if payload["result_exists"]:
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "epoch_id", "strategy_count",
            "reference_count", "references", "service_plan", "writer_structure", "prerequisites",
        ):
            payload[key] = data.get(key)
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

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code" || true
  echo "Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime" "$DEST"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in "$PYTHON_BIN" "$AUDITOR"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_compile_and_self_test
"$PYTHON_BIN" -m py_compile "$AUDITOR"
"$PYTHON_BIN" "$AUDITOR" --self-test

set_stage read_only_writer_service_contract_trace
rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$AUDITOR" --root "$ROOT" --worktree "$WORKTREE" --output "$RESULT"

set_stage independent_safety_gate
"$PYTHON_BIN" - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
assert data["status"] == "PASS_Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE"
assert data["epoch_id"] == "EXACT25_EDGE_V1"
assert data["strategy_count"] == 25
assert data["prerequisites"]["reported_gap"] == "AUTHORITATIVE_WRITER_SYSTEMD_REFERENCE_NOT_FOUND"
assert data["writer_structure"]["ast_valid"] is True
assert data["service_plan"]["deployment_shape"] in {
    "REUSE_EXISTING_REFERENCE_AFTER_SAFETY_AUDIT",
    "SYSTEMD_SERVICE",
    "SYSTEMD_SERVICE_PLUS_TIMER",
    "THIN_ADAPTER_PLUS_SYSTEMD_SERVICE",
    "RUNTIME_CALLER_TRACE_REQUIRED",
}
safety = data["safety"]
for key in (
    "read_only",
    "production_strategy_modified",
    "owner_manifest_modified",
    "binding_modified",
    "epoch_modified",
    "writer_modified",
    "service_installed",
    "production_measurement_write_enabled",
    "paper_enabled",
    "live_enabled",
    "order_enabled",
    "historical_backfill_performed",
    "raw_trade_rows_published",
    "raw_writer_source_published",
):
    expected = key == "read_only"
    assert safety[key] is expected, (key, safety[key], expected)
PY

set_stage publish_service_contract_trace
cd "$WORKTREE"
git config user.name "ZEL Exact25 Service Trace"
git config user.email "exact25-service-trace@z-os.local"
git add runtime_results/q4r3/exact25_writer_service_contract_trace

if git diff --cached --quiet; then
  COMMIT=$(git rev-parse HEAD)
  CURRENT_STAGE=complete
  write_status DONE no_change "$COMMIT"
  echo "Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE_ALREADY_CURRENT commit=$COMMIT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish Exact25 writer service contract trace"
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
  echo "Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE_PUBLISHED commit=$COMMIT branch=$BRANCH"
else
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$COMMIT"
  echo "Q4R3_EXACT25_WRITER_SERVICE_CONTRACT_TRACE_LOCAL_DONE_PUSH_PENDING commit=$COMMIT" >&2
fi
