#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-video-fidelity}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_forensic_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_raschke_forensic_rescue_latest.json"
LOG="$ROOT/runtime/q4r3_route_a_raschke_forensic_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$RESULT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
result_path = Path(sys.argv[5])
payload = {
    "job": "q4r3_route_a_raschke_forensic_rescue",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "result_path": str(result_path),
    "result_exists": result_path.exists(),
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
}
if result_path.exists():
    try:
        result = json.loads(result_path.read_text(errors="ignore"))
        payload["result_status"] = result.get("status")
        payload["verdict"] = result.get("verdict")
        payload["discovery_selected_mode"] = result.get("discovery_selected_mode")
        payload["selected_holdout_cost_0.15"] = result.get("selected_holdout_cost_0.15")
        payload["second_holdout_queue_frozen"] = result.get("second_holdout_queue_frozen")
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
  write_status FAILED "exit_code=$code" || true
  echo "RASCHKE_FORENSIC_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
exec > >(tee -a "$LOG") 2>&1
rm -f "$RESULT"
write_status RUNNING "preflight"

if [ ! -f "$OVERLAY/backend/strategies/raschke_macd_ema200.py" ] \
   || [ ! -f "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" ]; then
  echo "RASCHKE_FORENSIC_OVERLAY_MISSING:$OVERLAY" >&2
  exit 2
fi

cd "$OVERLAY"

echo "=== RASCHKE FORENSIC IMPORT PREFLIGHT ==="
PYTHONPATH="$OVERLAY:$ROOT" "$PYTHON_BIN" - <<'PY'
import importlib
from pathlib import Path
root = Path.cwd().resolve()
module = importlib.import_module("backend.strategies.raschke_macd_ema200")
path = Path(module.__file__).resolve()
print("raschke_module=", path)
if root not in path.parents:
    raise RuntimeError(f"OVERLAY_SHADOWED:{path}")
for mode in (
    "source_core",
    "candle_direction",
    "body_close",
    "trend_strength",
    "pdm_proxy_v1",
):
    module.RaschkeMacdEma200Config(confirmation_mode=mode)
print("PREDECLARED_MODES_OK")
PY

write_status RUNNING "tests"
echo "=== RASCHKE FORENSIC TESTS ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_route_a_video_fidelity.py" \
  "$OVERLAY/tests/test_raschke_forensic_rescue.py"

write_status RUNNING "forensic_replay"
echo "=== RASCHKE FORENSIC REPLAY ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py"

write_status DONE "forensic_complete"

echo "=== RASCHKE FORENSIC RESULT ==="
jq '{
  status,
  verdict,
  discovery_selected_mode,
  selected_holdout: ."selected_holdout_cost_0.15",
  baseline_holdout: ."baseline_holdout_cost_0.15",
  second_holdout_queue_frozen,
  best_groups: .baseline_group_extremes.best10[:5],
  worst_groups: .baseline_group_extremes.worst10[:5],
  hard_gate,
  near_gate,
  authority
}' "$RESULT" || true

echo "RASCHKE_FORENSIC_JOB_DONE"
