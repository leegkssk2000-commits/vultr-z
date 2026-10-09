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
from statistics import median
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

        # Outcome classes are audit labels only; never use them as entry features.
        metadata["original_entry_price_examples"]=[r.get("entry_prices") for r in rows[:2]]
        metadata["original_signal_meta_examples"]=[r["signal"]["meta"] for r in rows[:2]]

        # Entry price is only considered at already-modelled next-open admission;
        # no future MFE/MAE / exit reason enters any candidate decision.
        def attr_cost_multiple(r):
            symbol = str(r["symbol"])
            entry = float(r["entry_prices"][symbol])
            attr = float(r["signal"]["meta"]["entry_cost_gate"]["atr_price"])
            frozen_cost = float(r["signal"]["meta"]["frozen_cost_bps"])
            if min(entry, attr, frozen_cost) <= 0:
                raise RuntimeError("NONPOSITIVE_ENTRY_GEOMETRY")
            return (attr / entry) * 10_000 / frozen_cost
        def cost_class(r):
            if float(r["gross_bps"]) - 2 * float(r["cost_bps"]) > 0:
                return "TWO_X_POSITIVE"
            return "ONE_X_ONLY_POSITIVE" if float(r["net_bps"]) > 0 else "ONE_X_NONPOSITIVE"
        ratio_groups = defaultdict(list)
        for r in rows:
            ratio_groups[cost_class(r)].append(attr_cost_multiple(r))
        metadata["entry_atr_to_cost_multiple_by_outcome_audit_only"]={
            k:{"T":len(v),"min":round(min(v),6),"median":round(median(v),6),"max":round(max(v),6)}
            for k,v in sorted(ratio_groups.items())
        }
        metadata["entry_atr_to_cost_multiple_by_window"]={
            k:{"T":len(v),"median":round(median(v),6)}
            for k,v in sorted((z,[attr_cost_multiple(r) for r in rows if r["window_label"]==z]) for z in set(r["window_label"] for r in rows))
        }
        metadata["by_regime_and_window8"]=breakdown(rows, lambda r:r["regime"]+("::rolling8" if r["window_label"]=="rolling_8" else "::other"))
        metadata["by_2x_cost_outcome_class"]=breakdown(rows, lambda r:("two_x_net_winner" if float(r["gross_bps"])-2*float(r["cost_bps"])>0 else "fragile_1x_winner" if float(r["net_bps"])>0 else "one_x_nonpositive"))
        metadata["class_by_regime"]=breakdown(rows, lambda r:r["regime"]+"::"+("two_x_net_winner" if float(r["gross_bps"])-2*float(r["cost_bps"])>0 else "fragile_1x_winner" if float(r["net_bps"])>0 else "one_x_nonpositive"))
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
        "entry_price_examples":report[IDS[0]]["original_entry_price_examples"],
        "entry_meta_examples":report[IDS[0]]["original_signal_meta_examples"],
        "keltner_regime_window8":report[IDS[0]]["by_regime_and_window8"],
        "squeeze_regime_window8":report[IDS[1]]["by_regime_and_window8"],
        "keltner_cost_classes":report[IDS[0]]["by_2x_cost_outcome_class"],
        "keltner_entry_atr_cost_geometry":report[IDS[0]]["entry_atr_to_cost_multiple_by_outcome_audit_only"],
        "squeeze_entry_atr_cost_geometry":report[IDS[1]]["entry_atr_to_cost_multiple_by_outcome_audit_only"],
        "keltner_regime_cost_class":report[IDS[0]]["class_by_regime"],
        "overlap":report["overlap_diagnostic"],
        "no_economic_run":True
    },sort_keys=True),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    main(args.output)
