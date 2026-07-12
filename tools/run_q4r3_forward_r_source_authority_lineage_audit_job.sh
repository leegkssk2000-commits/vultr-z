#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN=$ROOT/.venv/bin/python
WORKTREE=${Q4R3_ROUTE_A_WORKTREE:-/tmp/q4r3-forward-r-source-lineage}
STATUS=$ROOT/runtime/q4r3_forward_r_source_authority_lineage_job_latest.json
LOG=$ROOT/runtime/q4r3_forward_r_source_authority_lineage_job.log
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

AUTHORITY=$ROOT/runtime/q4r3_forward_r_source_authority_latest.json
LINEAGE=$ROOT/runtime/q4r3_forward_r_writer_lineage_latest.json
DECISION=$ROOT/runtime/q4r3_forward_r_source_lineage_decision_latest.json
HTML=$ROOT/runtime/q4r3_forward_r_source_lineage_latest.html

write_status() {
  local state=$1
  local reason=${2:-}
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$AUTHORITY" "$LINEAGE" "$DECISION" "$HTML" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "authority": Path(sys.argv[5]),
    "lineage": Path(sys.argv[6]),
    "decision": Path(sys.argv[7]),
    "html": Path(sys.argv[8]),
}
payload = {
    "job": "q4r3_forward_r_source_authority_lineage_audit",
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
if paths["decision"].exists():
    try:
        decision = json.loads(paths["decision"].read_text(errors="ignore"))
        for key in (
            "status", "verdict", "action", "next_action", "authoritative_file_count",
            "stable_id_join_rate_pct", "joined_with_explicit_risk_count",
            "joined_formula_ready_count", "dominant_single_writer", "dominant_writer", "next_modules",
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
  echo Q4R3_FORWARD_R_SOURCE_AUTHORITY_LINEAGE_JOB_FAILED exit_code=$code >&2
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
  "$WORKTREE/tools/q4r3_forward_r_source_authority_lineage_audit.py" \
  "$WORKTREE/tests/test_q4r3_forward_r_source_authority_lineage_audit.py" \
  "$ROOT/runtime/q4r3_raschke_freeze_manifest_latest.json" \
  "$ROOT/runtime/q4r3_forward_r_writer_surface_latest.json" \
  "$ROOT/runtime/q4r3_forward_r_writer_decision_latest.json"
do
  if [ ! -s "$required" ]; then
    echo REQUIRED_INPUT_MISSING:$required >&2
    exit 2
  fi
done

rm -f "$AUTHORITY" "$LINEAGE" "$DECISION" "$HTML"
write_status RUNNING tests

echo === FORWARD R SOURCE AUTHORITY LINEAGE TESTS ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" -m pytest -q tests/test_q4r3_forward_r_source_authority_lineage_audit.py
)

write_status RUNNING classify_sources_trace_identity_and_writer_lineage

echo === FORWARD R SOURCE AUTHORITY AND WRITER LINEAGE ===
(
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE:$ROOT" \
  Q4R3_ROUTE_A_WORKTREE="$WORKTREE" \
  Q4R3_ROUTE_A_OVERLAY_ROOT="$WORKTREE" \
  "$PYTHON_BIN" tools/q4r3_forward_r_source_authority_lineage_audit.py
)

for output in "$AUTHORITY" "$LINEAGE" "$DECISION" "$HTML"; do
  if [ ! -s "$output" ]; then
    echo REQUIRED_OUTPUT_MISSING:$output >&2
    exit 3
  fi
done

write_status DONE source_authority_and_writer_lineage_complete

echo === DECISION ===
jq . "$DECISION"
echo === AUTHORITATIVE SOURCES ===
jq '{raschke_state,class_counts,authoritative_files:[.authoritative_files[0:20][]|{path,open_rows,closed_rows,stable_id_rows,risk_rows,realized_r_rows,realized_usdt_rows}]}' "$AUTHORITY"
echo === RUNTIME LINEAGE ===
jq '.runtime | {open_record_count,close_record_count,open_with_stable_id_count,close_with_stable_id_count,unique_open_ids,unique_close_ids,joined_unique_ids,stable_id_join_rate_pct,joined_with_explicit_risk_count,joined_formula_ready_count,joined_with_explicit_realized_r_count,top_source_pairs}' "$LINEAGE"
echo === PRODUCTION WRITER LINEAGE ===
jq '.code | {dominant_single_writer,dominant_writer,second_score,production_candidates:.production_candidates[0:15],excluded_diagnostic_candidates:.excluded_diagnostic_candidates[0:10]}' "$LINEAGE"
echo Q4R3_FORWARD_R_SOURCE_AUTHORITY_LINEAGE_JOB_DONE
