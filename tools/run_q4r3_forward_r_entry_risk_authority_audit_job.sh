#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-entry-risk-audit}
STATUS=$ROOT/runtime/q4r3_forward_r_entry_risk_authority_job_latest.json
LOG=$ROOT/runtime/q4r3_forward_r_entry_risk_authority_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

AUDIT=$ROOT/runtime/q4r3_forward_r_entry_risk_authority_latest.json
DECISION=$ROOT/runtime/q4r3_forward_r_entry_risk_decision_latest.json
HTML=$ROOT/runtime/q4r3_forward_r_entry_risk_authority_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$AUDIT" "$DECISION" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {'audit': Path(sys.argv[5]), 'decision': Path(sys.argv[6]), 'html': Path(sys.argv[7])}
payload = {
    'job': 'q4r3_forward_r_entry_risk_authority_audit',
    'state': state,
    'reason': reason,
    'started_at': started_at,
    'updated_at': datetime.now(timezone.utc).isoformat(),
    'outputs': {key: str(path) for key, path in paths.items()},
    'output_exists': {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
    'order_authority': 'blocked',
    'execution_authority': 'none',
    'real_order_enabled': False,
    'paper_request_written': False,
    'live_execution_allowed': False,
    'production_strategy_modified': False,
    'final_holdout_opened': False,
}
if paths['decision'].exists():
    try:
        decision = json.loads(paths['decision'].read_text(errors='ignore'))
        for key in ('status', 'verdict', 'action', 'next_action', 'stable_id_join_rate_pct', 'authoritative_open_row_count', 'explicit_risk_ready_count', 'formula_ready_from_price_stop_qty_count', 'dominant_single_entry_writer', 'dominant_entry_writer', 'next_modules'):
            payload[f'result_{key}' if key == 'status' else key] = decision.get(key)
    except Exception as exc:
        payload['decision_read_error'] = repr(exc)
tmp = status_path.with_suffix('.json.tmp')
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_FORWARD_R_ENTRY_RISK_AUTHORITY_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in \
  "$WORKTREE/tools/q4r3_forward_r_entry_risk_authority_audit.py" \
  "$WORKTREE/tests/test_q4r3_forward_r_entry_risk_authority_audit.py" \
  "$ROOT/runtime/q4r3_forward_r_source_authority_latest.json" \
  "$ROOT/runtime/q4r3_forward_r_writer_lineage_latest.json" \
  "$ROOT/runtime/q4r3_forward_r_source_lineage_decision_latest.json"
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$AUDIT" "$DECISION" "$HTML"
write_status RUNNING tests

echo === FORWARD R ENTRY RISK AUTHORITY TESTS ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
    "$PYTHON_BIN" -m pytest -q tests/test_q4r3_forward_r_entry_risk_authority_audit.py
)

write_status RUNNING trace_authoritative_entry_risk_writer

echo === FORWARD R ENTRY RISK AUTHORITY AUDIT ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" Q4R3_ROUTE_A_WORKTREE="$WORKTREE" Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
    "$PYTHON_BIN" tools/q4r3_forward_r_entry_risk_authority_audit.py
)

for output in "$AUDIT" "$DECISION" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE entry_risk_authority_and_writer_lineage_complete

echo === DECISION ===
jq . "$DECISION"
echo === ENTRY RISK AUTHORITY ===
jq '{stable_id_join_rate_pct,authoritative_open_source_count,authoritative_open_row_count,explicit_risk_ready_count,formula_ready_from_price_stop_qty_count,entry_price_ready_count,stop_price_ready_count,qty_ready_count,dominant_single_entry_writer,dominant_entry_writer,second_score,source_rows,production_candidates:[.production_candidates[0:15][]]}' "$AUDIT"
echo Q4R3_FORWARD_R_ENTRY_RISK_AUTHORITY_JOB_DONE
