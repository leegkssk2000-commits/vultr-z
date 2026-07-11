#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-video-fidelity}
STATUS="$ROOT/runtime/q4r3_route_a_video_fidelity_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_video_fidelity_tournament_latest.json"
LOG="$ROOT/runtime/q4r3_route_a_video_fidelity_job.log"
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
    "job": "q4r3_route_a_video_fidelity_tournament",
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
        payload["top5"] = result.get("ranking_cost_0.15", [])[:5]
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
  echo "ROUTE_A_VIDEO_FIDELITY_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
exec > >(tee -a "$LOG") 2>&1
rm -f "$RESULT"
write_status RUNNING "preflight_import"

if [ ! -f "$OVERLAY/backend/__init__.py" ] || [ ! -f "$OVERLAY/backend/strategies/__init__.py" ]; then
  echo "OVERLAY_PACKAGE_MISSING:$OVERLAY" >&2
  exit 2
fi

# Python places the current working directory before PYTHONPATH. Running from
# /home/z/z caused the production backend package to shadow the isolated
# overlay package. Enter the overlay first so the research-only modules win.
cd "$OVERLAY"

echo "=== ROUTE A VIDEO FIDELITY IMPORT PREFLIGHT ==="
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" - <<'PY'
import importlib
import sys
from pathlib import Path
expected = Path.cwd().resolve()
modules = [
    "backend.strategies.rayner_hist_momentum",
    "backend.strategies.raschke_macd_ema200",
    "backend.strategies.fractal_triple_ema_pullback",
    "backend.strategies.alligator_trend_pullback",
]
print("cwd=", expected)
print("sys.path[:4]=", sys.path[:4])
for name in modules:
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    print(name, "->", path)
    if expected not in path.parents:
        raise RuntimeError(f"OVERLAY_SHADOWED:{name}:{path}")
PY

write_status RUNNING "tests_and_tournament"

echo "=== ROUTE A VIDEO FIDELITY TESTS ==="
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_route_a_video_fidelity.py"

echo "=== ROUTE A VIDEO FIDELITY TOURNAMENT ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py"

write_status DONE "tournament_complete"

echo "=== ROUTE A VIDEO FIDELITY TOP 10 ==="
jq '{status, top10: .ranking_cost_0.15[:10], hard_gate, authority}' "$RESULT"
echo "ROUTE_A_VIDEO_FIDELITY_JOB_DONE"
