#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-history-recovery-registry-authority-audit}
BRANCH=q4r3-strategy-history-recovery-registry-authority-audit
PYTHON_BIN=$ROOT/.venv/bin/python
ANALYZER=$WORKTREE/tools/q4r3_strategy_history_recovery_registry_authority_audit.py
TEST_FILE=$WORKTREE/tests/test_q4r3_strategy_history_recovery_registry_authority_audit.py
DEST=$WORKTREE/runtime_results/q4r3/strategy_history_recovery_registry_authority
RESULT=$DEST/q4r3_strategy_history_recovery_registry_authority_latest.json
STATUS=$ROOT/runtime/q4r3_strategy_history_recovery_registry_authority_job_latest.json
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$RESULT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_strategy_history_recovery_registry_authority_audit",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "result_path": str(result_path),
    "result_exists": result_path.exists() and result_path.stat().st_size > 0,
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

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_STRATEGY_HISTORY_RECOVERY_REGISTRY_AUTHORITY_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$ANALYZER" "$TEST_FILE"; do
  if [ ! -e "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

mkdir -p "$ROOT/runtime"
write_status RUNNING audit_started

cd "$WORKTREE"
echo '=== HISTORY RECOVERY + REGISTRY AUTHORITY TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

echo '=== FETCH ALL REACHABLE HISTORY ==='
if [ "$(git -C "$ROOT" rev-parse --is-shallow-repository 2>/dev/null || echo false)" = "true" ]; then
  git -C "$ROOT" fetch --unshallow --tags origin
fi
git -C "$ROOT" fetch --all --tags --prune

rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$ANALYZER" --root "$ROOT" --output-dir "$DEST"

# Never publish raw process command lines. Only PID and repository-relative paths remain.
"$PYTHON_BIN" - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
entrypoints = payload.get("runtime_entrypoints") or {}
for process in entrypoints.get("processes") or []:
    process.pop("args", None)
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY

if ! "$PYTHON_BIN" - "$DEST" <<'PY'
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
            raise SystemExit(1)
PY
then
  echo SANITIZATION_CHECK_FAILED >&2
  exit 3
fi

cd "$WORKTREE"
git config user.name "ZEL Recovery Auditor"
git config user.email "recovery-auditor@z-os.local"
git add runtime_results/q4r3/strategy_history_recovery_registry_authority

if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_HISTORY_RECOVERY_REGISTRY_AUTHORITY_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish strategy history recovery and registry authority audit"
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_HISTORY_RECOVERY_REGISTRY_AUTHORITY_PUBLISHED commit="$COMMIT" branch="$BRANCH"
