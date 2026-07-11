#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
PYTHON_BIN="$ROOT/.venv/bin/python"
OVERLAY=${Q4R3_ROUTE_A_OVERLAY_ROOT:-/tmp/q4r3-route-a-loss-forensic}
STATUS="$ROOT/runtime/q4r3_route_a_raschke_loss_forensic_job_latest.json"
RESULT="$ROOT/runtime/q4r3_route_a_raschke_loss_forensic_latest.json"
CLUSTERS="$ROOT/runtime/common_loss_clusters.json"
PAIRS="$ROOT/runtime/loss_vs_win_matched_pairs.json"
FIXES="$ROOT/runtime/raschke_structural_fix_candidates.json"
CHART_INDEX="$ROOT/runtime/loss_cluster_chart_pack/index.html"
LOG="$ROOT/runtime/q4r3_route_a_raschke_loss_forensic_job.log"
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 127
fi

write_status() {
  local state="$1"
  local reason="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$reason" "$START_TS" "$RESULT" "$CLUSTERS" "$PAIRS" "$FIXES" "$CHART_INDEX" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status_path = Path(sys.argv[1])
state = sys.argv[2]
reason = sys.argv[3]
started_at = sys.argv[4]
paths = {
    "summary": Path(sys.argv[5]),
    "clusters": Path(sys.argv[6]),
    "matched_pairs": Path(sys.argv[7]),
    "fix_candidates": Path(sys.argv[8]),
    "chart_pack": Path(sys.argv[9]),
}
payload = {
    "job": "q4r3_route_a_raschke_loss_cluster_forensic",
    "state": state,
    "reason": reason,
    "started_at": started_at,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "outputs": {key: str(path) for key, path in paths.items()},
    "output_exists": {key: path.exists() for key, path in paths.items()},
    "raw_path_contract": {
        "prior_holdout_90d": "*_1m_90d_pre30d.json",
        "second_holdout_90d": "*_1m_90d_pre90d.json",
    },
    "order_authority": "blocked",
    "execution_authority": "none",
    "real_order_enabled": False,
    "paper_request_written": False,
    "live_execution_allowed": False,
    "production_strategy_modified": False,
}
if paths["summary"].exists():
    try:
        result = json.loads(paths["summary"].read_text(errors="ignore"))
        payload["result_status"] = result.get("status")
        payload["verdict"] = result.get("verdict")
        payload["cluster_count"] = result.get("cluster_count")
        payload["structural_fix_candidates"] = result.get("structural_fix_candidates", [])
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
  echo "RASCHKE_LOSS_FORENSIC_JOB_FAILED exit_code=$code" >&2
  exit "$code"
}
trap on_error ERR

mkdir -p "$ROOT/runtime"
exec > >(tee -a "$LOG") 2>&1
rm -f "$RESULT" "$CLUSTERS" "$PAIRS" "$FIXES"
rm -rf "$ROOT/runtime/loss_cluster_chart_pack"
write_status RUNNING "preflight"

for required in \
  "$OVERLAY/tools/q4r3_route_a_raschke_loss_cluster_forensic.py" \
  "$OVERLAY/tools/q4r3_route_a_raschke_loss_cluster_forensic_runner.py" \
  "$OVERLAY/tests/test_raschke_loss_cluster_forensic.py" \
  "$OVERLAY/tests/test_raschke_loss_forensic_paths.py" \
  "$ROOT/runtime/q4r3_route_a_raschke_forensic_trades_latest.json" \
  "$ROOT/runtime/q4r3_route_a_raschke_second_holdout_trades_latest.json"
do
  if [ ! -f "$required" ]; then
    echo "RASCHKE_LOSS_FORENSIC_INPUT_MISSING:$required" >&2
    exit 2
  fi
done

for symbol in BTCUSDT ETHUSDT SOLUSDT XRPUSDT LINKUSDT; do
  for path in \
    "$ROOT/data/oos_a2/frozen_pre30d/${symbol}_1m_90d_pre30d.json" \
    "$ROOT/data/oos_a3/raschke_second_holdout/${symbol}_1m_90d_pre90d.json"
  do
    if [ ! -f "$path" ]; then
      echo "RASCHKE_LOSS_FORENSIC_RAW_MISSING:$path" >&2
      exit 2
    fi
  done
done

echo "=== RASCHKE LOSS FORENSIC TESTS ==="
write_status RUNNING "tests"
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" -m pytest -q \
  "$OVERLAY/tests/test_raschke_loss_cluster_forensic.py" \
  "$OVERLAY/tests/test_raschke_loss_forensic_paths.py"

echo "=== RASCHKE CROSS-WINDOW LOSS CLUSTER FORENSIC ==="
write_status RUNNING "cluster_mfe_mae_matched_chart_analysis"
Q4R3_ROUTE_A_OVERLAY_ROOT="$OVERLAY" \
PYTHONPATH="$OVERLAY:$ROOT" \
  "$PYTHON_BIN" \
  "$OVERLAY/tools/q4r3_route_a_raschke_loss_cluster_forensic_runner.py"

for output in "$RESULT" "$CLUSTERS" "$PAIRS" "$FIXES" "$CHART_INDEX"; do
  if [ ! -s "$output" ]; then
    echo "RASCHKE_LOSS_FORENSIC_OUTPUT_MISSING:$output" >&2
    exit 3
  fi
done

write_status DONE "forensic_complete_no_strategy_rejection"

echo "=== RASCHKE LOSS FORENSIC RESULT ==="
jq '{
  status,
  verdict,
  cluster_count,
  structural_fix_candidates,
  outputs,
  authority
}' "$RESULT"

echo "=== TOP COMMON ADVERSE SIGNATURES ==="
jq '{
  candle_direction: .recurring_adverse_signatures.candle_direction[:10],
  source_core: .recurring_adverse_signatures.source_core[:10]
}' "$CLUSTERS"

echo "=== FIX CANDIDATES ==="
jq . "$FIXES"

echo "RASCHKE_LOSS_FORENSIC_JOB_DONE"
