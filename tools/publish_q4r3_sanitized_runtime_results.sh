#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
RESULT_BRANCH=${Q4R3_RESULT_BRANCH:-q4r3-runtime-results}
PUBLISH_WORKTREE=${Q4R3_RESULT_WORKTREE:-/tmp/q4r3-runtime-results-publish}
HANDOFF=$ROOT/runtime/q4r3_missing_strategy_writer_trace_handoff_latest.json
DECISION=$ROOT/runtime/q4r3_missing_strategy_writer_trace_decision_latest.json
PUBLISH_STATUS=$ROOT/runtime/q4r3_missing_strategy_writer_trace_publish_latest.json
DEST_DIR=$PUBLISH_WORKTREE/runtime_results/q4r3

PYTHON_BIN=$ROOT/.venv/bin/python

write_publish_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  $PYTHON_BIN - "$PUBLISH_STATUS" "$state" "$reason" "$commit_sha" "$RESULT_BRANCH" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "job": "q4r3_sanitized_runtime_result_publish",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "commit_sha": sys.argv[4] or None,
    "branch": sys.argv[5],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "published_files": [
        "runtime_results/q4r3/missing_strategy_writer_trace_handoff_latest.json",
        "runtime_results/q4r3/missing_strategy_writer_trace_decision_latest.json",
        "runtime_results/q4r3/manifest_latest.json",
    ],
    "sanitized_only": True,
}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
PY
}

if [ ! -s "$HANDOFF" ] || [ ! -s "$DECISION" ]; then
  write_publish_status FAILED missing_sanitized_inputs
  exit 2
fi

cd "$ROOT"
git fetch origin "$RESULT_BRANCH"
git worktree remove --force "$PUBLISH_WORKTREE" 2>/dev/null || true
rm -rf "$PUBLISH_WORKTREE"
git worktree add -B "$RESULT_BRANCH" "$PUBLISH_WORKTREE" "origin/$RESULT_BRANCH"

mkdir -p "$DEST_DIR"
cp "$HANDOFF" "$DEST_DIR/missing_strategy_writer_trace_handoff_latest.json"
cp "$DECISION" "$DEST_DIR/missing_strategy_writer_trace_decision_latest.json"

$PYTHON_BIN - "$HANDOFF" "$DECISION" "$DEST_DIR/manifest_latest.json" <<'PY'
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
    "schema": "q4r3_sanitized_runtime_manifest_v1",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "source_job": "q4r3_missing_strategy_writer_trace",
    "files": {
        "missing_strategy_writer_trace_handoff_latest.json": digest(handoff),
        "missing_strategy_writer_trace_decision_latest.json": digest(decision),
    },
    "sanitized_only": True,
    "raw_runtime_published": False,
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

cd "$PUBLISH_WORKTREE"
git config user.name "ZEL Runtime Publisher"
git config user.email "runtime-publisher@z-os.local"
git add runtime_results/q4r3

if git diff --cached --quiet; then
  current=$(git rev-parse HEAD)
  write_publish_status DONE no_change "$current"
  exit 0
fi

git commit -m "Publish sanitized Q4R3 writer trace result"
git push origin "HEAD:$RESULT_BRANCH"
commit_sha=$(git rev-parse HEAD)
write_publish_status DONE published "$commit_sha"
echo Q4R3_SANITIZED_RUNTIME_RESULT_PUBLISHED commit=$commit_sha branch=$RESULT_BRANCH
