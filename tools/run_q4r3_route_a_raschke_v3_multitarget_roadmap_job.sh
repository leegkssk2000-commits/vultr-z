#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-v3-multitarget}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_v3_multitarget_roadmap_job_latest.json"
PLAN="$ROOT/runtime/q4r3_route_a_raschke_v3_multitarget_sample_plan_latest.json"
LADDER="$ROOT/runtime/q4r3_route_a_raschke_v3_label_ladder_latest.json"
ROADMAP="$ROOT/runtime/q4r3_route_a_raschke_v3_research_roadmap_latest.json"
HTML="$ROOT/runtime/raschke_v3_multitarget_roadmap_latest.html"
LOG="$ROOT/runtime/q4r3_route_a_raschke_v3_multitarget_roadmap_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$PLAN" "$LADDER" "$ROADMAP" "$HTML" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "plan": Path(sys.argv[5]),
    "ladder": Path(sys.argv[6]),
    "roadmap": Path(sys.argv[7]),
    "html": Path(sys.argv[8]),
}
payload = {
    "job": "q4r3_route_a_raschke_v3_multitarget_roadmap",
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
if paths["plan"].exists():
    try:
        plan = json.loads(paths["plan"].read_text(errors="ignore"))
        payload["result_status"] = plan.get("status")
        payload["verdict"] = plan.get("verdict")
        payload["tp2r_current"] = plan.get("tp2r_sample_plan", {}).get("current")
        payload["tp2r_scenarios"] = plan.get("tp2r_sample_plan", {}).get("scenarios")
        payload["competing_risk"] = plan.get("competing_risk")
    except Exception as exc:
        payload["plan_read_error"] = repr(exc)
if paths["ladder"].exists():
    try:
        ladder = json.loads(paths["ladder"].read_text(errors="ignore"))
        payload["preferred_diagnostic_label"] = ladder.get("preferred_diagnostic_label")
        payload["label_counts"] = [
            {
                "label": row.get("label"),
                "positive": row.get("positive"),
                "negative": row.get("negative"),
                "readiness": row.get("readiness"),
            }
            for row in ladder.get("reports", [])
        ]
    except Exception as exc:
        payload["ladder_read_error"] = repr(exc)
if paths["roadmap"].exists():
    try:
        roadmap = json.loads(paths["roadmap"].read_text(errors="ignore"))
        payload["next_action"] = roadmap.get("next_action")
        payload["immediate_modules"] = roadmap.get("immediate_modules")
    except Exception as exc:
        payload["roadmap_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo "RASCHKE_V3_MULTITARGET_ROADMAP_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "RUN_START $START_TS"
rm -f "$PLAN" "$LADDER" "$ROADMAP" "$HTML"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/tools/q4r3_route_a_raschke_v3_multitarget_roadmap.py" \
  "$OVERLAY/tests/test_raschke_v3_multitarget_roadmap.py" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_all_signal_ledger_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_drift_attribution_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_sample_inventory_latest.json"
do
  if [ ! -f "$required" ]; then
    echo "RASCHKE_V3_MULTITARGET_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

write_status RUNNING "tests"
echo "=== RASCHKE V3 MULTITARGET ROADMAP TESTS ==="
PYTHONPATH="$OVERLAY:$ROOT" "$PYTHON_BIN" -m pytest -q "$OVERLAY/tests/test_raschke_v3_multitarget_roadmap.py"

write_status RUNNING "positive_event_and_label_ladder_recalculation"
echo "=== RASCHKE V3 POSITIVE-EVENT SAMPLE PLAN + LABEL LADDER + RESEARCH ROADMAP ==="
PYTHONPATH="$OVERLAY:$ROOT" "$PYTHON_BIN" "$OVERLAY/tools/q4r3_route_a_raschke_v3_multitarget_roadmap.py"

for output in "$PLAN" "$LADDER" "$ROADMAP" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo "RASCHKE_V3_MULTITARGET_OUTPUT_MISSING:$output" >&2
    exit 3
  fi
done

write_status DONE "multitarget_sample_plan_and_research_roadmap_complete"

echo "=== TP2R SAMPLE PLAN ==="
jq '{status, verdict, tp2r_sample_plan, competing_risk, feature_budget, safe_history, authority}' "$PLAN"
echo "=== LABEL LADDER ==="
jq '{status, preferred_diagnostic_label, reports: [.reports[] | {label, positive, negative, prevalence, readiness}]}' "$LADDER"
echo "=== ROADMAP ==="
jq '{status, verdict, next_action, immediate_modules, phases, hard_rules}' "$ROADMAP"
echo "RASCHKE_V3_MULTITARGET_ROADMAP_JOB_DONE"
