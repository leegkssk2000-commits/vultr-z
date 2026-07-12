#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-source-snapshot-review}
BRANCH=q4r3-strategy-source-snapshot-review
PYTHON_BIN=$ROOT/.venv/bin/python
PUBLISHER=$WORKTREE/tools/q4r3_publish_strategy_source_snapshot.py
TEST_FILE=$WORKTREE/tests/test_q4r3_publish_strategy_source_snapshot.py
PROBE=$WORKTREE/runtime_results/q4r3/strategy_runtime_owner_contract_probe/q4r3_strategy_runtime_owner_contract_probe_latest.json
DEST=$WORKTREE/runtime_results/q4r3/strategy_source_snapshot
RESULT=$DEST/manifest.json
STATUS=$ROOT/runtime/q4r3_strategy_source_snapshot_publish_job_latest.json
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
    'job': 'q4r3_strategy_source_snapshot_publish',
    'state': sys.argv[2],
    'reason': sys.argv[3],
    'started_at': sys.argv[4],
    'updated_at': datetime.now(timezone.utc).isoformat(),
    'branch': sys.argv[5],
    'commit_sha': sys.argv[6] or None,
    'result_path': str(result_path),
    'result_exists': result_path.exists() and result_path.stat().st_size > 0,
    'order_authority': 'blocked',
    'execution_authority': 'none',
    'real_order_enabled': False,
    'paper_request_written': False,
    'live_execution_allowed': False,
    'production_strategy_modified': False,
    'persistent_forward_r_watcher_modified': False,
}
if payload['result_exists']:
    try:
        result = json.loads(result_path.read_text(errors='ignore'))
        for key in (
            'status', 'verdict', 'action', 'next_action', 'expected_strategy_count',
            'strategy_module_count', 'published_file_count', 'published_total_bytes',
            'skipped_file_count', 'direct_strategy_snapshot_complete',
        ):
            payload[key] = result.get(key)
    except Exception as exc:
        payload['result_read_error'] = repr(exc)
tmp = status.with_suffix('.json.tmp')
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(status)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_STRATEGY_SOURCE_SNAPSHOT_PUBLISH_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$PUBLISHER" "$TEST_FILE" "$PROBE"; do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

mkdir -p "$ROOT/runtime"
write_status RUNNING snapshot_started

cd "$WORKTREE"
echo '=== STRATEGY SOURCE SNAPSHOT TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE"

rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$PUBLISHER" --root "$ROOT" --probe "$PROBE" --output-dir "$DEST"

"$PYTHON_BIN" - "$PUBLISHER" "$DEST/source" <<'PY'
import importlib.util
import sys
from pathlib import Path

publisher_path = Path(sys.argv[1])
source_root = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('q4r3_source_snapshot_verifier', publisher_path)
if spec is None or spec.loader is None:
    raise SystemExit('PUBLISHER_IMPORT_FAILED')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

hits = []
for path in source_root.rglob('*'):
    if not path.is_file():
        continue
    findings = module.sensitive_findings(path, path.read_bytes())
    if findings:
        hits.append({'path': str(path.relative_to(source_root)), 'findings': findings})
if hits:
    for hit in hits:
        print(f"SENSITIVE_SNAPSHOT_HIT:{hit}", file=sys.stderr)
    raise SystemExit(1)
PY

cd "$WORKTREE"
git config user.name 'ZEL Strategy Source Publisher'
git config user.email 'strategy-source@z-os.local'
git add runtime_results/q4r3/strategy_source_snapshot
if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_SOURCE_SNAPSHOT_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m 'Publish sanitized 25-strategy source snapshot'
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_SOURCE_SNAPSHOT_PUBLISHED commit="$COMMIT" branch="$BRANCH"
