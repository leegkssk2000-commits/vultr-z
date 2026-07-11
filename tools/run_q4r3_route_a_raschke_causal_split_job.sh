#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-causal-split}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_causal_split_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_raschke_causal_split_latest.json"
TRADES="$ROOT/runtime/q4r3_route_a_raschke_causal_split_trades_latest.json"
DIAGNOSTIC="$ROOT/runtime/q4r3_route_a_raschke_short_confirmation_diagnostic_latest.json"
LOG="$ROOT/runtime/q4r3_route_a_raschke_causal_split_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$RESULT" "$TRADES" "$DIAGNOSTIC" <<'PY'
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
    "short_diagnostic": Path(sys.argv[7]),
}
payload = {
    "job": "q4r3_route_a_raschke_causal_split_replay",
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
        payload["top6"] = result.get("ranking", [])[:6]
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
  echo "RASCHKE_CAUSAL_SPLIT_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "RUN_START $START_TS"
rm -f "$RESULT" "$TRADES" "$DIAGNOSTIC"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/backend/strategies/_route_a_video_common.py" \
  "$OVERLAY/backend/strategies/raschke_macd_ema200.py" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_causal_split_replay.py" \
  "$OVERLAY/tests/test_raschke_causal_split_replay.py"
do
  if [ ! -f "$required" ]; then
    echo "RASCHKE_CAUSAL_SPLIT_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    "$ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json" \
    "$ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json"
  do
    if [ ! -f "$path" ]; then
      echo "RASCHKE_CAUSAL_SPLIT_RAW_MISSING:$path" >&2
      exit 2
    fi
  done
done

write_status RUNNING "tests"
echo "=== RASCHKE CAUSAL SPLIT TESTS ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_raschke_causal_split_replay.py"

write_status RUNNING "six_lane_causal_replay"
echo "=== RASCHKE SIX-LANE CAUSAL SPLIT REPLAY ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_causal_split_replay.py"

for output in "$RESULT" "$TRADES" "$DIAGNOSTIC"; do
  if [ ! -s "$output" ]; then
    echo "RASCHKE_CAUSAL_SPLIT_OUTPUT_MISSING:$output" >&2
    exit 3
  fi
done

write_status DONE "causal_split_replay_complete"

echo "=== RASCHKE CAUSAL SPLIT RESULT ==="
jq '{status, verdict, third_holdout_queue, ranking, authority}' "$RESULT"

echo "=== SHORT CONFIRMATION DIAGNOSTIC ==="
jq '{status, baseline_second_short, lanes}' "$DIAGNOSTIC"

echo "RASCHKE_CAUSAL_SPLIT_JOB_DONE"
