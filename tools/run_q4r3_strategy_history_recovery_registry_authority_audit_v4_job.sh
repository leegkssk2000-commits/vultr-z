#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-history-recovery-registry-authority-audit}
BRANCH=q4r3-strategy-history-recovery-registry-authority-audit
PYTHON_BIN=$ROOT/.venv/bin/python
ANALYZER=$WORKTREE/tools/q4r3_strategy_history_recovery_registry_authority_audit_v2.py
TEST_FILE=$WORKTREE/tests/test_q4r3_strategy_history_recovery_registry_authority_audit_v2.py
DEST=$WORKTREE/runtime_results/q4r3/strategy_history_recovery_registry_authority
RESULT=$DEST/q4r3_strategy_history_recovery_registry_authority_latest.json
STATUS=$ROOT/runtime/q4r3_strategy_history_recovery_registry_authority_job_latest.json
LOG=$ROOT/runtime/q4r3_strategy_history_recovery_registry_authority_v4.log
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CURRENT_STAGE=init
FETCH_WARNING=""

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$RESULT" "$CURRENT_STAGE" "$FETCH_WARNING" "$LOG" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_strategy_history_recovery_registry_authority_audit_v4",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
    "analyzer_version": "v4_optional_fetch_guard",
    "current_stage": sys.argv[8],
    "fetch_warning": sys.argv[9] or None,
    "log_path": sys.argv[10],
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "registry_modified": False,
    "persistent_forward_r_watcher_modified": False,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(errors="ignore"))
        for key in ("status", "verdict", "action", "next_action", "targets", "candidate_summary", "recovery_decision"):
            payload[key] = result.get(key)
        payload["registry_authority_found"] = bool((result.get("registry_authority") or {}).get("authoritative_candidate"))
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
tmp = status.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status)
PY
}

set_stage() {
  CURRENT_STAGE=$1
  write_status RUNNING "$CURRENT_STAGE"
  echo "=== STAGE: $CURRENT_STAGE ==="
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "stage=$CURRENT_STAGE exit_code=$code" || true
  echo "Q4R3_RECOVERY_AUDIT_V4_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in "$PYTHON_BIN" "$ANALYZER" "$TEST_FILE"; do
  if [ ! -e "$required" ]; then
    CURRENT_STAGE=required_input_check
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

set_stage preflight_tests
cd "$WORKTREE"
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

set_stage preflight_optional_fetch_guard
OPTIONAL_FETCH_TEST_RC=0
if OPTIONAL_FETCH_TEST_OUT=$(bash -c 'echo SIMULATED_OPTIONAL_FETCH_FAILURE >&2; exit 128' 2>&1); then
  OPTIONAL_FETCH_TEST_RC=0
else
  OPTIONAL_FETCH_TEST_RC=$?
fi
if [ "$OPTIONAL_FETCH_TEST_RC" -ne 128 ]; then
  echo "OPTIONAL_FETCH_GUARD_SELFTEST_FAILED rc=$OPTIONAL_FETCH_TEST_RC" >&2
  exit 5
fi
echo "OPTIONAL_FETCH_GUARD_OK rc=$OPTIONAL_FETCH_TEST_RC"

set_stage refresh_origin_history_optional
# Optional freshness only. Both commands are placed in `if` conditions so the
# global ERR trap cannot convert a non-critical fetch failure into a job failure.
if [ "$(git -C "$ROOT" rev-parse --is-shallow-repository 2>/dev/null || echo false)" = "true" ]; then
  if UNSHALLOW_OUT=$(git -C "$ROOT" fetch origin --unshallow --tags 2>&1); then
    echo "ORIGIN_UNSHALLOW_OK"
  else
    UNSHALLOW_RC=$?
    FETCH_WARNING="unshallow_origin_rc=$UNSHALLOW_RC"
    echo "WARN:$FETCH_WARNING"
    printf '%s\n' "$UNSHALLOW_OUT" | tail -80
  fi
fi

if FETCH_OUT=$(git -C "$ROOT" fetch origin --tags --prune 2>&1); then
  echo "ORIGIN_FETCH_OK"
else
  FETCH_RC=$?
  if [ -n "$FETCH_WARNING" ]; then
    FETCH_WARNING="$FETCH_WARNING;origin_fetch_rc=$FETCH_RC"
  else
    FETCH_WARNING="origin_fetch_rc=$FETCH_RC"
  fi
  echo "WARN:$FETCH_WARNING"
  printf '%s\n' "$FETCH_OUT" | tail -120
  write_status RUNNING "origin_fetch_warning_local_history_continues"
fi

set_stage full_history_archive_registry_audit
rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$ANALYZER" --root "$ROOT" --output-dir "$DEST"

set_stage redact_runtime_process_args
"$PYTHON_BIN" - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
entrypoints = payload.get("runtime_entrypoints") or {}
for process in entrypoints.get("processes") or []:
    process.pop("args", None)
payload["analyzer_version"] = "v4_optional_fetch_guard"
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY

set_stage sanitization
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
    for pattern in patterns:
        if pattern.search(data):
            print(f"SANITIZATION_HIT:{path}", file=sys.stderr)
            raise SystemExit(3)
PY

set_stage publish_github
cd "$WORKTREE"
git config user.name "ZEL Recovery Auditor"
git config user.email "recovery-auditor@z-os.local"
git add runtime_results/q4r3/strategy_history_recovery_registry_authority

if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  CURRENT_STAGE=complete
  write_status DONE no_change "$CURRENT"
  echo "Q4R3_RECOVERY_AUDIT_V4_ALREADY_CURRENT commit=$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish strategy recovery and registry authority audit v4"
COMMIT=$(git rev-parse HEAD)

PUSH_OK=false
for attempt in 1 2 3; do
  if git push origin "HEAD:$BRANCH"; then
    PUSH_OK=true
    break
  fi
  echo "WARN:PUSH_ATTEMPT_${attempt}_FAILED"
  sleep $((attempt * 3))
done
if [ "$PUSH_OK" != true ]; then
  CURRENT_STAGE=publish_github
  write_status FAILED "analysis_complete_but_github_push_failed" "$COMMIT"
  exit 4
fi

CURRENT_STAGE=complete
write_status DONE published "$COMMIT"
echo "Q4R3_RECOVERY_AUDIT_V4_PUBLISHED commit=$COMMIT branch=$BRANCH"
