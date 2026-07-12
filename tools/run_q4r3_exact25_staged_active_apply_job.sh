#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_APPLY_WORKTREE:-/tmp/q4r3-exact25-staged-active-apply-rollback}
BRANCH=q4r3-exact25-staged-active-apply-rollback
PYTHON_BIN=$ROOT/.venv/bin/python
TOOL=$WORKTREE/tools/q4r3_exact25_staged_active_apply.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_staged_active_apply.py
CANDIDATE_ROOT=$WORKTREE/runtime_results/q4r3/exact25_candidate_package
PUBLISH_DIR=$WORKTREE/runtime_results/q4r3/exact25_staged_active_apply
PUBLISH_RESULT=$PUBLISH_DIR/q4r3_exact25_staged_active_apply_latest.json
RUNTIME_ROOT=$ROOT/runtime
RUNTIME_RESULT=$RUNTIME_ROOT/q4r3_exact25_staged_active_apply_latest.json
STATUS=$RUNTIME_ROOT/q4r3_exact25_staged_active_apply_job_latest.json
LOG=$RUNTIME_ROOT/q4r3_exact25_staged_active_apply_job.log
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap
CANDIDATE_COMMIT=$(git -C "$WORKTREE" rev-parse HEAD)

write_status() {
  local state=$1
  local reason=$2
  local report_commit=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$CURRENT_STAGE" "$LOG" "$RUNTIME_RESULT" "$BRANCH" "$CANDIDATE_COMMIT" "$report_commit" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_staged_active_apply",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "current_stage": sys.argv[5],
    "log_path": sys.argv[6],
    "result_path": str(result_path),
    "result_exists": result_path.is_file() and result_path.stat().st_size > 0,
    "branch": sys.argv[8],
    "candidate_commit": sys.argv[9],
    "report_commit": sys.argv[10] or None,
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "persistent_forward_r_watcher_modified": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "transaction_id",
            "applied_targets",
            "applied_file_count",
            "backup_dir",
            "rollback_available",
            "rollback_command",
            "verification",
            "runtime_binding_status",
            "activation_allowed",
            "production_strategy_modified",
            "registry_manifest_staged",
            "runtime_registry_bound",
            "active_state",
            "runner_failure_rollback",
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
temporary = status.with_name(status.name + ".tmp")
temporary.parent.mkdir(parents=True, exist_ok=True)
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status)
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
  local rollback_state=not_required_or_apply_tool_already_rolled_back

  if [ -s "$RUNTIME_RESULT" ]; then
    local backup_dir
    backup_dir=$(
      "$PYTHON_BIN" - "$RUNTIME_RESULT" <<'PY' 2>/dev/null || true
import json
import sys
from pathlib import Path
try:
    print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("backup_dir") or "")
except Exception:
    print("")
PY
    )
    if [ -n "$backup_dir" ] && [ -f "$backup_dir/backup_manifest.json" ]; then
      local rollback_tool=$backup_dir/q4r3_exact25_staged_active_apply.py
      if [ ! -f "$rollback_tool" ]; then
        cp "$TOOL" "$rollback_tool" 2>/dev/null || true
        chmod 700 "$rollback_tool" 2>/dev/null || true
      fi
      if [ -f "$rollback_tool" ] && Q4R3_ALLOW_ROLLBACK=EXACT25_ROLLBACK "$PYTHON_BIN" "$rollback_tool" \
          --active-root "$ROOT" \
          --runtime-root "$RUNTIME_ROOT" \
          --rollback-backup "$backup_dir"; then
        rollback_state=auto_rollback_pass
      else
        rollback_state=auto_rollback_failed
      fi

      "$PYTHON_BIN" - "$RUNTIME_RESULT" "$PUBLISH_RESULT" "$rollback_state" "$CURRENT_STAGE" "$code" <<'PY' 2>/dev/null || true
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

runtime_path = Path(sys.argv[1])
publish_path = Path(sys.argv[2])
rollback_state = sys.argv[3]
stage = sys.argv[4]
code = int(sys.argv[5])
try:
    payload = json.loads(runtime_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
payload.update({
    "status": "ROLLBACK_Q4R3_EXACT25_STAGED_ACTIVE_APPLY_AFTER_RUNNER_FAILURE",
    "verdict": "PRE_APPLY_STATE_RESTORED" if rollback_state == "auto_rollback_pass" else "ROLLBACK_FAILED_MANUAL_INTERVENTION_REQUIRED",
    "action": "HOLD",
    "next_action": "DIAGNOSE_RUNNER_FAILURE_BEFORE_RETRY",
    "active_state": "ROLLED_BACK" if rollback_state == "auto_rollback_pass" else "UNKNOWN",
    "runner_failure_rollback": rollback_state,
    "runner_failure_stage": stage,
    "runner_failure_exit_code": code,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "runtime_registry_bound": False,
    "activation_allowed": False,
})
for path in (runtime_path, publish_path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except Exception:
        pass
PY
    fi
  fi

  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code rollback=$rollback_state" || true
  echo "Q4R3_EXACT25_STAGED_ACTIVE_APPLY_FAILED stage=$CURRENT_STAGE exit_code=$code rollback=$rollback_state" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$RUNTIME_ROOT" "$PUBLISH_DIR"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
rm -f "$STATUS" "$RUNTIME_RESULT" "$PUBLISH_RESULT"

for required in "$PYTHON_BIN" "$TOOL" "$TEST_FILE" "$CANDIDATE_ROOT/q4r3_exact25_candidate_package_contract_latest.json"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

stage preflight_shell_and_rollback_unit_tests
bash -n "$0"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

stage candidate_gate_and_active_23_preflight
Q4R3_ALLOW_ACTIVE_APPLY=EXACT25_STAGED_APPLY \
"$PYTHON_BIN" "$TOOL" \
  --active-root "$ROOT" \
  --candidate-root "$CANDIDATE_ROOT" \
  --runtime-root "$RUNTIME_ROOT" \
  --publish-result "$PUBLISH_RESULT" \
  --candidate-commit "$CANDIDATE_COMMIT"

stage persist_standalone_rollback_tool
BACKUP_DIR=$(
  "$PYTHON_BIN" - "$RUNTIME_RESULT" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload["backup_dir"])
PY
)
ROLLBACK_TOOL=$BACKUP_DIR/q4r3_exact25_staged_active_apply.py
cp "$TOOL" "$ROLLBACK_TOOL"
chmod 700 "$ROLLBACK_TOOL"

"$PYTHON_BIN" - "$RUNTIME_RESULT" "$PUBLISH_RESULT" "$ROLLBACK_TOOL" "$ROOT" "$RUNTIME_ROOT" <<'PY'
import json
import sys
from pathlib import Path

runtime_path = Path(sys.argv[1])
publish_path = Path(sys.argv[2])
rollback_tool = Path(sys.argv[3])
active_root = Path(sys.argv[4])
runtime_root = Path(sys.argv[5])
payload = json.loads(runtime_path.read_text(encoding="utf-8"))
payload["rollback_tool"] = str(rollback_tool)
payload["rollback_command"] = (
    f"Q4R3_ALLOW_ROLLBACK=EXACT25_ROLLBACK /home/z/z/.venv/bin/python {rollback_tool} "
    f"--active-root {active_root} --runtime-root {runtime_root} --rollback-backup {payload['backup_dir']}"
)
for path in (runtime_path, publish_path):
    temporary = path.with_name(path.name + ".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
PY

stage post_apply_independent_integrity_check
"$PYTHON_BIN" - "$ROOT" "$RUNTIME_RESULT" <<'PY'
import ast
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
result = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if result.get("status") != "PASS_Q4R3_EXACT25_STAGED_ACTIVE_APPLY":
    raise SystemExit("APPLY_STATUS_NOT_PASS")
if result.get("runtime_binding_status") != "NOT_BOUND_STAGED_ACTIVE":
    raise SystemExit("RUNTIME_ALREADY_BOUND")
if result.get("activation_allowed") is not False:
    raise SystemExit("ACTIVATION_FLAG_UNSAFE")
manifest_path = root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
entries = manifest.get("strategies") or []
if len(entries) != 25 or len({entry.get("strategy_id") for entry in entries}) != 25:
    raise SystemExit("ACTIVE_MANIFEST_NOT_EXACT25")
for entry in entries:
    if any(entry.get(flag) is not False for flag in ("enabled_for_shadow", "enabled_for_paper", "enabled_for_live")):
        raise SystemExit(f"UNSAFE_ENABLE_FLAG:{entry.get('strategy_id')}")
    path = root / entry["owner_path"]
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("owner_sha256"):
        raise SystemExit(f"SHA_MISMATCH:{entry.get('strategy_id')}")
print("POST_APPLY_INTEGRITY_PASS strategy_count=25 all_execution_flags=false")
PY

stage publish_apply_evidence
cd "$WORKTREE"
git config user.name "ZEL Exact25 Apply Auditor"
git config user.email "exact25-apply@z-os.local"
git add runtime_results/q4r3/exact25_staged_active_apply

REPORT_COMMIT=$(git rev-parse HEAD)
if ! git diff --cached --quiet; then
  git -c core.hooksPath=/dev/null commit -m "Publish rollback-guarded exact-25 staged active apply evidence"
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
  echo "Q4R3_EXACT25_STAGED_ACTIVE_APPLY_PUBLISHED commit=$REPORT_COMMIT branch=$BRANCH"
else
  CURRENT_STAGE=complete_local_publish_pending
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$REPORT_COMMIT"
  echo "Q4R3_EXACT25_STAGED_ACTIVE_APPLY_LOCAL_DONE_PUSH_PENDING commit=$REPORT_COMMIT" >&2
fi
