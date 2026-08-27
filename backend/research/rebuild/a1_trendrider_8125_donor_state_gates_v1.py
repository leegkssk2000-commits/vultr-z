#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate, metrics, trade_key
from backend.research.rebuild.a1_trend_rider_wr80_winner_restore_attribution_v1 import _enrich

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
SCHEMA = "zel.a1.trendrider.8125.donor_state_gates.v1"
AXES = ("st_gap_state", "chase_state", "atr_state", "geometry_balance")


def read(path: Path) -> dict[str, Any]:
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins=[float(x["net_bps"]) for x in rows if float(x["net_bps"])>0]
    losses=[-float(x["net_bps"]) for x in rows if float(x["net_bps"])<0]
    if not wins or not losses: return None
    return (sum(wins)/len(wins))/(sum(losses)/len(losses))


def strict(parent: list[dict[str, Any]], subset: list[dict[str, Any]]) -> dict[str, Any]:
    r=evaluate({"strategy_id":"trend_rider","trades":parent},{"strategy_id":"trend_rider","trades":subset})
    pp=payoff(parent); cp=payoff(parent+subset)
    checks=dict(r.get("checks") or {})
    checks["combined_payoff_non_decrease"] = pp is None or (cp is not None and cp>=pp)
    return {"pass":all(bool(x) for x in checks.values()),"checks":checks,"combined_metrics":r["combined_metrics"],"combined_payoff":cp}


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out",type=Path,default=Path("out/a1_trendrider_8125_donor_state_gates_v1.json")); args=ap.parse_args()
    pd=read(PARENT); parent=[dict(x) for x in pd.get("trades") or []]
    if len(parent)!=16 or abs(float(pd["metrics"]["win_rate"])-0.8125)>1e-12: raise RuntimeError("PARENT_AUTHORITY_MISMATCH")
    current=rebuild_current(); donor=[dict(x) for x in current.get("trades") or []]
    if len(donor)!=12: raise RuntimeError(f"CURRENT12_EXPECTED:{len(donor)}")
    pkeys={trade_key(x) for x in parent}; distinct=[x for x in donor if trade_key(x) not in pkeys]
    if len(distinct)!=8: raise RuntimeError(f"DISTINCT8_EXPECTED:{len(distinct)}")
    _enrich(current, distinct)
    if any(bool(x.get("feature_missing")) for x in distinct): raise RuntimeError("DISTINCT8_FEATURE_MISSING")
    results=[]
    for axis in AXES:
        vals=sorted({str(x.get(axis)) for x in distinct})
        for value in vals:
            subset=[x for x in distinct if str(x.get(axis))==value]
            if not subset: continue
            s=strict(parent,subset)
            results.append({
                "axis":axis,"value":value,"selected_T":len(subset),
                "keys":[list(trade_key(x)) for x in subset],
                "selected_metrics":metrics(subset),
                "combined_metrics":s["combined_metrics"],"combined_payoff":s["combined_payoff"],
                "strict_all_metric_pass":s["pass"],"failed_checks":[k for k,v in s["checks"].items() if not v],
                "preentry_only":True,"numeric_threshold_sweep":False,
            })
    results.sort(key=lambda x:(x["strict_all_metric_pass"],x["selected_T"],x["combined_metrics"]["net_pnl_bps"]),reverse=True)
    best=next((x for x in results if x["strict_all_metric_pass"]),None)
    compact=[]
    for x in distinct:
        compact.append({
            "key":list(trade_key(x)),"net_bps":float(x["net_bps"]),"reason":x.get("reason"),
            "st_gap_state":x.get("st_gap_state"),"chase_state":x.get("chase_state"),"atr_state":x.get("atr_state"),"geometry_balance":x.get("geometry_balance"),
        })
    out={
        "schema_version":SCHEMA,
        "state":"PASS_HISTORICAL_STATE_GATE_FOUND" if best else "HOLD_NO_NAMED_STATE_GATE_PRESERVES_8125",
        "strategy_id":"trend_rider","parent_T":16,"parent_metrics":metrics(parent),"parent_payoff":payoff(parent),
        "current12_T":12,"overlap_T":4,"distinct_donor_T":8,"distinct_attribution":compact,
        "axes_tested":list(AXES),"gate_results":results,"best_historical_gate":best,
        "historical_discovery_promotable":False,"fresh_prospective_confirmation_required":True,"parent_immutable":True,
        "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","action":"hold",
        "next":"FREEZE_GATE_THEN_FRESH_VALIDATE" if best else "CURRENT12_EXHAUSTED_AS_DIRECT_DONOR; WAIT_FOR_NEW_UNSEEN_T_OR_NEW_CAUSAL_FEATURE_AXIS",
    }
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":out["state"],"best":best},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
