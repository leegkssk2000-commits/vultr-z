#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
RESULT_BRANCH=${Q4R3_RESULT_BRANCH:-q4r3-runtime-results-v2}
PUBLISH_WORKTREE=${Q4R3_RESULT_WORKTREE:-/tmp/q4r3-runtime-results-v2-publish}
HANDOFF=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_handoff_latest.json
DECISION=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_decision_latest.json
PUBLISH_STATUS=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_publish_latest.json
DEST_DIR=$PUBLISH_WORKTREE/runtime_results/q4r3
CURRENT_STEP=init

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$PUBLISH_STATUS" "$state" "$reason" "$commit_sha" "$RESULT_BRANCH" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "job": "q4r3_closed_pnl_contract_adapter_publish",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "commit_sha": sys.argv[4] or None,
    "branch": sys.argv[5],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "published_files": [
        "runtime_results/q4r3/closed_pnl_contract_adapter_handoff_latest.json",
        "runtime_results/q4r3/closed_pnl_contract_adapter_decision_latest.json",
        "runtime_results/q4r3/closed_pnl_contract_adapter_manifest_latest.json",
    ],
    "sanitized_only": True,
    "raw_runtime_published": False,
}
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "${CURRENT_STEP}_exit_${code}" || true
  echo Q4R3_CLOSED_PNL_ADAPTER_PUBLISH_FAILED step=$CURRENT_STEP exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

write_status RUNNING preflight

CURRENT_STEP=validate_sanitized_inputs
if [ ! -s "$HANDOFF" ] || [ ! -s "$DECISION" ]; then
  write_status FAILED missing_sanitized_inputs
  exit 2
fi

CURRENT_STEP=verify_remote_branch
cd "$ROOT"
if ! git ls-remote --exit-code --heads origin "refs/heads/$RESULT_BRANCH" >/dev/null 2>&1; then
  write_status FAILED remote_result_branch_missing
  exit 3
fi

CURRENT_STEP=fetch_result_branch
git fetch origin "$RESULT_BRANCH"
CURRENT_STEP=prepare_result_worktree
git worktree remove --force "$PUBLISH_WORKTREE" 2>/dev/null || true
rm -rf "$PUBLISH_WORKTREE"
git worktree add -B "$RESULT_BRANCH" "$PUBLISH_WORKTREE" "origin/$RESULT_BRANCH"

CURRENT_STEP=write_sanitized_files
mkdir -p "$DEST_DIR"
cp "$HANDOFF" "$DEST_DIR/closed_pnl_contract_adapter_handoff_latest.json"
cp "$DECISION" "$DEST_DIR/closed_pnl_contract_adapter_decision_latest.json"

"$PYTHON_BIN" - "$HANDOFF" "$DECISION" "$DEST_DIR/closed_pnl_contract_adapter_manifest_latest.json" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

handoff = Path(sys.argv[1])
decision = Path(sys.argv[2])
out = Path(sys.argv[3])

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

payload = {
    "schema": "q4r3_sanitized_runtime_manifest_v2",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "source_job": "q4r3_closed_pnl_contract_adapter",
    "files": {
        "closed_pnl_contract_adapter_handoff_latest.json": digest(handoff),
        "closed_pnl_contract_adapter_decision_latest.json": digest(decision),
    },
    "sanitized_only": True,
    "raw_runtime_published": False,
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

CURRENT_STEP=commit_result
cd "$PUBLISH_WORKTREE"
git config user.name "ZEL Runtime Publisher"
git config user.email "runtime-publisher@z-os.local"
git add runtime_results/q4r3
if git diff --cached --quiet; then
  current=$(git rev-parse HEAD)
  write_status DONE no_change "$current"
  echo Q4R3_CLOSED_PNL_ADAPTER_RESULT_NO_CHANGE commit=$current branch=$RESULT_BRANCH
  exit 0
fi

git commit -m "Publish sanitized closed-PnL adapter result"
CURRENT_STEP=push_result
git push origin "HEAD:$RESULT_BRANCH"
commit_sha=$(git rev-parse HEAD)
write_status DONE published "$commit_sha"
echo Q4R3_CLOSED_PNL_ADAPTER_RESULT_PUBLISHED commit=$commit_sha branch=$RESULT_BRANCH
