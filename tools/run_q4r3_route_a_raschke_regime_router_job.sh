#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-router}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_regime_router_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_raschke_regime_router_latest.json"
TRADES="$ROOT/runtime/q4r3_route_a_raschke_regime_router_trades_latest.json"
AUDIT_JSON="$ROOT/runtime/raschke_regime_router_chart_audit_latest.json"
AUDIT_HTML="$ROOT/runtime/raschke_regime_router_chart_audit_latest.html"
LOG="$ROOT/runtime/q4r3_route_a_raschke_regime_router_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$RESULT" "$TRADES" "$AUDIT_JSON" "$AUDIT_HTML" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "result": Path(sys.argv[5]),
    "trades": Path(sys.argv[6]),
    "chart_audit_json": Path(sys.argv[7]),
    "chart_audit_html": Path(sys.argv[8]),
}
payload = {
    "job": "q4r3_route_a_raschke_regime_router",
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
if paths["result"].exists():
    try:
        result = json.loads(paths["result"].read_text(errors="ignore"))
        payload["result_status"] = result.get("status")
        payload["verdict"] = result.get("verdict")
        payload["third_holdout_queue"] = result.get("third_holdout_queue", [])
        payload["top5"] = result.get("ranking", [])[:5]
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
  echo "RASCHKE_REGIME_ROUTER_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "RUN_START $START_TS"
rm -f "$RESULT" "$TRADES" "$AUDIT_JSON" "$AUDIT_HTML"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/backend/strategies/_route_a_video_common.py" \
  "$OVERLAY/backend/strategies/raschke_macd_ema200.py" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_regime_router.py" \
  "$OVERLAY/tests/test_raschke_regime_router.py"
do
  if [ ! -f "$required" ]; then
    echo "RASCHKE_REGIME_ROUTER_OVERLAY_MISSING:$required" >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    "$ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json" \
    "$ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json"
  do
    if [ ! -f "$path" ]; then
      echo "RASCHKE_REGIME_ROUTER_RAW_MISSING:$path" >&2
      exit 2
    fi
  done
done

write_status RUNNING "tests"
echo "=== RASCHKE REGIME ROUTER TESTS ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_raschke_regime_router.py"

write_status RUNNING "causal_router_replay"
echo "=== RASCHKE REGIME ROUTER TWO-WINDOW REPLAY ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_regime_router.py"

for output in "$RESULT" "$TRADES" "$AUDIT_JSON" "$AUDIT_HTML"; do
  if [ ! -s "$output" ]; then
    echo "RASCHKE_REGIME_ROUTER_OUTPUT_MISSING:$output" >&2
    exit 3
  fi
done

write_status DONE "regime_router_complete"

echo "=== RASCHKE REGIME ROUTER RESULT ==="
jq '{
  status,
  verdict,
  base_lane,
  top5: .ranking[:5],
  third_holdout_queue,
  router_gate,
  chart_audit,
  authority
}' "$RESULT"

echo "RASCHKE_REGIME_ROUTER_JOB_DONE"
