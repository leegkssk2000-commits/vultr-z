#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-route-a-v3-continuation}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_continuation_partial_history_job_latest.json
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_continuation_partial_history_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

CONTINUATION=$ROOT/runtime/q4r3_route_a_raschke_v3_15r_to_2r_continuation_latest.json
POLICY=$ROOT/runtime/q4r3_route_a_raschke_v3_partial_runner_replay_latest.json
HISTORY=$ROOT/runtime/q4r3_route_a_raschke_v3_safe_history_integrity_latest.json
BOCPD_MONTH=$ROOT/runtime/q4r3_route_a_raschke_v3_bocpd_month_validation_latest.json
DECISION=$ROOT/runtime/q4r3_route_a_raschke_v3_continuation_decision_latest.json
TRIAL=$ROOT/runtime/q4r3_route_a_raschke_v3_partial_runner_trial_registration_latest.json
HTML=$ROOT/runtime/raschke_v3_continuation_partial_history_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - "$STATUS" "$state" "$reason" "$START_TS" "$CONTINUATION" "$POLICY" "$HISTORY" "$BOCPD_MONTH" "$DECISION" "$TRIAL" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "continuation": Path(sys.argv[5]),
    "policy": Path(sys.argv[6]),
    "history": Path(sys.argv[7]),
    "bocpd_month": Path(sys.argv[8]),
    "decision": Path(sys.argv[9]),
    "trial": Path(sys.argv[10]),
    "html": Path(sys.argv[11]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_continuation_partial_history",
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
        payload["continuation_probability_2R_given_1_5R"] = decision.get("continuation_probability_2R_given_1_5R")
        payload["eligible_safe_history_groups"] = decision.get("eligible_safe_history_groups")
        payload["bocpd_month_observer_supported"] = decision.get("bocpd_month_observer_supported")
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
  echo RASCHKE_V3_CONTINUATION_PARTIAL_HISTORY_JOB_FAILED exit_code=$code >&2
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
  $WORKTREE/tools/q4r3_route_a_raschke_v3_continuation_partial_history.py \
  $WORKTREE/tools/q4r3_route_a_raschke_v3_continuation_partial_history_job.py \
  $WORKTREE/tests/test_raschke_v3_continuation_partial_history.py \
  $ROOT/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json \
  $ROOT/runtime/q4r3_route_a_raschke_v3_transition_giveback_latest.json \
  $ROOT/runtime/q4r3_route_a_raschke_v3_bocpd_observer_latest.json \
  $ROOT/runtime/q4r3_route_a_raschke_v3_sample_inventory_latest.json
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

rm -f "$CONTINUATION" "$POLICY" "$HISTORY" "$BOCPD_MONTH" "$DECISION" "$TRIAL" "$HTML"
write_status RUNNING tests

echo === RASCHKE V3 CONTINUATION PARTIAL HISTORY TESTS ===
PYTHONPATH=$WORKTREE:$ROOT $PYTHON_BIN -m pytest -q $WORKTREE/tests/test_raschke_v3_continuation_partial_history.py

write_status RUNNING continuation_partial_runner_and_history_integrity

echo === RASCHKE V3 CONTINUATION PARTIAL RUNNER HISTORY ===
PYTHONPATH=$WORKTREE:$ROOT $PYTHON_BIN $WORKTREE/tools/q4r3_route_a_raschke_v3_continuation_partial_history_job.py

for attempt in $(seq 1 30); do
  ready=true
  for output in "$CONTINUATION" "$POLICY" "$HISTORY" "$BOCPD_MONTH" "$DECISION" "$TRIAL" "$HTML"; do
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

for output in "$CONTINUATION" "$POLICY" "$HISTORY" "$BOCPD_MONTH" "$DECISION" "$TRIAL" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE continuation_partial_runner_history_complete

echo === DECISION ===
jq . "$DECISION"
echo === POLICY SUMMARY ===
jq '{ranking, promising_candidates, reports: (.reports | with_entries(.value |= {gate_pass, retention_vs_baseline_pct, avg_R_improvement_vs_baseline, combined_cost_0_15: .["combined_cost_0.15"], combined_cost_0_20: .["combined_cost_0.20"], prior_cost_0_15: .["prior_cost_0.15"], second_cost_0_15: .["second_cost_0.15"], checks}))}' "$POLICY"
echo === CONTINUATION SUMMARY ===
jq '{all: .groups.all, by_window: .groups.window, by_side: .groups.side, speed: .groups.speed_bucket, stable_features: [.feature_screen[] | select(.stable_diagnostic == true)][0:10]}' "$CONTINUATION"
echo === SAFE HISTORY ===
jq '{eligible_count, eligible_groups, inspected_groups: [.inspected_groups[] | {directory, eligible_for_manual_approval, reasons}]}' "$HISTORY"
echo RASCHKE_V3_CONTINUATION_PARTIAL_HISTORY_JOB_DONE
