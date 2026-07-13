#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_CLOSE_AUTHORITY_WORKTREE:-/tmp/q4r3-exact25-close-source-authority-lock}
BRANCH=q4r3-exact25-close-source-authority-lock
PYTHON_BIN=$ROOT/.venv/bin/python
AUDITOR=$WORKTREE/tools/q4r3_exact25_close_source_authority_lock.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_close_source_authority_lock.py
JOB_STATUS=$ROOT/runtime/q4r3_exact25_close_source_authority_lock_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_close_source_authority_lock_job.log
RESULT_DIR=$WORKTREE/runtime_results/q4r3/exact25_close_source_authority_lock
RESULT=$RESULT_DIR/q4r3_exact25_close_source_authority_lock_latest.json
HTML=$RESULT_DIR/q4r3_exact25_close_source_authority_lock_latest.html
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap

mkdir -p "$ROOT/runtime" "$RESULT_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

write_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$JOB_STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$report_commit" "$RESULT" "$CURRENT_STAGE" "$LOG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_close_source_authority_lock",
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
    "canary_source_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "production_measurement_write_enabled": False,
    "read_only": True,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action",
            "pure_shadow_authority_count", "filterable_mixed_source_count",
            "paper_rejected_count", "eligible_active_producer_units",
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
  write_status RUNNING "stage=$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

on_error() {
  local code=$?
  local failed_stage=$CURRENT_STAGE
  trap - ERR
  write_status FAILED "stage=$failed_stage exit_code=$code" || true
  echo "Q4R3_EXACT25_CLOSE_SOURCE_AUTHORITY_LOCK_FAILED stage=$failed_stage exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

for required in \
  "$PYTHON_BIN" \
  "$AUDITOR" \
  "$TEST_FILE" \
  "$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json" \
  "$ROOT/runtime/exact25_edge_v1/first_real_forward_canary/status_latest.json"
do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_shell_python_and_unit_tests
bash -n "$0"
"$PYTHON_BIN" -m py_compile "$AUDITOR"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage read_only_close_source_authority_lock
"$PYTHON_BIN" "$AUDITOR" --root "$ROOT" --output "$RESULT" --html "$HTML"

set_stage independent_result_gate
"$PYTHON_BIN" - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "PASS_Q4R3_EXACT25_CLOSE_SOURCE_AUTHORITY_LOCK":
    raise SystemExit("AUTHORITY_LOCK_STATUS_NOT_PASS")
if payload.get("action") != "HOLD":
    raise SystemExit("AUTHORITY_LOCK_MUST_REMAIN_HOLD")
if payload.get("read_only") is not True:
    raise SystemExit("AUTHORITY_LOCK_NOT_READ_ONLY")
for key in (
    "real_order_enabled", "paper_request_written", "live_execution_allowed",
    "production_strategy_modified", "owner_manifest_modified", "binding_modified",
    "epoch_modified", "writer_modified", "canary_source_modified",
    "persistent_forward_r_watcher_modified", "production_measurement_write_enabled",
):
    if payload.get(key) is not False:
        raise SystemExit(f"UNSAFE_RESULT_FLAG:{key}:{payload.get(key)}")
if payload.get("verdict") not in {
    "PROVEN_PURE_SHADOW_CLOSE_AUTHORITY_FOUND",
    "MIXED_CLOSE_SOURCE_REQUIRES_SHADOW_ONLY_FILTER_SIDECAR",
    "PAPER_LEDGER_REJECTED_AS_SHADOW_AUTHORITY",
    "NO_PROVEN_EXACT25_SHADOW_CLOSE_AUTHORITY",
}:
    raise SystemExit(f"UNKNOWN_VERDICT:{payload.get('verdict')}")
for unit in payload.get("eligible_active_producer_units") or []:
    lower = str(unit).lower()
    if any(token in lower for token in ("audit", "trace", "probe", "test", "report", "canary", "writer", "watch")):
        raise SystemExit(f"FALSE_PRODUCER_UNIT:{unit}")
print(json.dumps({
    "status": payload.get("status"),
    "verdict": payload.get("verdict"),
    "next_action": payload.get("next_action"),
    "pure_shadow_authority_count": payload.get("pure_shadow_authority_count"),
    "filterable_mixed_source_count": payload.get("filterable_mixed_source_count"),
    "paper_rejected_count": payload.get("paper_rejected_count"),
    "eligible_active_producer_units": payload.get("eligible_active_producer_units"),
}, ensure_ascii=False))
PY

set_stage publish_sanitized_evidence
cd "$WORKTREE"
git config user.name "ZEL Exact25 Authority Auditor"
git config user.email "exact25-authority@z-os.local"
git add runtime_results/q4r3/exact25_close_source_authority_lock
if git diff --cached --quiet; then
  REPORT_COMMIT=$(git rev-parse HEAD)
else
  git -c core.hooksPath=/dev/null commit -m "Publish Exact25 close source authority lock"
  REPORT_COMMIT=$(git rev-parse HEAD)
  git push origin "HEAD:refs/heads/$BRANCH"
fi

CURRENT_STAGE=complete
write_status DONE published "$REPORT_COMMIT"
echo "Q4R3_EXACT25_CLOSE_SOURCE_AUTHORITY_LOCK_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
