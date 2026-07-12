#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=/home/z/z/.venv/bin/python
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-v3-attribution}
STATUS=/home/z/z/runtime/q4r3_route_a_raschke_v3_drift_attribution_job_latest.json
ATTRIBUTION=/home/z/z/runtime/q4r3_route_a_raschke_v3_drift_attribution_latest.json
INVENTORY=/home/z/z/runtime/q4r3_route_a_raschke_v3_sample_inventory_latest.json
NEXT=/home/z/z/runtime/q4r3_route_a_raschke_v3_next_design_latest.json
HTML=/home/z/z/runtime/raschke_v3_drift_attribution_latest.html
LOG=/home/z/z/runtime/q4r3_route_a_raschke_v3_drift_attribution_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$ATTRIBUTION" "$INVENTORY" "$NEXT" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "attribution": Path(sys.argv[5]),
    "inventory": Path(sys.argv[6]),
    "next_design": Path(sys.argv[7]),
    "html": Path(sys.argv[8]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_drift_attribution_inventory",
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
if paths["next_design"].exists():
    try:
        result = json.loads(paths["next_design"].read_text(errors="ignore"))
        payload["result_status"] = result.get("status")
        payload["verdict"] = result.get("verdict")
        payload["next_action"] = result.get("next_action")
        payload["sample_gap"] = result.get("sample_gap")
        payload["stable_numeric_candidates"] = result.get("stable_numeric_candidates", [])[:5]
        payload["stable_categorical_candidates"] = result.get("stable_categorical_candidates", [])[:5]
    except Exception as exc:
        payload["result_read_error"] = repr(exc)
if paths["inventory"].exists():
    try:
        inventory = json.loads(paths["inventory"].read_text(errors="ignore"))
        payload["full_symbol_candidate_groups"] = inventory.get("full_symbol_candidate_groups", [])[:10]
    except Exception as exc:
        payload["inventory_read_error"] = repr(exc)
temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED exit_code=$code || true
  echo RASCHKE_V3_DRIFT_ATTRIBUTION_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

mkdir -p /home/z/z/runtime
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo RUN_START $START_TS
rm -f "$ATTRIBUTION" "$INVENTORY" "$NEXT" "$HTML"
write_status RUNNING preflight

for required in \
  "$OVERLAY/tools/q4r3_route_a_raschke_v3_drift_attribution_inventory.py" \
  "$OVERLAY/tests/test_raschke_v3_drift_attribution_inventory.py" \
  /home/z/z/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json \
  /home/z/z/runtime/q4r3_route_a_raschke_v3_feature_drift_latest.json \
  /home/z/z/runtime/q4r3_route_a_raschke_v3_event_aligned_paths_latest.json
do
  if [ ! -f "$required" ]; then
    echo RASCHKE_V3_DRIFT_ATTRIBUTION_INPUT_MISSING:$required >&2
    exit 2
  fi
done

write_status RUNNING tests
echo === RASCHKE V3 DRIFT ATTRIBUTION TESTS ===
PYTHONPATH="$OVERLAY:$ROOT" "$PYTHON_BIN" -m pytest -q "$OVERLAY/tests/test_raschke_v3_drift_attribution_inventory.py"

write_status RUNNING class_conditional_drift_path_and_history_manifest
echo === RASCHKE V3 CLASS-CONDITIONAL DRIFT + SAFE HISTORY MANIFEST ===
PYTHONPATH="$OVERLAY:$ROOT" "$PYTHON_BIN" "$OVERLAY/tools/q4r3_route_a_raschke_v3_drift_attribution_inventory.py"

for output in "$ATTRIBUTION" "$INVENTORY" "$NEXT" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo RASCHKE_V3_DRIFT_ATTRIBUTION_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE drift_attribution_and_sample_inventory_complete

echo === RASCHKE V3 NEXT DESIGN ===
jq '{status, verdict, next_action, sample_gap, stable_numeric_candidates: .stable_numeric_candidates[:5], stable_categorical_candidates: .stable_categorical_candidates[:5]}' "$NEXT"
echo === SAFE HISTORY MANIFEST ===
jq '{status, scanned_json_files, full_symbol_candidate_groups: .full_symbol_candidate_groups[:10], excluded, contract}' "$INVENTORY"
echo RASCHKE_V3_DRIFT_ATTRIBUTION_JOB_DONE
