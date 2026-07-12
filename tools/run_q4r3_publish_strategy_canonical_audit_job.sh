#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-canonical-audit-results}
BRANCH=q4r3-strategy-canonical-audit-results
PYTHON_BIN=$ROOT/.venv/bin/python
PUBLISHER=$WORKTREE/tools/q4r3_publish_strategy_canonical_audit.py
TEST_FILE=$WORKTREE/tests/test_q4r3_publish_strategy_canonical_audit.py
DEST=$WORKTREE/runtime_results/q4r3/strategy_canonical_audit
STATUS=$ROOT/runtime/q4r3_strategy_canonical_audit_publish_latest.json
SOURCE=${Q4R3_CANONICAL_AUDIT_SOURCE:-}

if [ -z "$SOURCE" ]; then
  SOURCE=$(find /root -maxdepth 1 -type f -name 'Z_STRATEGY_CANONICAL_AUDIT_*.txt' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
fi

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$SOURCE" "$BRANCH" "$commit_sha" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
source = Path(sys.argv[4]) if sys.argv[4] else None
payload = {
    "job": "q4r3_strategy_canonical_audit_publish",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "source": str(source) if source else None,
    "source_exists": bool(source and source.is_file()),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "published_path": "runtime_results/q4r3/strategy_canonical_audit",
    "sanitized_only": True,
    "raw_audit_published": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "production_strategy_modified": False,
}
tmp = status.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_STRATEGY_CANONICAL_AUDIT_PUBLISH_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$PUBLISHER" "$TEST_FILE"; do
  if [ ! -e "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done
if [ -z "$SOURCE" ] || [ ! -s "$SOURCE" ]; then
  echo SOURCE_AUDIT_MISSING:${SOURCE:-none} >&2
  exit 2
fi

cd "$WORKTREE"
echo '=== STRATEGY CANONICAL AUDIT PUBLISH TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$PUBLISHER" --source "$SOURCE" --output-dir "$DEST"

if ! "$PYTHON_BIN" - "$DEST" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = (
    ("pem_private_key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "assigned_secret",
        re.compile(
            rb"(?ix)\b(api[_-]?key|secret(?:[_-]?key)?|password|private[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9._~+/=-]{8,})"
        ),
    ),
)

hits = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    data = path.read_bytes()
    for label, pattern in patterns:
        if pattern.search(data):
            hits.append((str(path.relative_to(root)), label))

if hits:
    for rel, label in hits:
        print(f"SANITIZATION_HIT file={rel} pattern={label}", file=sys.stderr)
    raise SystemExit(1)
PY
then
  write_status FAILED sanitization_check_failed
  echo SANITIZATION_CHECK_FAILED >&2
  exit 3
fi

cd "$WORKTREE"
git config user.name "ZEL Audit Publisher"
git config user.email "audit-publisher@z-os.local"
git add runtime_results/q4r3/strategy_canonical_audit

if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_CANONICAL_AUDIT_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git commit -m "Publish sanitized strategy canonical audit"
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_CANONICAL_AUDIT_PUBLISHED commit="$COMMIT" branch="$BRANCH"
