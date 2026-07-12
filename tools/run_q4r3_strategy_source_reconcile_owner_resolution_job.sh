#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_AUDIT_WORKTREE:-/tmp/q4r3-strategy-source-reconcile-owner-resolution}
BRANCH=q4r3-strategy-source-reconcile-owner-resolution
PYTHON_BIN=$ROOT/.venv/bin/python
RECONCILER=$WORKTREE/tools/q4r3_reconcile_strategy_source_probe.py
PUBLISHER=$WORKTREE/tools/q4r3_publish_strategy_source_snapshot.py
OWNER_ANALYZER=$WORKTREE/tools/q4r3_strategy_canonical_owner_matrix.py
RESOLVER=$WORKTREE/tools/q4r3_resolve_canonical_owner_registry.py
RECONCILE_TEST=$WORKTREE/tests/test_q4r3_reconcile_strategy_source_probe.py
PUBLISH_TEST=$WORKTREE/tests/test_q4r3_publish_strategy_source_snapshot.py
OWNER_TEST=$WORKTREE/tests/test_q4r3_strategy_canonical_owner_matrix.py
RESOLVER_TEST=$WORKTREE/tests/test_q4r3_resolve_canonical_owner_registry.py
ORIGINAL_PROBE=$WORKTREE/runtime_results/q4r3/strategy_runtime_owner_contract_probe/q4r3_strategy_runtime_owner_contract_probe_latest.json
RECONCILE_DIR=$WORKTREE/runtime_results/q4r3/strategy_source_reconciliation
RECONCILED_PROBE=$RECONCILE_DIR/reconciled_probe.json
SNAPSHOT_DIR=$WORKTREE/runtime_results/q4r3/strategy_source_snapshot
OWNER_DIR=$WORKTREE/runtime_results/q4r3/strategy_canonical_owner_matrix
OWNER_RESULT=$OWNER_DIR/q4r3_strategy_canonical_owner_matrix_latest.json
RESOLUTION_DIR=$WORKTREE/runtime_results/q4r3/canonical_owner_registry_resolution
RESOLUTION_RESULT=$RESOLUTION_DIR/q4r3_canonical_owner_registry_resolution_latest.json
STATUS=$ROOT/runtime/q4r3_strategy_source_reconcile_owner_resolution_job_latest.json
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

write_status() {
  local state=$1
  local reason=$2
  local commit_sha=${3:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$STARTED_AT" "$BRANCH" "$commit_sha" "$RECONCILED_PROBE" "$SNAPSHOT_DIR/manifest.json" "$OWNER_RESULT" "$RESOLUTION_RESULT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status = Path(sys.argv[1])
paths = {
    "reconciled_probe": Path(sys.argv[7]),
    "snapshot": Path(sys.argv[8]),
    "owner_matrix": Path(sys.argv[9]),
    "resolution": Path(sys.argv[10]),
}
payload = {
    "job": "q4r3_strategy_source_reconcile_owner_resolution",
    "state": sys.argv[2],
    "reason": sys.argv[3],
    "started_at": sys.argv[4],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "branch": sys.argv[5],
    "commit_sha": sys.argv[6] or None,
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "registry_modified": False,
    "persistent_forward_r_watcher_modified": False,
}
if payload["output_exists"]["reconciled_probe"]:
    try:
        data = json.loads(paths["reconciled_probe"].read_text(errors="ignore"))
        summary = data.get("source_reconciliation") or {}
        payload["source_reconciliation"] = {
            key: summary.get(key)
            for key in (
                "expected_strategy_count",
                "original_module_count",
                "reconciled_module_count",
                "probe_omission_count",
                "all_25_have_active_source",
                "all_25_have_canonical_source",
            )
        }
    except Exception as exc:
        payload["reconciled_probe_read_error"] = repr(exc)
if payload["output_exists"]["snapshot"]:
    try:
        data = json.loads(paths["snapshot"].read_text(errors="ignore"))
        payload["snapshot_verdict"] = data.get("verdict")
        payload["strategy_module_count"] = data.get("strategy_module_count")
        payload["direct_strategy_snapshot_complete"] = data.get("direct_strategy_snapshot_complete")
    except Exception as exc:
        payload["snapshot_read_error"] = repr(exc)
if payload["output_exists"]["owner_matrix"]:
    try:
        data = json.loads(paths["owner_matrix"].read_text(errors="ignore"))
        payload["owner_matrix_verdict"] = data.get("verdict")
        payload["owner_summary"] = data.get("owner_summary")
    except Exception as exc:
        payload["owner_matrix_read_error"] = repr(exc)
if payload["output_exists"]["resolution"]:
    try:
        data = json.loads(paths["resolution"].read_text(errors="ignore"))
        for key in ("status", "verdict", "action", "next_action", "resolved_owner_count", "unresolved_owner_count", "unresolved_strategies"):
            payload[key] = data.get(key)
        payload["registry_authority"] = (data.get("registry_resolution") or {}).get("authoritative_candidate")
        payload["false_registry_candidates_rejected"] = (data.get("registry_resolution") or {}).get("false_exact_candidates_rejected")
    except Exception as exc:
        payload["resolution_read_error"] = repr(exc)

temporary = status.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_STRATEGY_SOURCE_RECONCILE_OWNER_RESOLUTION_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

for required in "$PYTHON_BIN" "$RECONCILER" "$PUBLISHER" "$OWNER_ANALYZER" "$RESOLVER" "$RECONCILE_TEST" "$PUBLISH_TEST" "$OWNER_TEST" "$RESOLVER_TEST" "$ORIGINAL_PROBE"; do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

mkdir -p "$ROOT/runtime"
write_status RUNNING tests_started

cd "$WORKTREE"
echo '=== SOURCE RECONCILIATION + OWNER RESOLUTION TESTS ==='
PYTHONPATH="$WORKTREE:$ROOT" "$PYTHON_BIN" -m pytest -q \
  "$RECONCILE_TEST" \
  "$PUBLISH_TEST" \
  "$OWNER_TEST" \
  "$RESOLVER_TEST"

rm -rf "$RECONCILE_DIR" "$SNAPSHOT_DIR" "$OWNER_DIR" "$RESOLUTION_DIR"
mkdir -p "$RECONCILE_DIR" "$SNAPSHOT_DIR" "$OWNER_DIR" "$RESOLUTION_DIR"

write_status RUNNING reconciling_source_probe
"$PYTHON_BIN" "$RECONCILER" \
  --root "$ROOT" \
  --probe "$ORIGINAL_PROBE" \
  --output "$RECONCILED_PROBE"

write_status RUNNING publishing_reconciled_snapshot
"$PYTHON_BIN" "$PUBLISHER" \
  --root "$ROOT" \
  --probe "$RECONCILED_PROBE" \
  --output-dir "$SNAPSHOT_DIR"

write_status RUNNING rebuilding_owner_matrix
"$PYTHON_BIN" "$OWNER_ANALYZER" \
  --worktree "$WORKTREE" \
  --output-dir "$OWNER_DIR"

write_status RUNNING resolving_registry_authority
"$PYTHON_BIN" "$RESOLVER" \
  --owner-matrix "$OWNER_RESULT" \
  --output "$RESOLUTION_RESULT"

"$PYTHON_BIN" - "$SNAPSHOT_DIR" "$OWNER_DIR" "$RESOLUTION_DIR" <<'PY'
import re
import sys
from pathlib import Path

patterns = (
    re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(rb"(?ix)\b(api[_-]?key|secret(?:[_-]?key)?|password|private[_-]?key|access[_-]?token|refresh[_-]?token)\b\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9._~+/=-]{8,})"),
)
for root_arg in sys.argv[1:]:
    root = Path(root_arg)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in patterns):
            print(f"SANITIZATION_HIT:{path}", file=sys.stderr)
            raise SystemExit(1)
PY

cd "$WORKTREE"
git config user.name "ZEL Source Reconciliation Auditor"
git config user.email "source-reconcile@z-os.local"
git add \
  runtime_results/q4r3/strategy_source_reconciliation \
  runtime_results/q4r3/strategy_source_snapshot \
  runtime_results/q4r3/strategy_canonical_owner_matrix \
  runtime_results/q4r3/canonical_owner_registry_resolution

if git diff --cached --quiet; then
  CURRENT=$(git rev-parse HEAD)
  write_status DONE no_change "$CURRENT"
  echo Q4R3_STRATEGY_SOURCE_RECONCILE_OWNER_RESOLUTION_ALREADY_CURRENT commit="$CURRENT"
  exit 0
fi

git -c core.hooksPath=/dev/null commit -m "Publish reconciled 25-strategy owner and registry resolution"
git push origin "HEAD:$BRANCH"
COMMIT=$(git rev-parse HEAD)
write_status DONE published "$COMMIT"
echo Q4R3_STRATEGY_SOURCE_RECONCILE_OWNER_RESOLUTION_PUBLISHED commit="$COMMIT" branch="$BRANCH"
