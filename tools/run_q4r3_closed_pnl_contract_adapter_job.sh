#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-closed-pnl-adapter}
STATUS=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_job_latest.json
LOG=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PUBLISH_GITHUB_RESULTS=${Q4R3_PUBLISH_GITHUB_RESULTS:-0}
RESULT_BRANCH=${Q4R3_RESULT_BRANCH:-q4r3-runtime-results-v2}

AUDIT=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_audit_latest.json
LEDGER=$ROOT/runtime/q4r3_25_strategy_realized_r_extended_ledger_latest.json
COVERAGE=$ROOT/runtime/q4r3_25_strategy_realized_r_extended_coverage_latest.json
PORTFOLIO=$ROOT/runtime/q4r3_route_a_raschke_v3_portfolio_role_extended_latest.json
DECISION=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_decision_latest.json
HANDOFF=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_handoff_latest.json
PUBLISH=$ROOT/runtime/q4r3_closed_pnl_contract_adapter_publish_latest.json

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$AUDIT" "$LEDGER" "$COVERAGE" "$PORTFOLIO" "$DECISION" "$HANDOFF" "$PUBLISH" "$PUBLISH_GITHUB_RESULTS" "$RESULT_BRANCH" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "audit": Path(sys.argv[5]),
    "extended_ledger": Path(sys.argv[6]),
    "extended_coverage": Path(sys.argv[7]),
    "portfolio": Path(sys.argv[8]),
    "decision": Path(sys.argv[9]),
    "handoff": Path(sys.argv[10]),
    "publish": Path(sys.argv[11]),
}
publish_requested = sys.argv[12] == "1"
result_branch = sys.argv[13]
payload = {
    "job": "q4r3_closed_pnl_contract_adapter",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() and path.stat().st_size > 0 for key, path in paths.items()},
    "github_publish_requested": publish_requested,
    "github_result_branch": result_branch,
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
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "base_covered_strategy_count",
            "extended_covered_strategy_count",
            "adapter_r_ready_rows_appended",
            "contract_state_counts",
            "missing_after_adapter",
            "full_25_strategy_source_ready",
            "portfolio_role",
        ):
            payload[f"result_{key}" if key == "status" else key] = decision.get(key)
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
if paths["publish"].exists():
    try:
        publish = json.loads(paths["publish"].read_text(errors="ignore"))
        payload["github_publish_state"] = publish.get("state")
        payload["github_publish_reason"] = publish.get("reason")
        payload["github_publish_commit"] = publish.get("commit_sha")
        payload["github_publish_branch"] = publish.get("branch")
    except Exception as exc:
        payload["publish_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_CLOSED_PNL_CONTRACT_ADAPTER_JOB_FAILED exit_code=$code >&2
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
  "$WORKTREE/backend/__init__.py" \
  "$WORKTREE/backend/strategies/__init__.py" \
  "$WORKTREE/backend/strategies/_route_a_video_common.py" \
  "$WORKTREE/backend/strategies/raschke_macd_ema200.py" \
  "$WORKTREE/tools/q4r3_closed_pnl_contract_adapter.py" \
  "$WORKTREE/tools/q4r3_route_a_raschke_v3_factorial_portfolio_audit.py" \
  "$WORKTREE/tools/publish_q4r3_closed_pnl_adapter_results.sh" \
  "$WORKTREE/tests/test_q4r3_closed_pnl_contract_adapter.py" \
  "$ROOT/runtime/q4r3_25_strategy_realized_r_coverage_latest.json" \
  "$ROOT/runtime/q4r3_25_strategy_realized_r_ledger_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json"
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$AUDIT" "$LEDGER" "$COVERAGE" "$PORTFOLIO" "$DECISION" "$HANDOFF" "$PUBLISH"
write_status RUNNING tests

echo === CLOSED PNL CONTRACT ADAPTER TESTS ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" -m pytest -q tests/test_q4r3_closed_pnl_contract_adapter.py
)

write_status RUNNING classify_and_extend_canonical_r_ledger

echo === CLOSED PNL CONTRACT ADAPTER ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" tools/q4r3_closed_pnl_contract_adapter.py
)

for output in "$AUDIT" "$LEDGER" "$COVERAGE" "$PORTFOLIO" "$DECISION" "$HANDOFF"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

publish_reason=publish_not_requested
if [ "$PUBLISH_GITHUB_RESULTS" = "1" ]; then
  write_status RUNNING publish_sanitized_adapter_result
  chmod +x "$WORKTREE/tools/publish_q4r3_closed_pnl_adapter_results.sh"
  if Q4R3_RESULT_BRANCH="$RESULT_BRANCH" "$WORKTREE/tools/publish_q4r3_closed_pnl_adapter_results.sh"; then
    publish_reason=github_publish_complete
  else
    publish_reason=local_adapter_complete_github_publish_failed
  fi
fi

write_status DONE "$publish_reason"

echo === DECISION ===
jq . "$DECISION"
echo === HANDOFF ===
jq . "$HANDOFF"
echo === EXTENDED COVERAGE ===
jq '{expected_strategy_count,covered_expected_strategy_count,total_rows,adapter_rows_appended,missing_expected_strategies,full_25_strategy_source_ready}' "$COVERAGE"
echo === PUBLISH STATUS ===
if [ -s "$PUBLISH" ]; then jq . "$PUBLISH"; else echo PUBLISH_NOT_REQUESTED; fi
echo Q4R3_CLOSED_PNL_CONTRACT_ADAPTER_JOB_DONE
