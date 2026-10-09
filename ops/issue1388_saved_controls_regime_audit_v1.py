"""Source-frozen, saved-only 30m trade attribution. No economic simulation.

All outcomes below are descriptive on consumed development history; never
use group labels to create a post-hoc admission filter, G-stage PASS or NAV.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("research/campaigns/scalp7_20260915/broad_rebuild_v2/results")
IDS = (
    "scalp7_keltner_hg_parent_utc30m_v2",
    "scalp7_squeeze_panic_cost4_parent_utc30m_v2",
)

def group(rows):
    n = len(rows)
    gross = sum(float(r["gross_bps"]) for r in rows)
    cost = sum(float(r["cost_bps"]) for r in rows)
    net = sum(float(r["net_bps"]) for r in rows)
    if abs(gross - cost - net) > 1e-5:
        raise RuntimeError("GROSS_COST_NET_DRIFT")
    return {
        "T": n,
        "gross_bps": round(gross, 8),
        "cost1x_bps": round(cost, 8),
        "net1x_bps": round(net, 8),
        "net2x_same_fills_bps": round(gross - 2 * cost, 8),
        "win_count": sum(float(r["net_bps"]) > 0 for r in rows),
        "gross_positive_count": sum(float(r["gross_bps"]) > 0 for r in rows),
    }

def load(identity):
    meta = json.loads((ROOT / (identity + ".json")).read_text(encoding="utf-8"))
    compressed = (ROOT / (identity + ".trades.json.gz")).read_bytes()
    digest = hashlib.sha256(compressed).hexdigest()
    if digest != meta["ledger_sha256"]:
        raise RuntimeError("SAVED_LEDGER_SHA_MISMATCH:" + identity)
    root = json.loads(gzip.decompress(compressed))
    if not isinstance(root, dict) or not isinstance(root.get("trades"), list):
        raise RuntimeError("SAVED_TRADES_SHAPE_MISMATCH")
    rolling = [r for r in root["trades"] if str(r.get("window_label", "")).startswith("rolling_")]
    if len(rolling) != meta["rolling1x"]["T"]:
        raise RuntimeError("ROLLING_T_MISMATCH:" + identity)
    stats = group(rolling)
    for k, b in [
        ("gross_bps", meta["rolling1x"]["Gross_bps"]),
        ("cost1x_bps", meta["rolling1x"]["Cost_bps"]),
        ("net1x_bps", meta["rolling1x"]["Net_bps"]),
        ("net2x_same_fills_bps", meta["rolling2x"]["Net_bps"]),
    ]:
        if abs(stats[k] - float(b)) > 1e-5:
            raise RuntimeError("SAVED_ECONOMIC_TOTAL_DRIFT:" + identity + ":" + k)
    for row in rolling:
        signal = row.get("signal")
        if not isinstance(signal, dict) or not isinstance(signal.get("meta"), dict):
            raise RuntimeError("ENTRY_FEATURE_SOURCE_NOT_BOUND")
        ts = int(row["signal_ts_ms"])
        entry = int(row["entry_ts_ms"])
        avail = int(signal["meta"]["feature_available_ts_ms"])
        if not (avail <= ts <= entry):
            raise RuntimeError("FUTURE_DECISION_FEATURE_OR_ENTRY")
        if row["regime"] != signal["meta"]["regime"]:
            raise RuntimeError("ENTRY_REGIME_DRIFT")
    return rolling, {
        "git_path_prefix": str(ROOT / identity),
        "ledger_sha256": digest,
        "rolling_summary": stats,
        "rolling_result_state": meta["state"],
        "formal_fresh_T": meta["fresh_T"],
    }

def breakdown(rows, field):
    bucket = defaultdict(list)
    for row in rows:
        bucket[str(field(row))].append(row)
    return {name: group(items) for name, items in sorted(bucket.items())}

def interval_overlaps(a, b):
    # Only records coexisting historical exposure, no assumed portfolio NAV.
    n_pairs = n_same_symbol = 0
    rolling8_pairs = 0
    examples = []
    for x in a:
        for y in b:
            if max(int(x["entry_ts_ms"]), int(y["entry_ts_ms"])) < min(int(x["exit_ts_ms"]), int(y["exit_ts_ms"])):
                n_pairs += 1
                n_same_symbol += x["symbol"] == y["symbol"]
                rolling8_pairs += x["window_label"] == y["window_label"] == "rolling_8"
                if len(examples) < 4:
                    examples.append({"keltner_symbol": x["symbol"], "squeeze_symbol": y["symbol"], "keltner_regime": x["regime"], "squeeze_regime": y["regime"], "at_window": x["window_label"]})
    return {"overlapping_cross_strategy_trade_pairs": n_pairs, "same_symbol_pairs": n_same_symbol, "both_rolling8_pairs": rolling8_pairs, "examples": examples}

def main(output):
    stored={}
    report={"schema":"zel.saved_parent_causal_regime_attribution.v1","status":"READ_ONLY_DEVELOPMENT_DIAGNOSTIC_ONLY",
        "method":"saved-fills after-cost group descriptive; no replay, fit or threshold search",
        "cost_stress":"2x same-fill costs, not leverage",
        "formal_profit_credit":0, "formal_new_survivor":0,
        "limitations":["completed trades only; misses rejected/occupied/unresolved opportunity differences",
            "regime grouping is a source-causal signal field, but conditioning on performance now is post-hoc research",
            "no absolute independent OOS, historical receipt delay, actual historical funding, margin or account NAV",
            "one unusually profitable rolling window may dominate both; shared attribution is NOT portfolio returns"]}
    for identity in IDS:
        rows,metadata=load(identity)
        stored[identity]=rows
        meta0=rows[0]["signal"]["meta"] if rows else {}
        first=rows[0]["signal"] if rows else {}
        metadata["entry_signal_keys"]=sorted(first)
        metadata["entry_meta_keys"]=sorted(meta0)
        metadata["by_entry_regime"]=breakdown(rows, lambda r:r["regime"])
        metadata["by_costed_symbol"]=breakdown(rows, lambda r:r["symbol"])
        metadata["by_rolling_window"]=breakdown(rows, lambda r:r["window_label"])
        metadata["by_exit_reason_outcome_only"]=breakdown(rows, lambda r:r["reason"])
        metadata["rolling8_vs_other"]=breakdown(rows, lambda r:"rolling8" if r["window_label"]=="rolling_8" else "other")
        metadata["native_cost_gate_atr_price_coverage"]=sum(isinstance(r["signal"]["meta"].get("atr_price"),(float,int)) for r in rows)
        metadata["signal_available_before_entry_count"]=len(rows)
        report[identity]=metadata
    report["overlap_diagnostic"]=interval_overlaps(stored[IDS[0]], stored[IDS[1]])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print("CAUSAL_REGIME_SAVED_DIAGNOSTIC",json.dumps({
        "keltner_sha":report[IDS[0]]["ledger_sha256"],
        "squeeze_sha":report[IDS[1]]["ledger_sha256"],
        "keltner":report[IDS[0]]["by_entry_regime"],
        "squeeze":report[IDS[1]]["by_entry_regime"],
        "keltner_signal_keys":report[IDS[0]]["entry_signal_keys"],
        "keltner_meta_keys":report[IDS[0]]["entry_meta_keys"],
        "overlap":report["overlap_diagnostic"],
        "no_economic_run":True
    },sort_keys=True),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    main(args.output)
