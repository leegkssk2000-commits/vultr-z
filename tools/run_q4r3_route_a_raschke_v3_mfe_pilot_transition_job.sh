#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-v3-mfe-pilot}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_mfe_pilot_transition_job_latest.json
SCREEN=$ROOT/runtime/q4r3_route_a_raschke_v3_mfe_stable_feature_screen_latest.json
PILOT=$ROOT/runtime/q4r3_route_a_raschke_v3_side_pilot_latest.json
TRANSITION=$ROOT/runtime/q4r3_route_a_raschke_v3_transition_giveback_latest.json
DECISION=$ROOT/runtime/q4r3_route_a_raschke_v3_pilot_decision_latest.json
TRIAL=$ROOT/runtime/q4r3_route_a_raschke_v3_trial_registration_latest.json
HTML=$ROOT/runtime/raschke_v3_mfe_pilot_transition_latest.html
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_mfe_pilot_transition_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x $PYTHON_BIN ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - $STATUS $state $reason $START_TS $SCREEN $PILOT $TRANSITION $DECISION $TRIAL $HTML <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "screen": Path(sys.argv[5]),
    "pilot": Path(sys.argv[6]),
    "transition": Path(sys.argv[7]),
    "decision": Path(sys.argv[8]),
    "trial": Path(sys.argv[9]),
    "html": Path(sys.argv[10]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_mfe_pilot_transition",
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
}
if paths["decision"].exists() and paths["decision"].stat().st_size > 0:
    try:
        decision = json.loads(paths["decision"].read_text(errors="ignore"))
        payload["result_status"] = decision.get("status")
        payload["verdict"] = decision.get("verdict")
        payload["stable_transport_sides"] = decision.get("stable_transport_sides")
        payload["stable_1.5R_feature_count"] = decision.get("stable_1.5R_feature_count")
        payload["p_2R_given_1.5R"] = decision.get("p_2R_given_1.5R")
        payload["giveback_after_1R_pct"] = decision.get("giveback_after_1R_pct")
        payload["next_modules"] = decision.get("next_modules")
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
if paths["pilot"].exists() and paths["pilot"].stat().st_size > 0:
    try:
        pilot = json.loads(paths["pilot"].read_text(errors="ignore"))
        payload["pilot_summary"] = {
            side: {
                "features": report.get("features"),
                "stable_transport": report.get("stable_transport"),
                "primary_auc": report.get("primary_prior_to_second", {}).get("predictive", {}).get("auc"),
                "primary_brier_skill": report.get("primary_prior_to_second", {}).get("predictive", {}).get("brier_skill"),
                "primary_target_lift": report.get("primary_prior_to_second", {}).get("economics", {}).get("target_lift"),
                "primary_top_half_avg_net_R": report.get("primary_prior_to_second", {}).get("economics", {}).get("top_half", {}).get("avg_net_R"),
            }
            for side, report in pilot.get("results", {}).items()
        }
    except Exception as exc:
        payload["pilot_read_error"] = repr(exc)

temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED exit_code=$code || true
  echo RASCHKE_V3_MFE_PILOT_TRANSITION_JOB_FAILED exit_code=$code >&2
  exit $code
}
trap on_error ERR

mkdir -p $ROOT/runtime
: > $LOG
exec > >(tee -a $LOG) 2>&1
echo RUN_START $START_TS
rm -f $SCREEN $PILOT $TRANSITION $DECISION $TRIAL $HTML
write_status RUNNING preflight

for required in $OVERLAY/tools/q4r3_route_a_raschke_v3_mfe_pilot_transition.py $OVERLAY/tests/test_raschke_v3_mfe_pilot_transition.py $ROOT/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_drift_attribution_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_mfe_ladder_diagnostic_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_bocpd_observer_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_diagnostic_decision_latest.json
do
  if [ ! -s $required ]; then
    echo RASCHKE_V3_MFE_PILOT_INPUT_MISSING:$required >&2
    exit 2
  fi
done

write_status RUNNING tests
echo === RASCHKE V3 MFE PILOT TRANSITION TESTS ===
PYTHONPATH=$OVERLAY:$ROOT $PYTHON_BIN -m pytest -q $OVERLAY/tests/test_raschke_v3_mfe_pilot_transition.py

write_status RUNNING stable_feature_screen_side_pilot_and_transition
echo === RASCHKE V3 STABLE FEATURE SCREEN + SIDE PILOT + TRANSITION ===
PYTHONPATH=$OVERLAY:$ROOT $PYTHON_BIN $OVERLAY/tools/q4r3_route_a_raschke_v3_mfe_pilot_transition.py

for attempt in $(seq 1 30)
do
  complete=true
  for output in $SCREEN $PILOT $TRANSITION $DECISION $TRIAL $HTML
  do
    if [ ! -s $output ]; then
      complete=false
    fi
  done
  if [ $complete = true ]; then
    break
  fi
  sleep 1
done

for output in $SCREEN $PILOT $TRANSITION $DECISION $TRIAL $HTML
do
  if [ ! -s $output ]; then
    echo RASCHKE_V3_MFE_PILOT_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE mfe_feature_screen_pilot_transition_complete

echo === PILOT DECISION ===
jq '{status, verdict, stable_transport_sides, stable_1_5R_feature_count: ."stable_1.5R_feature_count", p_2R_given_1_5R: ."p_2R_given_1.5R", giveback_after_1R_pct, next_modules, hard_rules, authority}' $DECISION

echo === SIDE PILOTS ===
jq '{status, target_R, model, results: (.results | with_entries(.value = {features: .value.features, stable_transport: .value.stable_transport, primary: .value.primary_prior_to_second, sensitivity: .value."sensitivity_0.5R_primary"})), promotion_allowed, authority}' $PILOT

echo === ALL TRANSITION ===
jq '{status, all: .scopes.all, bocpd_cross_check, rule, authority}' $TRANSITION

echo RASCHKE_V3_MFE_PILOT_TRANSITION_JOB_DONE
