#!/usr/bin/env python3
"""Close the already-completed 2026-10-24 KAMA/Grimes SOURCE_FIRST Work D.

Read-only audit of EXACT SHA-pinned original historic closed trade ledgers.
No strategy changes, no price API, no model tuning, no fresh OOS/G5 credit.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import argparse,hashlib,json,math

SOURCE={
    "KAMA":{
        "file":"/home/z/d_source_first_kama_1h_v1_result_20261024.json",
        "sha256":"0f7c89c82ba0ff43aab4655129539c68b2ec17fa588be3d585a6953484cf34b3"},
    "GRIMES":{
        "file":"/home/z/d_source_first_grimes_pullback_1h_v1_result_20261024.json",
        "sha256":"0e44b205b6a15baefe0bb4087fd79d8eec39959175bece3a98867c20100a469a"},
}
KAMA="KAMA"
GRIMES="grimes_first_channel_thrust_ema20_pullback_reclaim_1h_long_cash_v1"
BASE=20
STRESS=40

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def load(name):
    s=SOURCE[name]
    raw=Path(s["file"]).read_bytes()
    if sha(raw)!=s["sha256"]:raise ValueError("CHANGED_FROZEN_LEDGER:"+name)
    j=json.loads(raw)
    if j.get("orders",0)!=0 or j.get("market_requests",0)!=0:
        raise ValueError("TRADING_OR_EXTERNAL_MARKET_EFFECTS")
    return j

def windowdays(period):
    a=datetime.fromisoformat(period["from"].replace("Z","+00:00"))
    b=datetime.fromisoformat(period["until_exclusive"].replace("Z","+00:00"))
    days=(b-a).total_seconds()/86400
    if days<=0 or not days.is_integer():
        raise ValueError("BAD_PARTITION_LENGTH")
    return int(days)

def stats(rows,period):
    d=defaultdict(int)
    entry_hours=defaultdict(int)
    per_symbol=defaultdict(list)
    active=[]
    ids=set()
    for r in rows:
        symbol=r["symbol"];enter=r["entry_ts"];exit=r["exit_ts"]
        if not isinstance(enter,int) or not isinstance(exit,int) or enter>=exit:
            raise ValueError("BAD_ENTRY_EXIT_CHRONOLOGY")
        if enter%3_600_000 or exit%3_600_000:
            raise ValueError("NOT_MODELLED_HOURLY_FILL")
        idx=(symbol,enter)
        if idx in ids:raise ValueError("DUPLICATE_SYMBOL_ENTRY")
        ids.add(idx)
        if not all(math.isfinite(float(r[f])) for f in ("gross_bps","net_1x_bps","net_2x_bps")):
            raise ValueError("NONFINITE_RESULT")
        if abs((r["gross_bps"]-BASE)-r["net_1x_bps"])>1e-6:
            raise ValueError("COST1_PARITY")
        if abs((r["gross_bps"]-STRESS)-r["net_2x_bps"])>1e-6:
            raise ValueError("COST2_PARITY")
        d[enter//86_400_000]+=1
        entry_hours[enter]+=1
        per_symbol[symbol].append((enter,exit))
        active.extend(((enter,1),(exit,-1)))
    days=windowdays(period)
    if len(d)>days:raise ValueError("TOO_MANY_ENTRY_DAYS")
    active.sort(key=lambda x:(x[0],x[1])) # exit before entry at same t
    live=peak=0
    for _,delta in active:
        live+=delta
        if live<0:raise ValueError("UNBALANCED_POSITION_EVENTS")
        peak=max(peak,live)
    if live!=0:raise ValueError("UNBALANCED_LAST_CLOSE")
    for symbol, pairs in per_symbol.items():
        ordered=sorted(pairs)
        for a,b in zip(ordered,ordered[1:]):
            if a[1]>b[0]:raise ValueError("DUPLICATE_SAME_SYMBOL_EXPOSURE:"+symbol)
    net2=[r["net_2x_bps"] for r in rows]
    profit=sum(x for x in net2 if x>0)
    loss=-sum(x for x in net2 if x<0)
    return {
      "trades":len(rows),"gross_sum_trade_bps":sum(r["gross_bps"] for r in rows),
      "net1_sum_trade_bps":sum(r["net_1x_bps"] for r in rows),
      "net2_sum_trade_bps":sum(net2),
      "net2_per_T_trade_bps":sum(net2)/len(rows) if rows else None,
      "cost2_PF":profit/loss if loss else None,
      "calendar_days":days,"active_entry_days":len(d),"zero_entry_days":days-len(d),
      "nominal_trades_per_day":len(rows)/days,
      "distinct_hourly_entry_epochs":len(entry_hours),
      "entry_epochs_per_day":len(entry_hours)/days,
      "same_hour_other_symbol_entries":len(rows)-len(entry_hours),
      "multisymbol_entry_epochs":sum(k>1 for k in entry_hours.values()),
      "max_concurrent_positions_without_capital_model":peak,
      "top2_trade_winner_sum_net2_bps":sum(sorted(net2,reverse=True)[:2]),
      "original_cost_model_roundtrip_1x_bps":BASE,
      "original_cost_model_roundtrip_2x_bps":STRESS,
      "reason":"CORRELATED_ENTRIES_AND_FEES_MUST_NOT_BE_COUNTED_AS_INDEPENDENT_ACCOUNT_PROFIT",
    }

def audit():
    k,g=load("KAMA"),load("GRIMES")
    out={}
    for label in ("train","validation"):
        kp=k["calendar_partitions"][label]
        gp=g["results"][label]
        period={"from":kp["start_utc"],"until_exclusive":kp["end_exclusive_utc"]}
        if gp["period"]!=period:
            raise ValueError("SOURCE_TRADE_CALENDAR_MISMATCH")
        source_by_strat={
          "KAMA":kp["KAMA"]["closed_rows"],
          "KAMA_EMA_CONTROL":kp["EMA_COMPARATOR"]["closed_rows"],
          "GRIMES_FIRST_PULLBACK":gp[GRIMES]["source_trade_rows"],
          "GRIMES_IMMEDIATE_CONTROL":gp["immediate_channel_thrust_ema_trend_next_hour_v1"]["source_trade_rows"],
        }
        computed={}
        for name,rows in source_by_strat.items():
            r=stats(rows,period)
            original=(
                kp["KAMA"] if name=="KAMA" else
                kp["EMA_COMPARATOR"] if name=="KAMA_EMA_CONTROL" else
                gp[GRIMES] if name=="GRIMES_FIRST_PULLBACK" else
                gp["immediate_channel_thrust_ema_trend_next_hour_v1"]
            )["cost2x"]
            if (r["trades"]!=original["T"] or
                abs(r["net2_sum_trade_bps"]-original["net_sum_trade_bps"])>1e-6 or
                abs(r["cost2_PF"]-original["PF"])>1e-6):
                raise ValueError("FULL_LEDGER_SUMMARY_MISMATCH:"+label+":"+name)
            computed[name]=r
        out[label]=computed
    verdicts={
      "KAMA":"REJECT: train gross and Net2 negative; validation modeled gross positive but 40bps roundtrip defeats it",
      "GRIMES_FIRST_PULLBACK":"REJECT: gross negative and Net2 negative in both historical windows",
      "GRIMES_IMMEDIATE_CONTROL":"NOT_SURVIVOR: earlier train model negative, later block positive; no unseen OOS or author-exact numeric strategy",
    }
    return {
      "schema":"zel.d.source_first.two_candidates.final_independent_closure_audit.v1",
      "primary_input_sha256":{k:v["sha256"] for k,v in SOURCE.items()},
      "completed_source_refs":{
         "KAMA":"86231ebb2bf68cf75e7e67fadb4b5381c5e690ea",
         "GRIMES":"01bd4717584c30409f5dabc4d76d3aa17b265341",
         "SOURCE_MATRIX":"bfd137feb68474a1a4d9abe26ae79254e975a7a4",
      },
      "result":"SOURCE_FULL_LEDGER_COST_PARITY_PASS_BOTH_RETIRED",
      "candidate_verdicts":verdicts,
      "periods":out,
      "limitations":[
        "Already consumed past price windows, NOT independent untouched OOS",
        "Modeled next-hour open and 20/40bp roundtrip costs, not signed trade fills/funding",
        "Simultaneous hours and different symbols are not automatically independent opportunities",
        "No notional leverage position sizing or actual account NAV/DD",
        "Direct reaggregation of separate legacy HolyGrail donor previously denied; this audit NEVER reads it",
      ],
      "next_gate":"Only verified new source-exact candidate with fresh eligible input and author rule; no KAMA/Grimes numeric retune",
      "A_economic_full_runs":0,"new_market_requests":0,"order_calls":0,
      "formal_G4_G5_pass":False,
    }

def selftest():
    base={"symbol":"BTC-USDT","entry_ts":0,"exit_ts":3_600_000,"gross_bps":60,"net_1x_bps":40,"net_2x_bps":20}
    t=stats([base],{"from":"2026-01-01T00:00:00Z","until_exclusive":"2026-01-03T00:00:00Z"})
    assert t["trades"]==1 and t["active_entry_days"]==1 and t["zero_entry_days"]==1
    assert t["max_concurrent_positions_without_capital_model"]==1
    x={**base,"symbol":"ETH-USDT"}
    t=stats([base,x],{"from":"2026-01-01T00:00:00Z","until_exclusive":"2026-01-03T00:00:00Z"})
    assert t["same_hour_other_symbol_entries"]==1 and t["distinct_hourly_entry_epochs"]==1
    assert t["max_concurrent_positions_without_capital_model"]==2
    for bad in ({**base,"net_2x_bps":0},{**base,"exit_ts":0}):
        try:stats([bad],{"from":"2026-01-01T00:00:00Z","until_exclusive":"2026-01-03T00:00:00Z"})
        except ValueError:pass
        else:raise AssertionError("BAD_ROW_ACCEPTED")
    assert len(SOURCE)==2 and GRIMES.endswith("long_cash_v1")
    print(json.dumps({"assertions":9,"status":"PASS","market_requests":0,"orders":0}))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--out",type=Path)
    args=ap.parse_args()
    if args.self_test:selftest();return
    if not args.out:ap.error("--out mandatory")
    if args.out.exists():raise ValueError("NO_OVERWRITE")
    result=audit()
    with args.out.open("xb") as f:
        f.write((json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode())
    print(json.dumps({"status":result["result"],"path":str(args.out),"sha256":sha(args.out.read_bytes()),
       "kama_validation":result["periods"]["validation"]["KAMA"]["net2_sum_trade_bps"],
       "grimes_validation":result["periods"]["validation"]["GRIMES_FIRST_PULLBACK"]["net2_sum_trade_bps"]}))
if __name__=="__main__":main()
