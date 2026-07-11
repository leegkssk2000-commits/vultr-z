#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-v3-ledger}
STATUS=$ROOT/runtime/q4r3_route_a_raschke_v3_event_ledger_drift_job_latest.json
SUMMARY=$ROOT/runtime/q4r3_route_a_raschke_v3_event_ledger_drift_latest.json
LEDGER=$ROOT/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json
DRIFT=$ROOT/runtime/q4r3_route_a_raschke_v3_feature_drift_latest.json
PATHS=$ROOT/runtime/q4r3_route_a_raschke_v3_event_aligned_paths_latest.json
HTML=$ROOT/runtime/raschke_v3_event_ledger_drift_latest.html
LOG=$ROOT/runtime/q4r3_route_a_raschke_v3_event_ledger_drift_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$SUMMARY" "$LEDGER" "$DRIFT" "$PATHS" "$HTML" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state, reason, started_at = sys.argv[2], sys.argv[3], sys.argv[4]
paths = {
    "summary": Path(sys.argv[5]),
    "ledger": Path(sys.argv[6]),
    "drift": Path(sys.argv[7]),
    "aligned_paths": Path(sys.argv[8]),
    "html": Path(sys.argv[9]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_event_ledger_drift",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() for key, path in paths.items()},
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
}
if paths["summary"].exists():
    try:
        result = json.loads(paths["summary"].read_text(errors="ignore"))
        payload["result_status"] = result.get("status")
        payload["verdict"] = result.get("verdict")
        payload["event_count"] = result.get("event_count")
        payload["prior_event_count"] = result.get("prior_event_count")
        payload["second_event_count"] = result.get("second_event_count")
        payload["readiness"] = result.get("readiness")
        payload["top_numeric_drift"] = result.get("top_numeric_drift", [])[:5]
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED exit_code=$code || true
  echo RASCHKE_V3_EVENT_LEDGER_DRIFT_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo RUN_START $START_TS
rm -f "$SUMMARY" "$LEDGER" "$DRIFT" "$PATHS" "$HTML"
write_status RUNNING preflight

for required in \
  "$OVERLAY/backend/strategies/_route_a_video_common.py" \
  "$OVERLAY/backend/strategies/raschke_macd_ema200.py" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_v3_event_ledger_drift.py" \
  "$OVERLAY/tests/test_raschke_v3_event_ledger_drift.py"
do
  if [ ! -f "$required" ]; then
    echo RASCHKE_V3_LEDGER_INPUT_MISSING:$required >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    "$ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json" \
    "$ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json"
  do
    if [ ! -f "$path" ]; then
      echo RASCHKE_V3_LEDGER_RAW_MISSING:$path >&2
      exit 2
    fi
  done
done

write_status RUNNING tests
echo '=== RASCHKE V3 EVENT LEDGER DRIFT TESTS ==='
Q4R3_ROUTE_A_OVERLAY_ROOT=$OVERLAY PYTHONPATH=$OVERLAY:$ROOT "$PYTHON_BIN" -m pytest -q "$OVERLAY/tests/test_raschke_v3_event_ledger_drift.py"

write_status RUNNING all_signal_labeling_and_drift
echo '=== RASCHKE V3 ALL-SIGNAL LABELING + DRIFT ==='
Q4R3_ROUTE_A_OVERLAY_ROOT=$OVERLAY PYTHONPATH=$OVERLAY:$ROOT "$PYTHON_BIN" "$OVERLAY/tools/q4r3_route_a_raschke_v3_event_ledger_drift.py"

for output in "$SUMMARY" "$LEDGER" "$DRIFT" "$PATHS" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo RASCHKE_V3_LEDGER_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE event_ledger_and_drift_complete

echo '=== RASCHKE V3 EVENT LEDGER DRIFT SUMMARY ==='
jq '{status, verdict, event_count, prior_event_count, second_event_count, readiness, top_numeric_drift, top_categorical_drift, outputs, authority}' "$SUMMARY"
echo RASCHKE_V3_EVENT_LEDGER_DRIFT_JOB_DONE
