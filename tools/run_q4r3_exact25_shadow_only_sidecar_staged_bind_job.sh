#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_BIND_WORKTREE:-/tmp/q4r3-exact25-shadow-only-sidecar-staged-bind}
BRANCH=q4r3-exact25-shadow-only-sidecar-staged-bind
PYTHON_BIN=$ROOT/.venv/bin/python
BINDER=$WORKTREE/tools/q4r3_exact25_shadow_only_sidecar_staged_bind.py
TEST_FILE=$WORKTREE/tests/test_q4r3_exact25_shadow_only_sidecar_staged_bind.py
ACTIVE_RESULT=$ROOT/runtime/q4r3_exact25_shadow_only_sidecar_bind_latest.json
DEST=$WORKTREE/runtime_results/q4r3/exact25_shadow_only_sidecar_bind
PUBLISHED_RESULT=$DEST/q4r3_exact25_shadow_only_sidecar_bind_latest.json
STATUS=$ROOT/runtime/q4r3_exact25_shadow_only_sidecar_bind_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_shadow_only_sidecar_bind_job.log
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=bootstrap

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$ACTIVE_RESULT" "$CURRENT_STAGE" "$LOG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_shadow_only_sidecar_staged_bind",
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
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "persistent_forward_r_watcher_modified": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for key in (
            "status", "verdict", "action", "next_action", "transaction_id", "backup_dir",
            "rollback_available", "rollback_command", "strategy_count", "dry_run_pass_count",
            "dry_run_gap_count", "epoch_id", "epoch_state", "preexisting_data_label",
            "shadow_sidecar_bound", "core_runtime_registry_bound", "shadow_enabled",
            "write_enabled", "canary_enabled", "paper_enabled", "live_enabled", "order_enabled",
            "authoritative_writer",
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

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code" || true
  echo "Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_BIND_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in "$PYTHON_BIN" "$BINDER" "$TEST_FILE"; do
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

set_stage rollback_guarded_shadow_sidecar_staged_apply
rm -f "$ACTIVE_RESULT"
"$PYTHON_BIN" "$BINDER" \
  --active-root "$ROOT" \
  --worktree "$WORKTREE" \
  --result "$ACTIVE_RESULT" \
  --apply-token Q4R3_EXACT25_SHADOW_BIND_DRYRUN_ONLY

set_stage independent_post_apply_integrity_gate
"$PYTHON_BIN" - "$ACTIVE_RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
required = {
    "status": "PASS_Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_STAGED_BIND",
    "verdict": "EXACT25_SHADOW_SIDECAR_BOUND_DRYRUN_PASS_CANARY_NOT_STARTED",
    "strategy_count": 25,
    "dry_run_pass_count": 25,
    "dry_run_gap_count": 0,
    "epoch_id": "EXACT25_EDGE_V1",
    "epoch_state": "CREATED_DRYRUN_ONLY_NOT_STARTED",
    "preexisting_data_label": "PRE_EXACT25",
    "shadow_sidecar_bound": True,
    "core_runtime_registry_bound": False,
    "shadow_enabled": True,
    "write_enabled": False,
    "canary_enabled": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "production_strategy_modified": False,
    "owner_manifest_modified": False,
    "persistent_forward_r_watcher_modified": False,
}
for key, value in required.items():
    if payload.get(key) != value:
        raise SystemExit(f"POST_APPLY_GATE_MISMATCH:{key}:{payload.get(key)!r}:{value!r}")
if payload.get("watcher_before", {}).get("MainPID") != payload.get("watcher_after", {}).get("MainPID"):
    raise SystemExit("WATCHER_PID_CHANGED")
if payload.get("authoritative_writer", {}).get("secondary_close_writer_mode") != "OBSERVER_ONLY_NOT_BOUND":
    raise SystemExit("SECONDARY_WRITER_MODE_UNSAFE")
if payload.get("rollback_available") is not True:
    raise SystemExit("ROLLBACK_NOT_AVAILABLE")
PY

set_stage publish_bind_evidence
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$ACTIVE_RESULT" "$PUBLISHED_RESULT"
cp "$ROOT/runtime/exact25_edge_v1/dry_run_latest.json" "$DEST/q4r3_exact25_edge_v1_dry_run_latest.json"
cp "$ROOT/runtime/exact25_edge_v1/epoch_latest.json" "$DEST/q4r3_exact25_edge_v1_epoch_latest.json"

set_stage sanitization_check
"$PYTHON_BIN" - "$DEST" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(rb"(?ix)\b(api[_-]?key|secret(?:[_-]?key)?|password|private[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9._~+/=-]{8,})"),
)
for path in root.rglob("*"):
    if not path.is_file():
        continue
    data = path.read_bytes()
    if any(pattern.search(data) for pattern in patterns):
        print(f"SANITIZATION_HIT:{path}", file=sys.stderr)
        raise SystemExit(1)
PY

set_stage commit_and_push_evidence
cd "$WORKTREE"
git config user.name "ZEL Exact25 Shadow Binder"
git config user.email "exact25-shadow-binder@z-os.local"
git add runtime_results/q4r3/exact25_shadow_only_sidecar_bind

if git diff --cached --quiet; then
  COMMIT=$(git rev-parse HEAD)
  CURRENT_STAGE=complete
  write_status DONE no_change "$COMMIT"
  echo "Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_BIND_ALREADY_CURRENT commit=$COMMIT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish exact-25 shadow-only sidecar staged bind evidence"
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
  echo "Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_BIND_PUBLISHED commit=$COMMIT branch=$BRANCH"
else
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$COMMIT"
  echo "Q4R3_EXACT25_SHADOW_ONLY_SIDECAR_BIND_LOCAL_DONE_PUSH_PENDING commit=$COMMIT" >&2
fi
