#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-v3-factorial-portfolio}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_job_latest.json
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FACTORIAL=$ROOT/runtime/q4r3_route_a_raschke_v3_sparse_factorial_latest.json
TRADES=$ROOT/runtime/q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json
INVENTORY=$ROOT/runtime/q4r3_route_a_raschke_v3_portfolio_source_inventory_latest.json
PORTFOLIO=$ROOT/runtime/q4r3_route_a_raschke_v3_portfolio_role_latest.json
DECISION=$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json
TRIAL=$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_trial_latest.json
HTML=$ROOT/runtime/raschke_v3_factorial_portfolio_audit_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$FACTORIAL" "$TRADES" "$INVENTORY" "$PORTFOLIO" "$DECISION" "$TRIAL" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "factorial": Path(sys.argv[5]),
    "trades": Path(sys.argv[6]),
    "inventory": Path(sys.argv[7]),
    "portfolio": Path(sys.argv[8]),
    "decision": Path(sys.argv[9]),
    "trial": Path(sys.argv[10]),
    "html": Path(sys.argv[11]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_factorial_portfolio_audit",
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
        payload["independent_gate_pass_candidates"] = decision.get("independent_gate_pass_candidates")
        payload["best_independent_candidate"] = decision.get("best_independent_candidate")
        payload["portfolio_role"] = decision.get("portfolio_role")
        payload["portfolio_source_strategy_count"] = decision.get("portfolio_source_strategy_count")
        payload["full_25_strategy_conclusion_allowed"] = decision.get("full_25_strategy_conclusion_allowed")
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
  echo RASCHKE_V3_FACTORIAL_PORTFOLIO_JOB_FAILED exit_code=$code >&2
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
  $WORKTREE/backend/strategies/_route_a_video_common.py \
  $WORKTREE/backend/strategies/raschke_macd_ema200.py \
  $WORKTREE/tools/q4r3_route_a_video_fidelity_tournament.py \
  $WORKTREE/tools/q4r3_route_a_raschke_forensic_rescue.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v3_2r_rescue_tournament.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v3_factorial_portfolio_audit.py \
  $WORKTREE/tests/test_raschke_v3_factorial_portfolio_audit.py
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    $ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json \
    $ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json
  do
    if [ ! -s "$path" ]; then
      echo CONSUMED_RAW_MISSING:$path >&2
      exit 2
    fi
  done
done

rm -f "$FACTORIAL" "$TRADES" "$INVENTORY" "$PORTFOLIO" "$DECISION" "$TRIAL" "$HTML"
write_status RUNNING tests

echo === RASCHKE V3 FACTORIAL PORTFOLIO TESTS ===
PYTHONPATH=$WORKTREE:$ROOT Q4R3_ROUTE_A_OVERLAY_ROOT=$WORKTREE Q4R3_ROUTE_A_WORKTREE=$WORKTREE $PYTHON_BIN -m pytest -q $WORKTREE/tests/test_raschke_v3_factorial_portfolio_audit.py

write_status RUNNING prior_screen_frozen_confirmation_portfolio_role

echo === RASCHKE V3 SPARSE FACTORIAL AND PORTFOLIO ROLE AUDIT ===
PYTHONPATH=$WORKTREE:$ROOT Q4R3_ROUTE_A_OVERLAY_ROOT=$WORKTREE Q4R3_ROUTE_A_WORKTREE=$WORKTREE $PYTHON_BIN $WORKTREE/tools/q4r3_route_a_raschke_v3_factorial_portfolio_audit.py

for attempt in $(seq 1 30); do
  ready=true
  for output in "$FACTORIAL" "$TRADES" "$INVENTORY" "$PORTFOLIO" "$DECISION" "$TRIAL" "$HTML"; do
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

for output in "$FACTORIAL" "$TRADES" "$INVENTORY" "$PORTFOLIO" "$DECISION" "$TRIAL" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE factorial_and_portfolio_role_complete

echo === DECISION ===
jq . "$DECISION"
echo === SCREEN ===
jq '{selected_positive_factors:.screen.selected_positive_factors,dummy_noise_floor:.screen.dummy_noise_floor,selection_floor:.screen.selection_floor,best_prior_run:.screen.best_prior_run,effects:.screen.effects}' "$FACTORIAL"
echo === CONFIRMATION ===
jq '. as $r | {ranking:$r.confirmation.ranking,gate_pass_candidates:$r.confirmation.gate_pass_candidates,top:[$r.confirmation.ranking[] as $name | {candidate:$name,factors:$r.confirmation.reports[$name].factors,gate:$r.confirmation.reports[$name].gate,prior:$r.confirmation.reports[$name]["prior_cost_0.15"],second:$r.confirmation.reports[$name]["second_cost_0.15"],combined:$r.confirmation.reports[$name]["combined_cost_0.15"],stress:$r.confirmation.reports[$name]["combined_cost_0.20"]}]}' "$FACTORIAL"
echo === PORTFOLIO INVENTORY ===
jq '{strategy_count,deduplicated_rows,preliminary_source_ready,full_25_strategy_source_ready,strategies,files:[.files[]|select(.rows>0)]}' "$INVENTORY"
echo === PORTFOLIO ROLE ===
jq . "$PORTFOLIO"
echo RASCHKE_V3_FACTORIAL_PORTFOLIO_JOB_DONE
