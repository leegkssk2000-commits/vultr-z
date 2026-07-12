#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-25-strategy-ledger}
STATUS=$ROOT/runtime/q4r3_route_a_25_strategy_realized_ledger_bind_job_latest.json
LOG=$ROOT/runtime/q4r3_route_a_25_strategy_realized_ledger_bind_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

CANONICAL=$ROOT/runtime/q4r3_25_strategy_realized_r_ledger_latest.json
COVERAGE=$ROOT/runtime/q4r3_25_strategy_realized_r_coverage_latest.json
SOURCE=$ROOT/runtime/q4r3_25_strategy_realized_r_source_audit_latest.json
PORTFOLIO=$ROOT/runtime/q4r3_route_a_raschke_v3_portfolio_role_rebound_latest.json
DECISION=$ROOT/runtime/q4r3_25_strategy_realized_r_bind_decision_latest.json
HTML=$ROOT/runtime/q4r3_25_strategy_realized_r_bind_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$CANONICAL" "$COVERAGE" "$SOURCE" "$PORTFOLIO" "$DECISION" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "canonical": Path(sys.argv[5]),
    "coverage": Path(sys.argv[6]),
    "source_audit": Path(sys.argv[7]),
    "portfolio": Path(sys.argv[8]),
    "decision": Path(sys.argv[9]),
    "html": Path(sys.argv[10]),
}
payload = {
    "job": "q4r3_route_a_25_strategy_realized_ledger_bind",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
    "final_holdout_opened": False,
}
if paths["decision"].exists():
    try:
        decision = json.loads(paths["decision"].read_text(errors="ignore"))
        payload["result_status"] = decision.get("status")
        payload["verdict"] = decision.get("verdict")
        payload["action"] = decision.get("action")
        payload["expected_universe_exact_25"] = decision.get("expected_universe_exact_25")
        payload["expected_strategy_count"] = decision.get("expected_strategy_count")
        payload["covered_expected_strategy_count"] = decision.get("covered_expected_strategy_count")
        payload["canonical_row_count"] = decision.get("canonical_row_count")
        payload["missing_expected_strategies"] = decision.get("missing_expected_strategies")
        payload["portfolio_role"] = decision.get("portfolio_role")
        payload["full_25_strategy_source_ready"] = decision.get("full_25_strategy_source_ready")
        payload["next_modules"] = decision.get("next_modules")
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_25_STRATEGY_REALIZED_LEDGER_BIND_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

mkdir -p $ROOT/runtime
: > $LOG
exec > >(tee -a $LOG) 2>&1

for required in \
  $WORKTREE/backend/__init__.py \
  $WORKTREE/backend/strategies/__init__.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v3_factorial_portfolio_audit.py \
  $WORKTREE/tools/q4r3_route_a_25_strategy_realized_ledger_bind.py \
  $WORKTREE/tests/test_q4r3_25_strategy_realized_ledger_bind.py \
  $ROOT/runtime/q4r3_route_a_raschke_v3_sparse_factorial_latest.json \
  $ROOT/runtime/q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json \
  $ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$CANONICAL" "$COVERAGE" "$SOURCE" "$PORTFOLIO" "$DECISION" "$HTML"
write_status RUNNING tests

echo === 25 STRATEGY REALIZED R LEDGER BIND TESTS ===
PYTHONPATH=$WORKTREE:$ROOT Q4R3_ROUTE_A_OVERLAY_ROOT=$WORKTREE Q4R3_ROUTE_A_WORKTREE=$WORKTREE $PYTHON_BIN -m pytest -q $WORKTREE/tests/test_q4r3_25_strategy_realized_ledger_bind.py

write_status RUNNING universe_discovery_canonical_bind_portfolio_rerun

echo === 25 STRATEGY REALIZED R LEDGER BIND ===
PYTHONPATH=$WORKTREE:$ROOT Q4R3_ROUTE_A_OVERLAY_ROOT=$WORKTREE Q4R3_ROUTE_A_WORKTREE=$WORKTREE $PYTHON_BIN $WORKTREE/tools/q4r3_route_a_25_strategy_realized_ledger_bind.py

for attempt in $(seq 1 30); do
  ready=true
  for output in "$CANONICAL" "$COVERAGE" "$SOURCE" "$PORTFOLIO" "$DECISION" "$HTML"; do
    if [ ! -s "$output" ]; then
      ready=false
      break
    fi
  done
  if [ "$ready" = true ]; then
    break
  fi
  sleep 1
done

for output in "$CANONICAL" "$COVERAGE" "$SOURCE" "$PORTFOLIO" "$DECISION" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE canonical_25_strategy_ledger_and_portfolio_rerun_complete

echo === DECISION ===
jq . "$DECISION"
echo === COVERAGE ===
jq '{expected_strategy_count,covered_expected_strategy_count,observed_strategy_count,total_rows,duplicate_rows_removed,missing_expected_strategies,unexpected_observed_strategies,full_25_strategy_source_ready,by_strategy}' "$COVERAGE"
echo === UNIVERSE ===
jq '{selected_source:.universe.selected_source,selected_key:.universe.selected_key,expected_strategy_count:.universe.expected_strategy_count,exact_25_found:.universe.exact_25_found,expected_strategies:.universe.expected_strategies,top_candidates:.universe.top_candidates}' "$CANONICAL"
echo === SOURCES WITH ROWS ===
jq '{files_scanned,files_with_rows,accepted_rows,files:[.files[]|select(.accepted_rows>0)]}' "$SOURCE"
echo === PORTFOLIO ROLE REBOUND ===
jq . "$PORTFOLIO"
echo Q4R3_25_STRATEGY_REALIZED_LEDGER_BIND_JOB_DONE
