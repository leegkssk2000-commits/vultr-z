#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_trendrider_current12_fresh2_reservoir_v1 import rebuild_current
from backend.research.rebuild.a1_top5_additive_entry_union_v1 import metrics, trade_key
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
SCHEMA = "zel.a1.trendrider.8125.positive2_exit_ceiling.v1"
HORIZONS = (48,72,96,120,168)


def read(path: Path) -> dict[str, Any]:
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins=[float(x["net_bps"]) for x in rows if float(x["net_bps"])>0]
    losses=[-float(x["net_bps"]) for x in rows if float(x["net_bps"])<0]
    if not wins or not losses: return None
    return (sum(wins)/len(wins))/(sum(losses)/len(losses))


def sl_aware_mfe_net(t: Mapping[str, Any], bars: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    entry_ts=int(t["entry_ts"]); entry=float(t["entry"]); side=str(t["side"])
    cost=float(t.get("realized_cost_bps") or 0.0)
    sl=t.get("sl")
    if sl is None:
        geom=t.get("intent_geometry") or {}
        sl=geom.get("sl") if isinstance(geom, Mapping) else None
    if sl is None: raise RuntimeError(f"SL_MISSING:{trade_key(t)}")
    sl=float(sl)
    rows=[b for b in bars if int(b["ts_ms"])>=entry_ts]
    rows.sort(key=lambda x:int(x["ts_ms"]))
    rows=rows[:horizon]
    if not rows: raise RuntimeError(f"NO_BARS_AFTER_ENTRY:{trade_key(t)}")
    best=entry; best_ts=entry_ts; sl_hit=False; used=0
    for b in rows:
        used+=1
        high=float(b["high"]); low=float(b["low"])
        if side=="long":
            if low<=sl:
                sl_hit=True; break
            if high>best: best=high; best_ts=int(b["ts_ms"])
        elif side=="short":
            if high>=sl:
                sl_hit=True; break
            if low<best: best=low; best_ts=int(b["ts_ms"])
        else: raise RuntimeError(f"UNKNOWN_SIDE:{side}")
    gross=((best/entry)-1.0)*10000.0 if side=="long" else ((entry/best)-1.0)*10000.0
    return {"horizon_bars":horizon,"bars_used":used,"sl_hit_before_horizon":sl_hit,"best_price":best,"best_ts":best_ts,"gross_mfe_bps":gross,"net_mfe_ceiling_bps":gross-cost}


def adjusted(t: Mapping[str, Any], net_bps: float) -> dict[str, Any]:
    x=dict(t); x["net_bps"]=float(net_bps); x["gross_bps"]=float(net_bps)+float(t.get("realized_cost_bps") or 0.0); x["reason"]="DIAGNOSTIC_MFE_CEILING"; return x


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out",type=Path,default=Path("out/a1_trendrider_8125_positive2_exit_ceiling_v1.json")); args=ap.parse_args()
    parent_doc=read(PARENT); parent=[dict(x) for x in parent_doc.get("trades") or []]
    if len(parent)!=16 or abs(float(parent_doc["metrics"]["win_rate"])-0.8125)>1e-12: raise RuntimeError("PARENT_AUTHORITY_MISMATCH")
    current=rebuild_current(); donor=[dict(x) for x in current.get("trades") or []]
    pkeys={trade_key(x) for x in parent}; distinct=[x for x in donor if trade_key(x) not in pkeys]
    if len(distinct)!=8: raise RuntimeError(f"DISTINCT8_EXPECTED:{len(distinct)}")
    positives=[x for x in distinct if float(x["net_bps"])>0]
    if len(positives)!=2: raise RuntimeError(f"POSITIVE2_EXPECTED:{len(positives)}")
    bars_by={s:[dict(x) for x in ev.fetch_bars(s,"1h",1000)] for s in sorted({str(x["symbol"]) for x in positives})}
    parent_m=metrics(parent); parent_pay=payoff(parent)
    diagnostics=[]
    first_pass=None
    for h in HORIZONS:
        per=[]; adj=[]
        for t in positives:
            d=sl_aware_mfe_net(t,bars_by[str(t["symbol"])],h); per.append({"key":list(trade_key(t)),"realized_net_bps":float(t["net_bps"]),**d}); adj.append(adjusted(t,d["net_mfe_ceiling_bps"]))
        combined=parent+adj; cm=metrics(combined); cp=payoff(combined)
        checks={
            "wr_non_decrease":float(cm["win_rate"])>=float(parent_m["win_rate"]),
            "pnl_non_decrease":float(cm["net_pnl_bps"])>=float(parent_m["net_pnl_bps"]),
            "expectancy_non_decrease":float(cm["net_expectancy_bps"])>=float(parent_m["net_expectancy_bps"]),
            "pf_non_decrease":float(cm["profit_factor"])>=float(parent_m["profit_factor"]),
            "payoff_non_decrease":cp is not None and parent_pay is not None and cp>=parent_pay,
            "dd_non_increase":float(cm["drawdown_bps"])<=float(parent_m["drawdown_bps"]),
        }
        row={"horizon_bars":h,"per_trade":per,"adjusted_added_metrics":metrics(adj),"combined_metrics":cm,"combined_payoff":cp,"checks":checks,"all_metric_ceiling_pass":all(checks.values())}
        diagnostics.append(row)
        if first_pass is None and row["all_metric_ceiling_pass"]: first_pass=row
    result={
        "schema_version":SCHEMA,"state":"PASS_EXIT_CEILING_CAN_RESCUE_POSITIVE2" if first_pass else "HOLD_ENTRY_AMPLITUDE_CEILING_CONFIRMED_THROUGH_168H",
        "strategy_id":"trend_rider","parent_T":16,"parent_metrics":parent_m,"parent_payoff":parent_pay,
        "distinct_donor_T":8,"positive_donor_T":2,"positive_realized_metrics":metrics(positives),"positive_realized_payoff":payoff(positives),
        "positive_keys":[list(trade_key(x)) for x in positives],"diagnostics":diagnostics,
        "first_horizon_all_metric_ceiling_pass":first_pass["horizon_bars"] if first_pass else None,
        "diagnostic_only":True,"entry_identity_immutable":True,"sl_immutable":True,"historical_discovery_promotable":False,
        "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","action":"hold",
        "next":"DESIGN_EXIT_ONLY_RULE_ON_FROZEN_ENTRIES_THEN_FRESH_VALIDATE" if first_pass else "DO_NOT_TUNE_TIMEOUT_FOR_THESE_ROWS; SEEK_HIGHER_AMPLITUDE_ENTRY_GATE",
    }
    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"first_pass":result["first_horizon_all_metric_ceiling_pass"],"positive_keys":result["positive_keys"]},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
