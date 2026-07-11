#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-video-fidelity}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_second_holdout_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_raschke_second_holdout_latest.json"
LOG="$ROOT/runtime/q4r3_route_a_raschke_second_holdout_job.log"
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
    "job": "q4r3_route_a_raschke_second_holdout",
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
        payload["robust_pass_modes"] = result.get("robust_pass_modes")
        payload["window"] = result.get("window")
        payload["evaluations_cost_0.15"] = {
            mode: data.get("costs", {}).get("cost_0.15", {})
            for mode, data in result.get("evaluations", {}).items()
        }
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
  echo "RASCHKE_SECOND_HOLDOUT_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
exec > >(tee -a "$LOG") 2>&1
rm -f "$RESULT"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/backend/strategies/raschke_macd_ema200.py" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_second_holdout.py" \
  "$OVERLAY/tests/test_raschke_second_holdout.py"
do
  if [ ! -f "$required" ]; then
    echo "SECOND_HOLDOUT_OVERLAY_MISSING:$required" >&2
    exit 2
  fi
done

cd "$OVERLAY"

echo "=== RASCHKE SECOND HOLDOUT PREFLIGHT ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys
from pathlib import Path
root = Path.cwd().resolve()
path = root / "tools" / "q4r3_route_a_raschke_second_holdout.py"
spec = importlib.util.spec_from_file_location("q4r3_second_holdout_preflight", path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.FROZEN_MODES == ("source_core", "candle_direction")
assert module.FROZEN_CONTRACT["target_R"] == 2.0
assert module.FROZEN_CONTRACT["loss_cap_R"] == -0.5
print("FROZEN_INPUTS_OK")
PY

write_status RUNNING "tests"
echo "=== RASCHKE SECOND HOLDOUT TESTS ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_raschke_forensic_rescue.py" \
  "$OVERLAY/tests/test_raschke_second_holdout.py"

write_status RUNNING "collect_and_replay"
echo "=== RASCHKE SECOND HOLDOUT COLLECT + REPLAY ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_second_holdout.py"

write_status DONE "second_holdout_complete"

echo "=== RASCHKE SECOND HOLDOUT RESULT ==="
jq '{
  status,
  verdict,
  frozen_modes: .frozen_spec.modes,
  window,
  robust_pass_modes,
  source_core_015: .evaluations.source_core.costs."cost_0.15",
  candle_direction_015: .evaluations.candle_direction.costs."cost_0.15",
  source_core_020: .evaluations.source_core.costs."cost_0.20",
  candle_direction_020: .evaluations.candle_direction.costs."cost_0.20",
  promotion_rule,
  authority
}' "$RESULT" || true

echo "RASCHKE_SECOND_HOLDOUT_JOB_DONE"
