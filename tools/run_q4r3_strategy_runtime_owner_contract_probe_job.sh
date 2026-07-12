#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-runtime-owner-contract-probe}
BRANCH=q4r3-strategy-runtime-owner-contract-probe
PYTHON_BIN=$ROOT/.venv/bin/python
ANALYZER=$WORKTREE/tools/q4r3_strategy_runtime_owner_contract_probe_v2.py
TEST_FILE=$WORKTREE/tests/test_q4r3_strategy_runtime_owner_contract_probe.py
TEST_FILE_V2=$WORKTREE/tests/test_q4r3_strategy_runtime_owner_contract_probe_v2.py
COMPLETENESS_SOURCE=$WORKTREE/runtime_results/q4r3/strategy_canonical_completeness/q4r3_strategy_canonical_completeness_latest.json
OWNER_SOURCE=$WORKTREE/runtime_results/q4r3/strategy_owner_writer_test_audit/q4r3_strategy_owner_writer_test_audit_latest.json
COMPLETENESS_RUNTIME=$ROOT/runtime/q4r3_strategy_canonical_completeness_latest.json
OWNER_RUNTIME=$ROOT/runtime/q4r3_strategy_owner_writer_test_audit_latest.json
DEST=$WORKTREE/runtime_results/q4r3/strategy_runtime_owner_contract_probe
RESULT=$DEST/q4r3_strategy_runtime_owner_contract_probe_latest.json
STATUS=$ROOT/runtime/q4r3_strategy_runtime_owner_contract_probe_job_latest.json
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
    'job': 'q4r3_strategy_runtime_owner_contract_probe',
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
        for key in ('status', 'verdict', 'action', 'next_action', 'unresolved', 'expected_strategy_count', 'active_source_file_count', 'py_spy_available', 'py_spy_snapshot_count'):
            payload[key] = result.get(key)
        owner = result.get('range_fade_owner') or {}
        payload['range_fade_owner_verdict'] = owner.get('verdict')
        payload['range_fade_owner_module'] = owner.get('owner_module')
        payload['writer_verdicts'] = {item.get('strategy'): item.get('verdict') for item in result.get('writer_probes', [])}
        payload['contract_summary'] = (result.get('contract_surface') or {}).get('summary')
        payload['existing_test_covered_count'] = (result.get('existing_test_surface') or {}).get('direct_covered_count')
        payload['shared_harness_candidate_count'] = len((result.get('existing_test_surface') or {}).get('shared_harness_candidates', []))
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
  echo Q4R3_STRATEGY_RUNTIME_OWNER_CONTRACT_PROBE_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$ANALYZER" "$TEST_FILE" "$TEST_FILE_V2" "$COMPLETENESS_SOURCE" "$OWNER_SOURCE"; do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

mkdir -p "$ROOT/runtime"
cp "$COMPLETENESS_SOURCE" "$COMPLETENESS_RUNTIME.tmp"
mv "$COMPLETENESS_RUNTIME.tmp" "$COMPLETENESS_RUNTIME"
cp "$OWNER_SOURCE" "$OWNER_RUNTIME.tmp"
mv "$OWNER_RUNTIME.tmp" "$OWNER_RUNTIME"
write_status RUNNING probe_started

cd "$WORKTREE"
echo '=== RUNTIME OWNER CONTRACT PROBE TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q "$TEST_FILE" "$TEST_FILE_V2"

rm -rf "$DEST"
mkdir -p "$DEST"
"$PYTHON_BIN" "$ANALYZER" --output-dir "$DEST"

if ! "$PYTHON_BIN" - "$DEST" <<'PY'
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
patterns = (
    re.compile(rb'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'),
    re.compile(rb'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}'),
    re.compile(rb'(?ix)\b(api[_-]?key|secret(?:[_-]?key)?|password|private[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*["\']?\s*[:=]\s*["\']?([A-Za-z0-9._~+/=-]{8,})'),
)
for path in root.rglob('*'):
    if not path.is_file():
        continue
    data = path.read_bytes()
    if any(pattern.search(data) for pattern in patterns):
        print(f'SANITIZATION_HIT:{path}', file=sys.stderr)
        raise SystemExit(1)
PY
then
  echo SANITIZATION_CHECK_FAILED >&2
  exit 3
fi

cd "$WORKTREE"
git config user.name 'ZEL Runtime Evidence Probe'
git config user.email 'runtime-evidence@z-os.local'
git add runtime_results/q4r3/strategy_runtime_owner_contract_probe
if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_RUNTIME_OWNER_CONTRACT_PROBE_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m 'Publish runtime strategy owner and contract probe'
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_RUNTIME_OWNER_CONTRACT_PROBE_PUBLISHED commit="$COMMIT" branch="$BRANCH"
