#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-router-audit}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_router_failure_audit_job_latest.json"
AUDIT="$ROOT/runtime/q4r3_route_a_raschke_router_failure_audit_latest.json"
CONTRIB="$ROOT/runtime/q4r3_route_a_raschke_second_window_loss_contribution_latest.json"
CANDIDATES="$ROOT/runtime/q4r3_route_a_raschke_split_candidates_latest.json"
HTML="$ROOT/runtime/raschke_router_failure_audit_latest.html"
LOG="$ROOT/runtime/q4r3_route_a_raschke_router_failure_audit_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$AUDIT" "$CONTRIB" "$CANDIDATES" "$HTML" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "audit": Path(sys.argv[5]),
    "contribution": Path(sys.argv[6]),
    "candidates": Path(sys.argv[7]),
    "html": Path(sys.argv[8]),
}
payload = {
    "job": "q4r3_route_a_raschke_router_failure_audit",
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
if paths["audit"].exists():
    try:
        audit = json.loads(paths["audit"].read_text(errors="ignore"))
        payload["result_status"] = audit.get("status")
        payload["verdict"] = audit.get("verdict")
        payload["diagnostic_summary"] = audit.get("diagnostic_summary")
    except Exception as exc:
        payload["audit_read_error"] = repr(exc)
if paths["candidates"].exists():
    try:
        candidates = json.loads(paths["candidates"].read_text(errors="ignore"))
        payload["candidate_count"] = candidates.get("candidate_count")
        payload["next"] = candidates.get("next")
        payload["top_candidates"] = candidates.get("candidates", [])[:3]
    except Exception as exc:
        payload["candidate_read_error"] = repr(exc)
tmp = status_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo "RASCHKE_ROUTER_FAILURE_AUDIT_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "RUN_START $START_TS"
rm -f "$AUDIT" "$CONTRIB" "$CANDIDATES" "$HTML"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/backend/strategies/_route_a_video_common.py" \
  "$OVERLAY/backend/strategies/raschke_macd_ema200.py" \
  "$OVERLAY/tools/q4r3_route_a_video_fidelity_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_forensic_rescue.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_v2_entry_exit_tournament.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_router_failure_audit.py" \
  "$OVERLAY/tests/test_raschke_router_failure_audit.py" \
  "$ROOT/runtime/q4r3_route_a_raschke_regime_router_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_regime_router_trades_latest.json"
do
  if [ ! -f "$required" ]; then
    echo "RASCHKE_ROUTER_FAILURE_AUDIT_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    "$ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json" \
    "$ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json"
  do
    if [ ! -f "$path" ]; then
      echo "RASCHKE_ROUTER_FAILURE_AUDIT_RAW_MISSING:$path" >&2
      exit 2
    fi
  done
done

write_status RUNNING "tests"
echo "=== RASCHKE ROUTER FAILURE AUDIT TESTS ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_raschke_router_failure_audit.py"

write_status RUNNING "router_false_block_and_second_window_contribution"
echo "=== ROUTER FALSE-BLOCK / FALSE-PASS + SECOND WINDOW LOSS CONTRIBUTION ==="
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_router_failure_audit.py"

for output in "$AUDIT" "$CONTRIB" "$CANDIDATES" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo "RASCHKE_ROUTER_FAILURE_AUDIT_OUTPUT_MISSING:$output" >&2
    exit 3
  fi
done

write_status DONE "router_failure_and_loss_contribution_complete"

echo "=== ROUTER FAILURE SUMMARY ==="
jq '{
  status,
  verdict,
  diagnostic_summary,
  routers: [.router_audit | to_entries[] | {
    router: .key,
    diagnosis: .value.diagnosis,
    second_window: {
      blocked_events: .value.second_holdout_90d.blocked_events,
      useful_blocked_loss_R: .value.second_holdout_90d.useful_blocked_loss_R,
      false_blocked_win_R: .value.second_holdout_90d.false_blocked_win_R,
      false_passed_loss_R: .value.second_holdout_90d.false_passed_loss_R,
      actual_router_delta_R: .value.second_holdout_90d.actual_router_delta_R
    }
  }],
  authority
}' "$AUDIT"

echo "=== SPLIT CANDIDATES ==="
jq '{status, candidate_count, next, candidates}' "$CANDIDATES"

echo "RASCHKE_ROUTER_FAILURE_AUDIT_JOB_DONE"
