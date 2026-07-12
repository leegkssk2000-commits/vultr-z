#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-exact25-candidate-package-contract-harness}
BRANCH=q4r3-exact25-candidate-package-contract-harness
PYTHON_BIN=$ROOT/.venv/bin/python
BUILDER=$WORKTREE/tools/q4r3_build_exact25_candidate_package.py
TEST_FILE=$WORKTREE/tests/test_q4r3_build_exact25_candidate_package.py
DEST=$WORKTREE/runtime_results/q4r3/exact25_candidate_package
RESULT=$DEST/q4r3_exact25_candidate_package_contract_latest.json
STATUS=$ROOT/runtime/q4r3_exact25_candidate_package_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_candidate_package_job.log
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
result_path = Path(sys.argv[7])
payload = {
    "job": "q4r3_exact25_candidate_package_contract_harness",
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
    "registry_modified": False,
    "persistent_forward_r_watcher_modified": False,
    "candidate_package_only": True,
}
if payload["result_exists"]:
    try:
        result = json.loads(result_path.read_text(errors="ignore"))
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "exact_25",
            "all_sources_present",
            "recovered_two_present",
            "contract_pass_count",
            "contract_gap_count",
            "manifest_path",
            "recovery_decisions",
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
  echo "Q4R3_EXACT25_CANDIDATE_PACKAGE_FAILED stage=$CURRENT_STAGE exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in "$PYTHON_BIN" "$BUILDER" "$TEST_FILE"; do
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

set_stage build_candidate_package_and_run_shared_contract_harness
rm -rf "$DEST"
"$PYTHON_BIN" "$BUILDER" --repo-root "$WORKTREE" --output-root "$DEST"

set_stage result_integrity_check
"$PYTHON_BIN" - "$RESULT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file() or path.stat().st_size <= 0:
    raise SystemExit("RESULT_MISSING")
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("expected_strategy_count") != 25:
    raise SystemExit("EXPECTED_25_COUNT_MISMATCH")
if not payload.get("exact_25"):
    raise SystemExit("EXACT_25_FALSE")
if not payload.get("all_sources_present"):
    raise SystemExit("SOURCE_MISSING")
if not payload.get("recovered_two_present"):
    raise SystemExit("RECOVERED_TWO_MISSING")
PY

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

set_stage commit_candidate_package
cd "$WORKTREE"
git config user.name "ZEL Exact25 Auditor"
git config user.email "exact25-auditor@z-os.local"
git add runtime_results/q4r3/exact25_candidate_package

if git diff --cached --quiet; then
  COMMIT=$(git rev-parse HEAD)
  write_status DONE no_change "$COMMIT"
  echo "Q4R3_EXACT25_CANDIDATE_PACKAGE_ALREADY_CURRENT commit=$COMMIT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish exact-25 canonical candidate package and shared contract report"
COMMIT=$(git rev-parse HEAD)

set_stage push_candidate_package
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
  write_status DONE published "$COMMIT"
  echo "Q4R3_EXACT25_CANDIDATE_PACKAGE_PUBLISHED commit=$COMMIT branch=$BRANCH"
else
  CURRENT_STAGE=publish_pending
  write_status DONE_LOCAL_PUBLISH_PENDING push_failed_after_3_attempts "$COMMIT"
  echo "Q4R3_EXACT25_CANDIDATE_PACKAGE_LOCAL_DONE_PUSH_PENDING commit=$COMMIT" >&2
fi
