#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 as econ

BASE = {
  "candidate_id":"new_architecture_basis_premium_collector",
  "strategy_id":"NEW",
  "provider":"openai",
  "required_sources":["ohlcv","volume"],
  "executable_spec":{
    "bar_interval":"1d",
    "features":[{"name":"ret_sma_7","formula":"sma(ret(1),7)"}],
    "entry_rule":"ret(1) < -0.02 or ret(1) > 0.02",
    "side_rule":"long if ret(1) < -0.02 else short",
    "exit_rule":"time_stop",
    "max_hold_bars":12,
    "entry_timing":"next_bar_open",
    "cost_model":"verified_14bps_or_more",
    "development_data_rule":"strictly_before_GEN1_boundary",
    "parameter_provenance":"design_prior_or_primary_evidence_only"
  }
}


def _eval(c:dict[str,Any], symbols:tuple[str,...]|None=None)->dict[str,Any]:
    old=econ.SYMBOLS
    try:
        if symbols is not None: econ.SYMBOLS=symbols
        return econ.evaluate_candidate(c)
    finally:
        econ.SYMBOLS=old


def _m(row:dict[str,Any])->dict[str,Any]:
    x=row.get("metrics") or {}
    return {k:x.get(k) for k in ("trades","gross_expectancy_bps","net_expectancy_bps","net_pnl_bps","profit_factor","payoff","win_rate","drawdown_bps","events_per_day","net_bps_per_calendar_day","cost_bps_per_trade")}


def _variant(cid:str,entry:str,side:str)->dict[str,Any]:
    c=deepcopy(BASE); c["candidate_id"]=cid; c["executable_spec"]["entry_rule"]=entry; c["executable_spec"]["side_rule"]=side; return c


def run(output:Path)->dict[str,Any]:
    baseline=_eval(BASE)
    long_slice=_eval(_variant("slice_downshock_long","ret(1) < -0.02","long"))
    short_slice=_eval(_variant("slice_upshock_short","ret(1) > 0.02","short"))
    btc=_eval(BASE,("BTC-USDT",))
    eth=_eval(BASE,("ETH-USDT",))

    # One predeclared causal axis only: regime ownership. Keep 2% shock and 12-day hold unchanged.
    repaired=_variant(
      "repair_regime_owned_large_move_reversion_v1",
      "(ret(1) < -0.02 and close > sma('close',50)) or (ret(1) > 0.02 and close < sma('close',50))",
      "long if ret(1) < -0.02 else short"
    )
    repaired["evidence_ids"]=["F2","F16"]
    repaired["changed_axis"]="regime_ownership_only"
    repair=_eval(repaired)

    bm=_m(baseline); rm=_m(repair)
    result={
      "schema_version":"zel.a1_gen2_pass_robustness_audit.v1",
      "development_only":True,
      "candidate_id":BASE["candidate_id"],
      "mechanism_integrity":{
        "claimed_basis_funding_mechanism":False,
        "actual_executable_mechanism":"1D large-move mean reversion after abs(ret1)>2%, next-open entry, 12D time stop",
        "reason":"required_sources and formulas contain only OHLCV/volume; no basis/funding/OI feature is executed",
        "relabel":"large_move_mean_reversion"
      },
      "baseline":baseline,
      "decomposition":{"downshock_long":long_slice,"upshock_short":short_slice,"BTC_USDT":btc,"ETH_USDT":eth},
      "single_axis_repair":{
        "axis":"regime_ownership_only",
        "evidence_ids":["F2","F16"],
        "threshold_changed":False,
        "holding_horizon_changed":False,
        "repair":repair,
        "old_metrics":bm,
        "new_metrics":rm,
        "delta":{
          "net_expectancy_bps":(rm.get("net_expectancy_bps") or 0)-(bm.get("net_expectancy_bps") or 0),
          "net_pnl_bps":(rm.get("net_pnl_bps") or 0)-(bm.get("net_pnl_bps") or 0),
          "profit_factor":(rm.get("profit_factor") or 0)-(bm.get("profit_factor") or 0),
          "drawdown_bps":(rm.get("drawdown_bps") or 0)-(bm.get("drawdown_bps") or 0),
          "trades":(rm.get("trades") or 0)-(bm.get("trades") or 0)
        },
        "accept_for_further_prep":bool(repair.get("economic_pass") and (rm.get("net_expectancy_bps") or 0)>0 and (rm.get("profit_factor") or 0)>1 and (rm.get("drawdown_bps") or 1e99)<(bm.get("drawdown_bps") or 0))
      },
      "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0
    }
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"baseline":bm,"sides":{"long":_m(long_slice),"short":_m(short_slice)},"symbols":{"BTC":_m(btc),"ETH":_m(eth)},"repair":rm,"accept":result["single_axis_repair"]["accept_for_further_prep"]},sort_keys=True))
    return result

if __name__=="__main__":
    run(Path("out/a1_gen2_pass_robustness_audit_v1.json"))
