#!/usr/bin/env bash
set -euo pipefail
PY=/home/z/z/.venv/bin/python
G=/opt/zel/research-runtime/jobs/structural-premium-vwap-closed-loop-v1/gen0
BASE=/opt/zel/research-runtime/jobs/structural-premium-no-trend-v1/work/replay/lane_checkpoints/vwap_revert
ENG=/opt/zel/research-runtime/jobs/structural-premium-durable-lane-v2/work/engine/replay_v1.py

echo '===COUNTS==='
for cid in A B C; do
  printf '%s ' "$cid"
  find "$G/runs/$cid/replay_w12/lane_checkpoints/vwap_revert" -type f -name '*.json.gz' 2>/dev/null | wc -l || true
done

"$PY" - "$ENG" "$BASE" "$G" <<'PYCODE'
import gzip
import importlib.util
import json
import sys
from pathlib import Path

engp, basep, g = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("delta_engine", engp)
e = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = e
assert spec.loader is not None
spec.loader.exec_module(e)

def read_lane(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)

def lane_key(row):
    return (str(row.get("window_id")), str(row.get("symbol")))

base = {}
for path in basep.glob("*.json.gz"):
    row = read_lane(path)
    base[lane_key(row)] = row

for cid in ("A", "B", "C"):
    root = g / "runs" / cid / "replay_w12" / "lane_checkpoints" / "vwap_revert"
    files = sorted(root.glob("*.json.gz")) if root.exists() else []
    if not files:
        continue
    cand_rows = []
    base_rows = []
    keys = []
    for path in files:
        row = read_lane(path)
        key = lane_key(row)
        keys.append(key)
        for trade in (row.get("result") or {}).get("closed_rows") or []:
            if trade.get("side") == "long":
                cand_rows.append(trade)
        baseline = base.get(key)
        if baseline:
            for trade in (baseline.get("result") or {}).get("closed_rows") or []:
                if trade.get("side") == "long":
                    base_rows.append(trade)
    cm = e.metrics(cand_rows)
    bm = e.metrics(base_rows)
    delta = {
        "sample": int(cm.get("sample_count") or 0) - int(bm.get("sample_count") or 0),
        "net_R": float(cm.get("net_R") or 0) - float(bm.get("net_R") or 0),
        "pf": float(cm.get("profit_factor") or 0) - float(bm.get("profit_factor") or 0),
        "maxDD_R": float(cm.get("max_drawdown_R") or 0) - float(bm.get("max_drawdown_R") or 0),
        "wr_pp": float(cm.get("win_rate_pct") or 0) - float(bm.get("win_rate_pct") or 0),
    }
    print("CANDIDATE", cid, "LANES", keys)
    print("BASE_MATCHED", json.dumps(bm, sort_keys=True))
    print("CAND_MATCHED", json.dumps(cm, sort_keys=True))
    print("DELTA", json.dumps(delta, sort_keys=True))
PYCODE

echo '===ACTIVE==='
pgrep -af "$G/runs/.*/engine/lane_w12.py" || true
