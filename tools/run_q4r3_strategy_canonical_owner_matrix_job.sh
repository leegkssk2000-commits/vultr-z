#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-canonical-owner-matrix}
BRANCH=q4r3-strategy-canonical-owner-matrix
PYTHON_BIN=$ROOT/.venv/bin/python
ANALYZER=$WORKTREE/tools/q4r3_strategy_canonical_owner_matrix.py
TEST_FILE=$WORKTREE/tests/test_q4r3_strategy_canonical_owner_matrix.py
DEST=$WORKTREE/runtime_results/q4r3/strategy_canonical_owner_matrix
STATUS=$ROOT/runtime/q4r3_strategy_canonical_owner_matrix_job_latest.json
RESULT=$DEST/q4r3_strategy_canonical_owner_matrix_latest.json
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
    "job": "q4r3_strategy_canonical_owner_matrix",
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
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "expected_strategy_count",
            "source_snapshot_complete",
            "owner_summary",
            "registry_audit",
        ):
            value = result.get(key)
            if key == "registry_audit" and isinstance(value, dict):
                payload["registry_verdict"] = value.get("verdict")
                payload["registry_authoritative_candidate"] = value.get("authoritative_candidate")
            else:
                payload[key] = value
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
temp = status.with_suffix(".json.tmp")
temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temp.replace(status)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_STRATEGY_CANONICAL_OWNER_MATRIX_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$ANALYZER" "$TEST_FILE"; do
  if [ ! -e "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

SNAPSHOT=$WORKTREE/runtime_results/q4r3/strategy_source_snapshot/manifest.json
if [ ! -s "$SNAPSHOT" ]; then
  echo SOURCE_SNAPSHOT_MISSING:$SNAPSHOT >&2
  exit 2
fi

mkdir -p "$ROOT/runtime"
write_status RUNNING owner_matrix_started

cd "$WORKTREE"
echo '=== CANONICAL OWNER MATRIX TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$ANALYZER" --worktree "$WORKTREE" --output-dir "$DEST"

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
    if any(pattern.search(data) for pattern in patterns):
        print(f"SANITIZATION_HIT:{path}", file=sys.stderr)
        raise SystemExit(1)
PY
then
  echo SANITIZATION_CHECK_FAILED >&2
  exit 3
fi

cd "$WORKTREE"
git config user.name "ZEL Canonical Owner Auditor"
git config user.email "canonical-owner-auditor@z-os.local"
git add runtime_results/q4r3/strategy_canonical_owner_matrix

if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_CANONICAL_OWNER_MATRIX_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish 25-strategy canonical owner matrix"
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_CANONICAL_OWNER_MATRIX_PUBLISHED commit="$COMMIT" branch="$BRANCH"
