#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-v3-competing}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_competing_risk_bocpd_job_latest.json
COMPETING=$ROOT/runtime/q4r3_route_a_raschke_v3_competing_risk_latest.json
MFE=$ROOT/runtime/q4r3_route_a_raschke_v3_mfe_ladder_diagnostic_latest.json
BOCPD=$ROOT/runtime/q4r3_route_a_raschke_v3_bocpd_observer_latest.json
DECISION=$ROOT/runtime/q4r3_route_a_raschke_v3_diagnostic_decision_latest.json
HTML=$ROOT/runtime/raschke_v3_competing_risk_bocpd_latest.html
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_competing_risk_bocpd_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x $PYTHON_BIN ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

write_status() {
  local state=$1
  local reason=${2:-}
  $PYTHON_BIN - $STATUS $state $reason $START_TS $COMPETING $MFE $BOCPD $DECISION $HTML <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "competing_risk": Path(sys.argv[5]),
    "mfe_ladder": Path(sys.argv[6]),
    "bocpd": Path(sys.argv[7]),
    "decision": Path(sys.argv[8]),
    "html": Path(sys.argv[9]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_competing_risk_bocpd",
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
        payload["preferred_intermediate_label"] = decision.get("preferred_intermediate_label")
        payload["side_separated_pilot_labels"] = decision.get("side_separated_pilot_labels")
        payload["next_modules"] = decision.get("next_modules")
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
if paths["mfe_ladder"].exists() and paths["mfe_ladder"].stat().st_size > 0:
    try:
        mfe = json.loads(paths["mfe_ladder"].read_text(errors="ignore"))
        payload["mfe_thresholds"] = [
            {
                "threshold_R": row.get("threshold_R"),
                "positive": row.get("positive"),
                "rate_pct": row.get("rate_pct"),
                "readiness": row.get("readiness"),
            }
            for row in mfe.get("thresholds", [])
        ]
        payload["giveback"] = mfe.get("giveback")
    except Exception as exc:
        payload["mfe_read_error"] = repr(exc)
if paths["competing_risk"].exists() and paths["competing_risk"].stat().st_size > 0:
    try:
        competing = json.loads(paths["competing_risk"].read_text(errors="ignore"))
        payload["all_competing_risk"] = competing.get("subgroups", {}).get("all")
    except Exception as exc:
        payload["competing_read_error"] = repr(exc)
if paths["bocpd"].exists() and paths["bocpd"].stat().st_size > 0:
    try:
        bocpd = json.loads(paths["bocpd"].read_text(errors="ignore"))
        payload["second_window_boundary"] = bocpd.get("second_window_boundary")
        payload["top_change_points"] = bocpd.get("top_change_points", [])[:5]
    except Exception as exc:
        payload["bocpd_read_error"] = repr(exc)
temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED exit_code=$code || true
  echo RASCHKE_V3_COMPETING_RISK_BOCPD_JOB_FAILED exit_code=$code >&2
  exit $code
}
trap on_error ERR

wait_for_output() {
  local path=$1
  local attempts=0
  while [ $attempts -lt 40 ]; do
    if [ -s $path ]; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 0.25
  done
  echo OUTPUT_NOT_READY:$path >&2
  return 1
}

mkdir -p $ROOT/runtime
: > $LOG
exec > >(tee -a $LOG) 2>&1
echo RUN_START $START_TS
rm -f $COMPETING $MFE $BOCPD $DECISION $HTML
write_status RUNNING preflight

for required in $OVERLAY/tools/q4r3_route_a_raschke_v3_competing_risk_bocpd.py $OVERLAY/tests/test_raschke_v3_competing_risk_bocpd.py $ROOT/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_label_ladder_latest.json $ROOT/runtime/q4r3_route_a_raschke_v3_multitarget_sample_plan_latest.json; do
  if [ ! -s $required ]; then
    echo INPUT_MISSING_OR_EMPTY:$required >&2
    exit 2
  fi
done

write_status RUNNING tests
echo === RASCHKE V3 COMPETING RISK AND BOCPD TESTS ===
PYTHONPATH=$OVERLAY:$ROOT $PYTHON_BIN -m pytest -q $OVERLAY/tests/test_raschke_v3_competing_risk_bocpd.py

write_status RUNNING competing_risk_mfe_giveback_bocpd
echo === RASCHKE V3 COMPETING RISK MFE LADDER GIVEBACK BOCPD ===
PYTHONPATH=$OVERLAY:$ROOT $PYTHON_BIN $OVERLAY/tools/q4r3_route_a_raschke_v3_competing_risk_bocpd.py

wait_for_output $COMPETING
wait_for_output $MFE
wait_for_output $BOCPD
wait_for_output $DECISION
wait_for_output $HTML

write_status DONE competing_risk_mfe_and_changepoint_complete

echo === DECISION ===
cat $DECISION
echo RASCHKE_V3_COMPETING_RISK_BOCPD_JOB_DONE
