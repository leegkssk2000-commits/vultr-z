#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

BASE = {
  "candidate_id":"new_architecture_basis_premium_collector",
  "strategy_id":"NEW","provider":"openai","required_sources":["ohlcv","volume"],
  "executable_spec":{
    "bar_interval":"1d","features":[{"name":"ret_sma_7","formula":"sma(ret(1),7)"}],
    "entry_rule":"ret(1) < -0.02 or ret(1) > 0.02","side_rule":"long if ret(1) < -0.02 else short",
    "exit_rule":"time_stop","max_hold_bars":12,"entry_timing":"next_bar_open",
    "cost_model":"verified_14bps_or_more","development_data_rule":"strictly_before_GEN1_boundary",
    "parameter_provenance":"design_prior_or_primary_evidence_only"
  }
}


def _eval(c:dict[str,Any], symbols:tuple[str,...]|None=None)->dict[str,Any]:
    old=econ.SYMBOLS
    try:
        if symbols is not None: econ.SYMBOLS=symbols
        return econ.evaluate_candidate(c)
    finally: econ.SYMBOLS=old


def _m(row:dict[str,Any])->dict[str,Any]:
    x=row.get("metrics") or {}
    return {k:x.get(k) for k in ("trades","gross_expectancy_bps","net_expectancy_bps","net_pnl_bps","profit_factor","payoff","win_rate","drawdown_bps","events_per_day","net_bps_per_calendar_day","cost_bps_per_trade")}


def _variant(cid:str,entry:str,side:str)->dict[str,Any]:
    c=deepcopy(BASE); c["candidate_id"]=cid; c["executable_spec"]["entry_rule"]=entry; c["executable_spec"]["side_rule"]=side; return c


def _stats(rows:list[dict[str,Any]])->dict[str,Any]:
    net=[float(x["net_bps"]) for x in rows]; gross=[float(x["gross_bps"]) for x in rows]; n=len(rows)
    return {"trades":n,"gross_expectancy_bps":sum(gross)/n if n else None,"net_expectancy_bps":sum(net)/n if n else None,"net_pnl_bps":sum(net),"profit_factor":econ._pf(net) if n else None,"payoff":econ._payoff(net) if n else None,"win_rate":sum(x>0 for x in net)/n if n else None,"drawdown_bps":econ._dd(net) if n else 0.0}


def _actual_trades()->list[dict[str,Any]]:
    out=[]; spec=BASE["executable_spec"]; hold=int(spec["max_hold_bars"])
    for symbol in econ.SYMBOLS:
        rs=econ.bars(symbol,"1d"); eng=econ.Expr(rs,{})
        i=30
        while i<len(rs)-1:
            try: fire=bool(eng.eval(spec["entry_rule"],i))
            except Exception: fire=False
            if not fire: i+=1; continue
            side=econ._side(spec["side_rule"],eng,i); entry_i=i+1; exit_i=min(entry_i+hold-1,len(rs)-1)
            entry_px=rs[entry_i]["open"]; exit_px=rs[exit_i]["close"]
            gross=(exit_px/entry_px-1.0)*10000*(1 if side=="long" else -1); net=gross-econ.COST_BPS
            prev=rs[i-1]["close"]; signal_ret=rs[i]["close"]/prev-1.0 if prev else 0.0
            w=[x["close"] for x in rs[max(0,i-49):i+1]]; sma50=sum(w)/len(w)
            regime="above_sma50" if rs[i]["close"]>=sma50 else "below_sma50"
            out.append({"symbol":symbol,"side":side,"gross_bps":gross,"net_bps":net,"signal_ret1":signal_ret,"signal_regime50":regime,"signal_year":datetime.fromtimestamp(rs[i]["ts"]/1000,tz=timezone.utc).year,"entry_ts":int(rs[entry_i]["ts"]),"exit_ts":int(rs[exit_i]["ts"])})
            i=max(i+1,exit_i+1)
    return out


def _group(trades:list[dict[str,Any]],key:str)->dict[str,Any]:
    vals={}
    for t in trades: vals.setdefault(str(t[key]),[]).append(t)
    return {k:_stats(v) for k,v in sorted(vals.items())}


def run(output:Path)->dict[str,Any]:
    baseline=_eval(BASE); bm=_m(baseline); actual=_actual_trades(); actual_stats=_stats(actual)
    if actual_stats["trades"]!=bm["trades"] or abs((actual_stats["net_pnl_bps"] or 0)-(bm["net_pnl_bps"] or 0))>1e-6:
        raise RuntimeError("ATTRIBUTION_PATH_MISMATCH")

    # Previously predeclared repair; retained only as a sealed failed control.
    repaired=_variant("repair_regime_owned_large_move_reversion_v1","(ret(1) < -0.02 and close > sma('close',50)) or (ret(1) > 0.02 and close < sma('close',50))","long if ret(1) < -0.02 else short")
    repair=_eval(repaired); rm=_m(repair)

    losses=sorted([t for t in actual if t["net_bps"]<0],key=lambda x:x["net_bps"])
    total_loss=-sum(t["net_bps"] for t in losses); top10_loss=-sum(t["net_bps"] for t in losses[:10])
    attribution={
      "actual_path_verified":True,"actual_trade_count":len(actual),"actual_metrics":actual_stats,
      "by_side":_group(actual,"side"),"by_symbol":_group(actual,"symbol"),"by_year":_group(actual,"signal_year"),"by_regime50":_group(actual,"signal_regime50"),
      "loss_concentration":{"loss_trade_count":len(losses),"total_loss_bps":total_loss,"top10_loss_bps":top10_loss,"top10_share_of_loss":top10_loss/total_loss if total_loss else 0.0,"worst10":[{k:t[k] for k in ("symbol","side","net_bps","signal_ret1","signal_regime50","signal_year","entry_ts","exit_ts")} for t in losses[:10]]}
    }
    result={
      "schema_version":"zel.a1_gen2_pass_robustness_audit.v2","development_only":True,"candidate_id":BASE["candidate_id"],
      "mechanism_integrity":{"claimed_basis_funding_mechanism":False,"actual_executable_mechanism":"1D large-move mean reversion after abs(ret1)>2%, next-open entry, 12D time stop","reason":"executed source/formula uses OHLCV only; no basis/funding/OI","relabel":"large_move_mean_reversion"},
      "baseline":baseline,"actual_path_attribution":attribution,
      "sealed_failed_repair":{"axis":"regime_ownership_only","evidence_ids":["F2","F16"],"old_metrics":bm,"new_metrics":rm,"delta":{"net_expectancy_bps":(rm.get("net_expectancy_bps") or 0)-(bm.get("net_expectancy_bps") or 0),"net_pnl_bps":(rm.get("net_pnl_bps") or 0)-(bm.get("net_pnl_bps") or 0),"profit_factor":(rm.get("profit_factor") or 0)-(bm.get("profit_factor") or 0),"drawdown_bps":(rm.get("drawdown_bps") or 0)-(bm.get("drawdown_bps") or 0),"trades":(rm.get("trades") or 0)-(bm.get("trades") or 0)},"accepted":False,"state":"SEALED_FAIL_NO_REUSE"},
      "next_repair_authority":"NONE_UNTIL_ATTRIBUTION_REVIEW","selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0
    }
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"baseline":bm,"by_side":attribution["by_side"],"by_symbol":attribution["by_symbol"],"by_regime50":attribution["by_regime50"],"loss_concentration":attribution["loss_concentration"]},sort_keys=True))
    return result

if __name__=="__main__": run(Path("out/a1_gen2_pass_robustness_audit_v1.json"))
