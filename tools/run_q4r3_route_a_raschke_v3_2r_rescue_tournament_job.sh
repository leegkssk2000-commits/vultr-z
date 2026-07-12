#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-v3-2r-rescue}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_tournament_job_latest.json
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_tournament_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

RESULT=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_tournament_latest.json
TRADES=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_trades_latest.json
ROBUSTNESS=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_robustness_latest.json
DECISION=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_decision_latest.json
TRIAL=$ROOT/runtime/q4r3_route_a_raschke_v3_2r_rescue_trial_registration_latest.json
HTML=$ROOT/runtime/raschke_v3_2r_rescue_tournament_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$RESULT" "$TRADES" "$ROBUSTNESS" "$DECISION" "$TRIAL" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "result": Path(sys.argv[5]),
    "trades": Path(sys.argv[6]),
    "robustness": Path(sys.argv[7]),
    "decision": Path(sys.argv[8]),
    "trial": Path(sys.argv[9]),
    "html": Path(sys.argv[10]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_2r_rescue_tournament",
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
        payload["promising_policy_candidates"] = decision.get("promising_policy_candidates")
        payload["best_policy_by_preregistered_ranking"] = decision.get("best_policy_by_preregistered_ranking")
        payload["prior_trained_side_target_map"] = decision.get("prior_trained_side_target_map")
        payload["pbo_estimate"] = decision.get("pbo_estimate")
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
  echo RASCHKE_V3_2R_RESCUE_JOB_FAILED exit_code=$code >&2
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
  $WORKTREE/backend/strategies/_route_a_video_common.py \
  $WORKTREE/backend/strategies/raschke_macd_ema200.py \
  $WORKTREE/tools/q4r3_route_a_video_fidelity_tournament.py \
  $WORKTREE/tools/q4r3_route_a_raschke_forensic_rescue.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v3_2r_rescue_tournament.py \
  $WORKTREE/tests/test_raschke_v3_2r_rescue_tournament.py
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

rm -f "$RESULT" "$TRADES" "$ROBUSTNESS" "$DECISION" "$TRIAL" "$HTML"
write_status RUNNING tests

echo === RASCHKE V3 MULTIDIMENSIONAL 2R RESCUE TESTS ===
PYTHONPATH=$WORKTREE:$ROOT $PYTHON_BIN -m pytest -q $WORKTREE/tests/test_raschke_v3_2r_rescue_tournament.py

write_status RUNNING multidimensional_2r_rescue_replay

echo === RASCHKE V3 MULTIDIMENSIONAL 2R RESCUE TOURNAMENT ===
PYTHONPATH=$WORKTREE:$ROOT Q4R3_ROUTE_A_WORKTREE=$WORKTREE $PYTHON_BIN $WORKTREE/tools/q4r3_route_a_raschke_v3_2r_rescue_tournament.py

for attempt in $(seq 1 30); do
  ready=true
  for output in "$RESULT" "$TRADES" "$ROBUSTNESS" "$DECISION" "$TRIAL" "$HTML"; do
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

for output in "$RESULT" "$TRADES" "$ROBUSTNESS" "$DECISION" "$TRIAL" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE multidimensional_2r_rescue_complete

echo === DECISION ===
jq . "$DECISION"
echo === TOP RANKING ===
jq '{policy_count, promising_policy_candidates, prior_trained_side_target_map, ranking: .ranking[0:10]}' "$RESULT"
echo === TOP REPORTS ===
jq '{reports: (.reports | to_entries | sort_by(.value.gate.worst_window_avg_R) | reverse | .[0:10] | map({policy: .key, gate: .value.gate, combined_cost_0_15: .value.combined_cost_0.15, second_cost_0_15: .value.second_cost_0.15, combined_cost_0_20: .value.combined_cost_0.20, bootstrap_second: .value.bootstrap_second_cost_0.15}))}' "$RESULT"
echo === ROBUSTNESS ===
jq '{pbo_month_blocks, target_training_audit}' "$ROBUSTNESS"
echo RASCHKE_V3_2R_RESCUE_JOB_DONE
