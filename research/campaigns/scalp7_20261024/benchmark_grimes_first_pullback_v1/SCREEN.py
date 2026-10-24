#!/usr/bin/env python3
"""One source-first GRIMES pullback numerical interpretation, fixed BEFORE results.

First confirmed channel thrust -> first EMA20 pullback -> next-close recovery.
This is a ZEL implementation of qualitative Adam Grimes price patterns, NOT
the author claiming to publish these exact thresholds. One cheap modeled 1h
developer test (all original received_at/funding unavailable), no live/Shadow.
Frozen: 6b3a90406f5a8510c57df27f9f0776f15905ce57
"""
from __future__ import annotations
import argparse,importlib.util,json,math,hashlib
from pathlib import Path
from datetime import datetime,timezone

FREEZE="6b3a90406f5a8510c57df27f9f0776f15905ce57"
PARENT="immediate_channel_thrust_ema_trend_next_hour_v1"
CHILD="grimes_first_channel_thrust_ema20_pullback_reclaim_1h_long_cash_v1"
COMMON_SHA="0358fd4b9e370d1c882d4dbdd9c610a7c06aca9968af6cec99866484eb7953ba"
HOUR=3600000
MAX_PULLBACK_DELAY=8
MAX_RECLAIM_DELAY=8
ENTRY_CHANNEL=20
EMA_FAST=20
EMA_SLOW=50
MAX_HOLD_HOURS=24

def sha(x:bytes):return hashlib.sha256(x).hexdigest()
def load_common(path:Path):
 b=path.read_bytes()
 if sha(b)!=COMMON_SHA:raise ValueError("FROZEN_SOURCE_READER_CHANGED")
 spec=importlib.util.spec_from_file_location("d_market_archive_reader",str(path))
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 return module

def ema(prices,n):
 a=2/(n+1)
 o=[prices[0]]
 for p in prices[1:]:o.append(a*p+(1-a)*o[-1])
 return o

def thrust(bars,ma_fast,ma_slow,t):
 if t<ENTRY_CHANNEL:return False
 if not (ma_fast[t]>ma_slow[t] and ma_fast[t]>ma_fast[t-1]):return False
 return bars[t]["close"]>max(bars[j]["high"] for j in range(t-ENTRY_CHANNEL,t))

def qualifies_pullback(bars,ma_fast,ma_slow,t):
 return ma_fast[t]>ma_slow[t] and bars[t]["low"]<=ma_fast[t] and bars[t]["close"]>ma_slow[t]

def resume(bars,ma_fast,ma_slow,t):
 if t<1:return False
 return (ma_fast[t]>ma_slow[t] and ma_fast[t]>ma_fast[t-1]
     and bars[t]["close"]>ma_fast[t] and bars[t]["close"]>bars[t-1]["high"])

def scan(bars,which,begin,end):
 prices=[x["close"] for x in bars]
 fast=ema(prices,EMA_FAST)
 slow=ema(prices,EMA_SLOW)
 occupied=None;phase="FLAT";thrust_i=pullback_i=None
 trades=[];censored=[];impulses=touches=triggers=0
 for i in range(240,len(bars)-1):
  bar=bars[i];btime=bar["ts"]+HOUR
  if btime<begin or btime>=end:continue
  nxt=bars[i+1]
  if occupied is not None:
   signal_exit=(bar["close"]<fast[i] or btime-occupied["entry_ts"]>=MAX_HOLD_HOURS*HOUR)
   if signal_exit:
    if nxt["ts"]>=end:
     censored.append({"entry_ts":occupied["entry_ts"],"reason":"EXIT_NEXT_OPEN_BEYOND_PARTITION"})
     occupied=None
     break
    gross=(nxt["open"]/occupied["entry_px"]-1)*10000
    trades.append({"signal_ts":occupied["signal_ts"],"entry_ts":occupied["entry_ts"],
      "exit_ts":nxt["ts"],"gross_bps":gross,
      "net_1x_bps":gross-20,"net_2x_bps":gross-40,
      "entry_px":occupied["entry_px"],"exit_px":nxt["open"],
      "exit_reason":"EMA20_CLOSE_BREAK_OR_24H_TIME"})
    occupied=None;phase="FLAT";thrust_i=pullback_i=None
   continue
  if which=="IMMEDIATE":
   if thrust(bars,fast,slow,i):
    impulses+=1
    if nxt["ts"]>=end:
     censored.append({"signal_ts":bar["ts"],"reason":"ENTRY_NEXT_OPEN_BEYOND_PARTITION"})
     continue
    triggers+=1
    occupied={"signal_ts":bar["ts"],"entry_ts":nxt["ts"],"entry_px":nxt["open"]}
   continue
  # FSM: only original completed OHLC, no reaction to next-open/outcome info.
  if phase=="FLAT":
   if thrust(bars,fast,slow,i):
    impulses+=1;phase="WAIT_PULLBACK";thrust_i=i
   continue
  if phase=="WAIT_PULLBACK":
   if i-thrust_i>MAX_PULLBACK_DELAY or fast[i]<=slow[i]:
    phase="FLAT";thrust_i=None
    continue
   if qualifies_pullback(bars,fast,slow,i):
    touches+=1;pullback_i=i;phase="WAIT_RECLAIM"
   continue
  if phase=="WAIT_RECLAIM":
   if i-pullback_i>MAX_RECLAIM_DELAY or fast[i]<=slow[i] or bar["close"]<slow[i]:
    phase="FLAT";thrust_i=pullback_i=None
    continue
   if resume(bars,fast,slow,i):
    if nxt["ts"]>=end:
     censored.append({"signal_ts":bar["ts"],"reason":"ENTRY_NEXT_OPEN_BEYOND_PARTITION"})
     break
    triggers+=1
    occupied={"signal_ts":bar["ts"],"entry_ts":nxt["ts"],"entry_px":nxt["open"]}
    phase="OPEN"
   continue
  raise RuntimeError("BROKEN_IMPULSE_STATE")
 if occupied is not None:
  valid=[x for x in bars if x["ts"]<end]
  if valid:
   last=valid[-1]
   censored.append({"entry_ts":occupied["entry_ts"],
      "last_complete_close_ts":last["ts"]+HOUR,
      "gross_mtm_bps":(last["close"]/occupied["entry_px"]-1)*10000,
      "reason":"OPEN_POSITION_CENSORED_NO_MODELLED_FAVORABLE_EXIT"})
 return trades,censored,dict(thrusts=impulses,pullbacks=touches,entries=triggers)

def report(source,prov,manifest,common):
 periods={"train":(common.ms(common.TRAIN_START),common.ms(common.SPLIT)),
          "validation":(common.ms(common.SPLIT),common.ms(common.END))}
 outputs={}
 for partition,(a,b) in periods.items():
  results={}
  for identity,mode in [(PARENT,"IMMEDIATE"),(CHILD,"FIRST_PULLBACK")]:
   all_rows=[];cens=[];per={}
   for sym,bars in source.items():
    trades,unfinished,events=scan(bars,mode,a,b)
    for x in trades:x["symbol"]=sym
    for x in unfinished:x["symbol"]=sym
    all_rows.extend(trades);cens.extend(unfinished)
    per[sym]={"T":len(trades),"censored":len(unfinished),"Net2":sum(x["net_2x_bps"] for x in trades),**events}
   results[identity]={
     "cost1x":common.metric(all_rows,"net_1x_bps"),
     "cost2x":common.metric(all_rows,"net_2x_bps"),
     "per_symbol":per,"unfinished_positions":len(cens),
     "censored_rows":cens,
     "opportunities_per_calendar_day":len(all_rows)/((b-a)/common.DAY),
     "source_trade_rows":all_rows,
     "correlated_peak_positions_diagnostic":common.overlap(all_rows),
   }
  outputs[partition]={"period":{"from":common.ts(a),"until_exclusive":common.ts(b)},
    **results,
    "delta_new_pullback_minus_immediate_cost2_trade_bps":
      results[CHILD]["cost2x"]["net_sum_trade_bps"]-
      results[PARENT]["cost2x"]["net_sum_trade_bps"]}
 return {
 "schema":"zel.source_first.adam_grimes_first_pullback.dev.v1",
 "freeze_commit":FREEZE,
 "original_source":["https://www.adamhgrimes.com/pullback-trade-works/",
                    "https://adamhgrimes.com/context-in-pullbacks-what-should-happen/",
                    "https://adamhgrimes.com/trading-pullbacks/"],
 "exact_numerical_rule_authorship":"ZEL_DECLARED_INTERPRETATION_OF_GRIMES_CONCEPT",
 "history_role":"REUSED_HISTORICAL_DEVELOPMENT_NOT_INDEPENDENT_UNUSED_OOS",
 "market_time_1h_true_received_at_evidence":False,
 "archive_manifest_sha256":manifest,
 "source_input_shas":prov,
 "trade_fees_slippage_funding_real":None,
 "modeled_one_roundtrip_cost_1x_2x_bps":[20,40],
 "claims_production_or_G5_pass":False,
 "universe_intersection":list(source),
 "checks":{"frozen_source":True,"no_forward_source_requests":True,"cost2x_present":True},
 "economic_heavy_runs":0,"orders":0,"market_requests":0,"results":outputs
 }

def tests():
 bars=[{"ts":i*HOUR,"open":10,"high":11,"low":9,"close":10} for i in range(30)]
 f=[10.5]*30;s=[9.0]*30;f[20]=10.6
 assert not thrust(bars,f,s,20)
 bars[20]["close"]=12
 assert thrust(bars,f,s,20) is True
 assert qualifies_pullback(bars,f,s,21)
 assert not resume(bars,f,s,21)
 bars[21]["close"]=10.7;bars[22]["close"]=12.0;bars[22]["high"]=12.5
 f[22]=10.7
 assert resume(bars,f,s,22) is True
 assert ema([10.,10.,10.],20)==[10.,10.,10.]
 assert ENTRY_CHANNEL==20 and MAX_PULLBACK_DELAY==8
 assert CHILD!=PARENT
 assert len(bars)==30
 assert MAX_HOLD_HOURS==24
 print(json.dumps({"tests":10,"status":"PASS","orders":0,"market_requests":0}))

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--common",type=Path)
 p.add_argument("--archive",type=Path)
 p.add_argument("--out",type=Path)
 p.add_argument("--self-test",action="store_true")
 a=p.parse_args()
 if a.self_test:tests();return
 if not a.common or not a.archive or not a.out:p.error("common archive out required")
 if a.out.exists():p.error("output exists, immutable")
 common=load_common(a.common)
 source,prov,msha=common.read_data(a.archive)
 r=report(source,prov,msha,common)
 b=(json.dumps(r,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
 with a.out.open("xb") as f:f.write(b)
 print(json.dumps({"status":"RESULT_WRITTEN","sha256":sha(b),
   "train_T":r["results"]["train"][CHILD]["cost2x"]["T"],
   "train_net2":r["results"]["train"][CHILD]["cost2x"]["net_sum_trade_bps"],
   "validation_T":r["results"]["validation"][CHILD]["cost2x"]["T"],
   "validation_net2":r["results"]["validation"][CHILD]["cost2x"]["net_sum_trade_bps"]}))

if __name__=="__main__":main()
