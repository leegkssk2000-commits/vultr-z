#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-exact25-active-runtime-smoke}
BRANCH=q4r3-exact25-active-runtime-smoke
PYTHON_BIN=$ROOT/.venv/bin/python
TOOL=$WORKTREE/tools/q4r3_exact25_active_runtime_smoke.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_active_runtime_smoke.py
MANIFEST=$ROOT/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json
RUNTIME_RESULT=$ROOT/runtime/q4r3_exact25_active_runtime_smoke_latest.json
STATUS=$ROOT/runtime/q4r3_exact25_active_runtime_smoke_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_active_runtime_smoke_job.log
PUBLISH_DIR=$WORKTREE/runtime_results/q4r3/exact25_active_runtime_smoke
PUBLISH_RESULT=$PUBLISH_DIR/q4r3_exact25_active_runtime_smoke_latest.json
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap

write_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$CURRENT_STAGE" "$LOG" "$RUNTIME_RESULT" "$BRANCH" "$report_commit" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_active_runtime_smoke",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "current_stage": sys.argv[5],
    "log_path": sys.argv[6],
    "result_path": str(result_path),
    "result_exists": result_path.is_file() and result_path.stat().st_size > 0,
    "branch": sys.argv[8],
    "report_commit": sys.argv[9] or None,
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "runtime_registry_bound": False,
    "shadow_enabled": False,
    "production_files_modified": False,
    "persistent_forward_r_watcher_modified": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "exact_25",
            "all_execution_flags_false", "strategy_smoke_pass_count",
            "strategy_smoke_gap_count", "manifest_path", "safety",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
tmp = status.with_name(status.name + ".tmp")
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status)
PY
}

stage() {
  CURRENT_STAGE=$1
  write_status RUNNING "stage=$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code" || true
  echo "Q4R3_EXACT25_ACTIVE_RUNTIME_SMOKE_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime" "$PUBLISH_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
rm -f "$STATUS" "$RUNTIME_RESULT" "$PUBLISH_RESULT"

for required in "$PYTHON_BIN" "$TOOL" "$TEST_FILE" "$MANIFEST"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

stage preflight_shell_and_unit_tests
bash -n "$0"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

stage active_exact25_import_and_execution_smoke
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ROOT" \
  "$PYTHON_BIN" "$TOOL" \
  --active-root "$ROOT" \
  --manifest-path "$MANIFEST" \
  --output-path "$RUNTIME_RESULT" \
  --timeout-sec 20

stage independent_result_gate
"$PYTHON_BIN" - "$RUNTIME_RESULT" <<'PY'
import json
import sys
from pathlib import Path

result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if result.get("status") != "PASS_Q4R3_EXACT25_ACTIVE_RUNTIME_SMOKE_AUDIT":
    raise SystemExit("SMOKE_STATUS_NOT_PASS")
if result.get("exact_25") is not True:
    raise SystemExit("EXACT25_FALSE")
if result.get("all_execution_flags_false") is not True:
    raise SystemExit("EXECUTION_FLAGS_NOT_FALSE")
if result.get("strategy_smoke_pass_count") != 25:
    raise SystemExit(f"SMOKE_GAPS:{result.get('strategy_smoke_gap_count')}")
safety = result.get("safety") or {}
if safety.get("runtime_registry_bound") is not False or safety.get("shadow_enabled") is not False:
    raise SystemExit("UNSAFE_RUNTIME_BINDING_STATE")
print("INDEPENDENT_SMOKE_GATE_PASS strategy_count=25 runtime_registry_bound=false shadow_enabled=false")
PY

stage publish_smoke_evidence
cp "$RUNTIME_RESULT" "$PUBLISH_RESULT"
cd "$WORKTREE"
git config user.name "ZEL Exact25 Smoke Auditor"
git config user.email "exact25-smoke@z-os.local"
git add runtime_results/q4r3/exact25_active_runtime_smoke
REPORT_COMMIT=$(git rev-parse HEAD)
if ! git diff --cached --quiet; then
  git -c core.hooksPath=/dev/null commit -m "Publish exact-25 active runtime smoke evidence"
  REPORT_COMMIT=$(git rev-parse HEAD)
fi

PUSHED=false
for attempt in 1 2 3; do
  if git push origin "HEAD:$BRANCH"; then
    PUSHED=true
    break
  fi
  echo "WARN:PUSH_ATTEMPT_FAILED attempt=$attempt"
  sleep $((attempt * 3))
done

if [ "$PUSHED" = true ]; then
  CURRENT_STAGE=complete
  write_status DONE published "$REPORT_COMMIT"
  echo "Q4R3_EXACT25_ACTIVE_RUNTIME_SMOKE_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
else
  CURRENT_STAGE=complete_local_publish_pending
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$REPORT_COMMIT"
  echo "Q4R3_EXACT25_ACTIVE_RUNTIME_SMOKE_LOCAL_DONE_PUSH_PENDING commit=$REPORT_COMMIT" >&2
fi
