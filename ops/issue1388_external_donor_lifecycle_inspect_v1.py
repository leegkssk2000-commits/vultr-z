"""Exact source notebook rule inspection only: never execute donor code."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess

SOURCE = pathlib.Path("notebooks/single-backtest/bitcoin-breakout-atr.ipynb")
MATCH = re.compile(
    r"(calculate_indicators|decide_trades|stop_loss|take_profit|ATR|time_bucket|"
    r"fee|slippage|reserve|risk|chain_id|pair|position|short|trailing|"
    r"backtest|universe|equity|sliding|lookback|rolling|liquidit)",
    re.IGNORECASE,
)

def analyze(source: pathlib.Path):
    root = source.resolve()
    path = root / SOURCE
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    cells = obj.get("cells") or []
    matched=[]
    summary=[]
    for i,cell in enumerate(cells):
        content = "".join(cell.get("source") or [])
        if MATCH.search(content):
            # Parsing code and markdown as primary source, no execution or import.
            summary.append({"idx":i,"type":cell.get("cell_type"),"code_len":len(content),"keyword_count":len(MATCH.findall(content))})
            for pattern in (
                "def decide_trades", "def create_trading_universe",
                "def calculate_indicators", "def decide_price_structure",
                "def get_position_size",
                "time_bucket", "stop_loss", "take_profit",
                "trailing", "trading_fee", "slippage",
                "reserve_currency", "MAX_POSITIONS",
                "ATR", "bb_width", "buy_signal",
            ):
                if pattern.lower() in content.lower():
                    start=max(0,content.lower().find(pattern.lower())-130)
                    matched.append({"index":i,"tag":pattern,"excerpt":content[start:start+1100]})
    manifest={
        "source_repository":"tradingstrategy-ai/getting-started",
        "source_commit":"0be3392775ffd2567a617153a3c8d42fb0e57476",
        "original_notebook_path":str(SOURCE),
        "original_notebook_sha256":hashlib.sha256(raw).hexdigest(),
        "notebook_cells":len(cells),
        "matched_cell_count":len(summary),
        "matched_entries":summary,
        "source_excerpts":matched[:85],
        "frozen_core_strategy_cells":[
            {"cell_index":i,"cell_sha256":hashlib.sha256("".join(cells[i].get("source") or []).encode("utf-8")).hexdigest(),
             "code":"".join(cells[i].get("source") or [])}
            for i in (4,9,11) if i < len(cells)
        ],
        "root_LICENSE_file_exists":(root/"LICENSE").exists(),
        "root_pyproject_declared_license":[l for l in (root/"pyproject.toml").read_text().splitlines() if "license" in l.lower()][:7],
        "copied_code_or_executed_notebook":False,
        "economic_credit":0,
        "source_complete_lifecycle_verified":False,
        "disposition":"PRIMARY_NOTEBOOK_STATIC_EXTRACTION_PENDING_CAUSAL_FULL_LIFECYCLE_REVIEW",
    }
    return manifest

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=pathlib.Path,required=True)
    ap.add_argument("--out",type=pathlib.Path,required=True)
    v=ap.parse_args()
    rec=analyze(v.source)
    v.out.parent.mkdir(parents=True,exist_ok=True)
    v.out.write_text(json.dumps(rec,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("PRIMARY_NOTEBOOK_EXTRACT",json.dumps({
        "sha256":rec["original_notebook_sha256"],
        "cells":rec["notebook_cells"],"matched":rec["matched_cell_count"],
        "root_license_exists":rec["root_LICENSE_file_exists"],
        "pyproject_license":rec["root_pyproject_declared_license"],
        "matched_entries":rec["matched_entries"][:28],
        "rule_excerpts":rec["source_excerpts"][:18],
    },sort_keys=True),flush=True)

if __name__=="__main__":
    main()
