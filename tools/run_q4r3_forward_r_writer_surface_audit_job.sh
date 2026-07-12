#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-writer-audit}
STATUS=$ROOT/runtime/q4r3_forward_r_writer_surface_audit_job_latest.json
LOG=$ROOT/runtime/q4r3_forward_r_writer_surface_audit_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

FREEZE=$ROOT/runtime/q4r3_raschke_freeze_manifest_latest.json
SURFACE=$ROOT/runtime/q4r3_forward_r_writer_surface_latest.json
CONTRACT=$ROOT/runtime/q4r3_forward_r_contract_latest.json
DECISION=$ROOT/runtime/q4r3_forward_r_writer_decision_latest.json
HTML=$ROOT/runtime/q4r3_forward_r_writer_surface_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$FREEZE" "$SURFACE" "$CONTRACT" "$DECISION" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "freeze": Path(sys.argv[5]),
    "surface": Path(sys.argv[6]),
    "contract": Path(sys.argv[7]),
    "decision": Path(sys.argv[8]),
    "html": Path(sys.argv[9]),
}
payload = {
    "job": "q4r3_forward_r_writer_surface_audit",
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
    "final_holdout_opened": False,
}
if paths["freeze"].exists():
    try:
        freeze = json.loads(paths["freeze"].read_text(errors="ignore"))
        payload["raschke_state"] = freeze.get("state")
        payload["raschke_best_preserved_candidate"] = freeze.get("best_preserved_candidate")
    except Exception as exc:
        payload["freeze_read_error"] = repr(exc)
if paths["decision"].exists():
    try:
        decision = json.loads(paths["decision"].read_text(errors="ignore"))
        for key in (
            "status",
            "verdict",
            "action",
            "next_action",
            "dominant_writer",
            "stable_id_join_rate_pct",
            "join_explicit_risk_ready_count",
            "join_formula_ready_count",
            "close_explicit_realized_r_count",
            "close_usdt_plus_explicit_risk_count",
            "missing_strategy_count",
            "historical_contract_state_counts",
            "historical_adapter_r_ready_rows_appended",
            "next_modules",
        ):
            payload[f"result_{key}" if key == "status" else key] = decision.get(key)
    except Exception as exc:
        payload["decision_read_error"] = repr(exc)
temporary = status_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
temporary.replace(status_path)
PY
}

on_error() {
  local code=$?
  trap - ERR
  write_status FAILED "exit_code=$code" || true
  echo Q4R3_FORWARD_R_WRITER_SURFACE_AUDIT_JOB_FAILED exit_code=$code >&2
  exit "$code"
}
trap on_error ERR

if [ ! -x "$PYTHON_BIN" ]; then
  echo PYTHON_BIN_MISSING:$PYTHON_BIN >&2
  exit 127
fi

mkdir -p "$ROOT/runtime"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

for required in \
  "$WORKTREE/tools/q4r3_forward_r_writer_surface_audit.py" \
  "$WORKTREE/tests/test_q4r3_forward_r_writer_surface_audit.py" \
  "$ROOT/runtime/q4r3_closed_pnl_contract_adapter_decision_latest.json" \
  "$ROOT/runtime/q4r3_closed_pnl_contract_adapter_audit_latest.json" \
  "$ROOT/runtime/q4r3_25_strategy_realized_r_coverage_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json"
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$FREEZE" "$SURFACE" "$CONTRACT" "$DECISION" "$HTML"
write_status RUNNING tests

echo === FORWARD R WRITER SURFACE AUDIT TESTS ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" -m pytest -q tests/test_q4r3_forward_r_writer_surface_audit.py
)

write_status RUNNING freeze_and_trace_forward_writer_surface

echo === RASCHKE FREEZE AND FORWARD R WRITER SURFACE AUDIT ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" tools/q4r3_forward_r_writer_surface_audit.py
)

for output in "$FREEZE" "$SURFACE" "$CONTRACT" "$DECISION" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE raschke_frozen_forward_r_writer_surface_complete

echo === FREEZE ===
jq . "$FREEZE"
echo === DECISION ===
jq . "$DECISION"
echo === RUNTIME CONTRACT SUMMARY ===
jq '{close_record_count:.runtime.close_record_count,open_record_count:.runtime.open_record_count,close_with_stable_id_count:.runtime.close_with_stable_id_count,joinable_close_open_count:.runtime.joinable_close_open_count,join_explicit_risk_ready_count:.runtime.join_explicit_risk_ready_count,join_formula_ready_count:.runtime.join_formula_ready_count,stable_id_join_rate_pct:.runtime.stable_id_join_rate_pct,top_close_sources:.runtime.top_close_sources[0:10]}' "$SURFACE"
echo === TOP WRITER CANDIDATES ===
jq '{dominant_single_writer:.code.dominant_single_writer,dominant_writer:.code.dominant_writer,candidates:.code.candidates[0:15]}' "$SURFACE"
echo Q4R3_FORWARD_R_WRITER_SURFACE_AUDIT_JOB_DONE
