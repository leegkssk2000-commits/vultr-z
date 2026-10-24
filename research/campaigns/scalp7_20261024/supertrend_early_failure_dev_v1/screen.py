#!/usr/bin/env python3
"""FROZEN Supertrend H12 two-close loss-failure: MODELLED old 4/7 only.

Pre-registered separately at GitHub commit 2ded1247762e7dd6d3e91bc6df5cb0558f44e3fe
BEFORE reading metrics on this distinct 2026-02-14..2026-08-30 archive.
Historical actual receipt / order fill / funding NOT available. No native 7/7,
no formal G4/G5/OOS/paper/live/order authority. True signal/features from
the frozen original source; fixed 20/40bps roundtrip model only.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,sys
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict

ROOT_SOURCE="/home/z/z/runtime/economic7_campaign_20260915/canonical_postgap_20260213"
SHA_NATIVE={
"backend/research/contracts/a1_top5_replacement_child_freeze_v2.json":"686a8839bf9de0ef0baf719511910c10982656a20d723c2f997b58cc618576ce",
"backend/research/rebuild/a1_top5_replacement_child_prospective_v1.py":"d509b69cc80c773d4678613b21259e5d25b1a21407bb41e02bd7077e39bd96d3",
"backend/research/architecture_factory/a1_gen2_generic_dev_econ_v1.py":"d86a61ed25f8d6f74a8c56e834db13a6ba61daa370731a590bbbab514f5ae736"}
ID="supertrend_replacement_highvol_mom_long_4h_h12_v2"
CHILD="supertrend_h12_causal_two_close_failure_v1"
ENTRY="abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50"
UNIVERSE=("BTC-USDT","ETH-USDT","SOL-USDT","LINK-USDT")
HOUR=3600000;DAY=86400000;TF=4*HOUR
START=1771027200000 # Feb 14
DEV=1774483200000 # March 26
SPLIT=1781481600000 # June 15
END=1788048000000 # Aug 30
RULE_COMMIT="2ded1247762e7dd6d3e91bc6df5cb0558f44e3fe"

def sha(bs):return hashlib.sha256(bs).hexdigest()
def iso(ts):return datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()

def pinned_native(root:Path):
 for rel,expected in SHA_NATIVE.items():
  f=root/rel
  if not f.is_file() or sha(f.read_bytes())!=expected:
   raise ValueError("FROZEN_NATIVE_SHA_DRIFT:"+rel)
 sys.path.insert(0,str(root))
 from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as native
 spec=json.loads((root/"backend/research/contracts/a1_top5_replacement_child_freeze_v2.json").read_text())
 row=next(x for x in spec["children"] if x["child_id"]==ID)["executable_spec"]
 if (row["entry_rule"]!=ENTRY or row["bar_interval"]!="4h" or row["entry_timing"]!="next_bar_open" or
     row["max_hold_bars"]!=12 or row["exit_rule"]!="time_stop" or
     row["side_rule"]!="long" or row["cost_bps_per_trade"]!=20):
  raise ValueError("FROZEN_PARENT_CONTRACT_MISMATCH")
 return native,row

def source_data(root:Path):
 manifest_raw=(root/"MANIFEST.json").read_bytes()
 manifest=json.loads(manifest_raw)
 if(manifest.get("state")!="DATA_VALID_VOLUME_AUTHORITY_UNKNOWN" or
    manifest.get("data_integrity_complete") is not True or
    manifest.get("synthetic_fill") is not False or
    manifest.get("volume_unit")!="UNKNOWN"):
  raise ValueError("SOURCE_CLASS_CHANGED")
 if manifest["start_ms"]>START or manifest["end_exclusive_ms"]<END:
  raise ValueError("SOURCE_WINDOW_NOT_COVERED")
 a={}
 receipts={}
 for sym in UNIVERSE:
  prev=START;hdata=[];used=[]
  folder=root/"60m"/sym
  for f in sorted(folder.glob("*.csv.gz")):
   st,ed=map(int,f.name.removesuffix(".csv.gz").split("_"))
   if ed<=START or st>=END:continue
   if st!=prev or ed!=st+DAY:raise ValueError("INCOMPLETE_OR_NONUTC_DAY:"+sym)
   used.append((f.name,sha(f.read_bytes())))
   with gzip.open(f,"rt") as gz:
    dr=csv.DictReader(gz)
    if dr.fieldnames!=["timestamp_ms","open","high","low","close","volume"]:raise ValueError("HOUR_HEADER")
    entries=list(dr)
   if len(entries)!=24:raise ValueError("HOUR_DAY_SHORT")
   for k,r in enumerate(entries):
    ts=int(r["timestamp_ms"])
    if ts!=st+k*HOUR:raise ValueError("HOUR_TIME_GRID")
    vals=[float(r[z]) for z in ("open","high","low","close")]
    op,hi,lo,cl=vals
    if any(not math.isfinite(z) or z<=0 for z in vals) or lo>min(op,cl) or hi<max(op,cl):
     raise ValueError("BAD_HOURLY_OHLC")
    hdata.append({"ts":ts,"open":op,"high":hi,"low":lo,"close":cl})
   prev=ed
  if prev!=END or len(hdata)!=((END-START)//HOUR):raise ValueError("NOT_CLOSED_WINDOW:"+sym)
  bars=[]
  for i in range(0,len(hdata),4):
   chunk=hdata[i:i+4]
   if len(chunk)!=4 or any(x["ts"]!=chunk[0]["ts"]+q*HOUR for q,x in enumerate(chunk)):
    raise ValueError("UNVERIFIED_4H")
   bars.append({"ts":chunk[0]["ts"],"open":chunk[0]["open"],
     "high":max(x["high"] for x in chunk),"low":min(x["low"] for x in chunk),
     "close":chunk[-1]["close"],"volume":0.0})
  if len(bars)!=(END-START)//TF:raise ValueError("MISSING_4H")
  a[sym]=bars
  receipts[sym]={"hour_bars":len(hdata),"four_hour_bars":len(bars),
   "verified_daily_chunks":len(used),"daily_blob_shas_sha256":sha(json.dumps(used,sort_keys=True).encode())}
 return a,receipts,sha(manifest_raw)

def failure(bars,features,enter:int,j:int,entrypx:float)->bool:
 """Only two consecutive FULLY completed adverse H4 bar closes and native EMA20."""
 if j<enter+1:return False
 prev,now=bars[j-1]["close"],bars[j]["close"]
 ema_before,ema_now=features["ema20"][j-1],features["ema20"][j]
 return (ema_before is not None and ema_now is not None and
         prev<entrypx and now<entrypx and prev<ema_before and
         now<ema_now and now<prev)

def replay(bars,native,spec,kind):
 features,eng=native._features(bars,spec)
 eng.validate(ENTRY)
 i=240;out=[];censored=[];eligible=0
 while i<len(bars)-1:
  ts=bars[i]["ts"]
  if ts<DEV:
   i+=1;continue
  if ts>=END:break
  if not bool(eng.eval(ENTRY,i)):
   i+=1;continue
  eligible+=1
  entry=i+1;due=entry+11
  if due>=len(bars) or bars[due]["ts"]+TF>END:
   censored.append({"signal_ts":ts,"entry_ts":bars[entry]["ts"],"cause":"H12_EXCEEDS_ARCHIVE_END"})
   break
  price=bars[entry]["open"]
  exit_i=due
  ex_price=bars[due]["close"]
  ex_time=bars[due]["ts"]+TF
  reason="FROZEN_PARENT_H12_CLOSE_MODEL"
  if kind!="parent":
   for j in range(entry+1,due):
    if failure(bars,features,entry,j,price):
     x=j+(2 if kind=="latency_stress" else 1)
     if x>due:break
     exit_i=x
     ex_price=bars[x]["open"]
     ex_time=bars[x]["ts"]
     reason="TWO_CAUSAL_CLOSES_NEXT_OPEN_MODEL"+("_1FULLBAR_DELAY" if kind=="latency_stress" else "")
     break
  gross=(ex_price/price-1)*10000
  out.append({"signal_ts":ts,"entry_ts":bars[entry]["ts"],"exit_ts":ex_time,
     "entry_px":price,"exit_px":ex_price,"gross_bps":gross,
     "net1_bps":gross-20,"net2_bps":gross-40,"exit_reason":reason})
  i=exit_i+1
 return out,censored,eligible

def summary(trades,key):
 rows=sorted(trades,key=lambda x:(x["exit_ts"],x["symbol"],x["signal_ts"]))
 numbers=[r[key] for r in rows]
 win=[x for x in numbers if x>0];lose=[x for x in numbers if x<0]
 eq=peak=dd=0.0;loss=bestloss=runwin=bestwin=0
 for x in numbers:
  eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
  if x<0:loss+=1;runwin=0
  elif x>0:runwin+=1;loss=0
  else:loss=runwin=0
  bestloss=max(bestloss,loss);bestwin=max(bestwin,runwin)
 return {"T":len(numbers),"win_count":len(win),"WR":len(win)/len(numbers) if numbers else None,
   "gross_sum_bps":sum(r["gross_bps"] for r in rows),
   "net_sum_trade_bps":sum(numbers),
   "net_per_T_bps":sum(numbers)/len(numbers) if numbers else None,
   "PF":sum(win)/-sum(lose) if lose else None,
   "realized_trade_bps_max_DD":dd,
   "max_loss_streak":bestloss,"max_win_streak":bestwin}

def group(rows):
 bytime=defaultdict(list)
 for r in rows:bytime[r["exit_ts"]].append(r["net2_bps"])
 return {"exit_cohorts":len(bytime),
    "min_same_close_group_sum_trade_bps":min([sum(v) for v in bytime.values()],default=None),
    "multi_symbol_exit_groups":sum(len(v)>1 for v in bytime.values())}

def economic(streams,native,spec):
 output={}
 for sym,bars in streams.items():
  outcomes={}
  for kind in ("parent","child","latency_stress"):
   trades,cens,signals=replay(bars,native,spec,kind)
   for r in trades:r["symbol"]=sym
   outcomes[kind]={"trades":trades,"censored":cens,"signals":signals}
  output[sym]=outcomes
 def allrows(k):
  return [r for sym in UNIVERSE for r in output[sym][k]["trades"]]
 def window(rows,a,b):
  return [r for r in rows if a<=r["signal_ts"]<b]
 summary_result={}
 for label,a,b in (("development",DEV,SPLIT),("validation",SPLIT,END)):
  parent=window(allrows("parent"),a,b)
  child=window(allrows("child"),a,b)
  late=window(allrows("latency_stress"),a,b)
  pp={(r["symbol"],r["signal_ts"]):r for r in parent}
  cp={(r["symbol"],r["signal_ts"]):r for r in child}
  top2=sorted(parent,key=lambda r:r["net2_bps"],reverse=True)[:2]
  initial_positive={key for key,r in pp.items() if r["net2_bps"]>0}
  retained={key for key in initial_positive&set(cp) if cp[key]["net2_bps"]>0}
  eligible_by_symbol={sym:len([r for r in output[sym]["parent"]["trades"] if a<=r["signal_ts"]<b]) for sym in UNIVERSE}
  summary_result[label]={
   "period":{"start":iso(a),"end_exclusive":iso(b)},
   "parent":{"cost1x":summary(parent,"net1_bps"),"cost2x":summary(parent,"net2_bps"),"cohort":group(parent)},
   "child":{"cost1x":summary(child,"net1_bps"),"cost2x":summary(child,"net2_bps"),"cohort":group(child)},
   "latency_stress":{"cost2x":summary(late,"net2_bps")},
   "delta_child_minus_parent_2x_trade_bps":sum(r["net2_bps"] for r in child)-sum(r["net2_bps"] for r in parent),
   "parent_2x_positive":len(initial_positive),
   "still_positive_same_signal":len(retained),
   "parent_2x_winner_profit_retention_ratio":sum(cp[k]["net2_bps"] for k in retained)/sum(pp[k]["net2_bps"] for k in initial_positive) if initial_positive else None,
   "lost_positive_due_to_occupancy":len(initial_positive-set(cp)),
   "converted_positive_to_loss":len(initial_positive&set(cp))-len(retained),
   "parent_top2_diagnostic":[{"symbol":x["symbol"],"signal_ts":x["signal_ts"],
       "parent_net2_bps":x["net2_bps"],
       "child_net2_bps":cp.get((x["symbol"],x["signal_ts"]),{}).get("net2_bps")} for x in top2],
   "parent_missing_in_child":len(set(pp)-set(cp)),
   "child_new_opportunity":len(set(cp)-set(pp)),
   "child_failure_early_exits":sum(r["exit_reason"].startswith("TWO_") for r in child),
   "per_symbol_parent_T":eligible_by_symbol,
   "original_7symbol_population_complete":False,
   "censored_child":sum(len([r for r in output[sym]["child"]["censored"] if a<=r["signal_ts"]<b]) for sym in UNIVERSE)
  }
 return summary_result

def test():
 fake=[{"close":100},{"close":98},{"close":96}]
 f={"ema20":[101,100,99]}
 assert failure(fake,f,1,2,100) is True
 assert failure(fake,f,1,1,100) is False
 assert failure(fake,{"ema20":[90,90,90]},1,2,100) is False
 assert failure([{"close":100},{"close":95},{"close":97}],f,1,2,100) is False
 assert failure([{"close":100},{"close":100},{"close":96}],f,1,2,100) is False
 assert summary([{"exit_ts":1,"symbol":"A","signal_ts":1,"gross_bps":100,"net2_bps":60}],"net2_bps")["T"]==1
 assert summary([{"exit_ts":1,"symbol":"A","signal_ts":1,"gross_bps":0,"net2_bps":-40}],"net2_bps")["PF"]==0
 assert group([])["exit_cohorts"]==0
 assert END>SPLIT>DEV>START
 assert CHILD!=ID and RULE_COMMIT.startswith("2ded")
 print(json.dumps({"checks":10,"result":"PASS","orders":0,"market_gets":0}))

def main():
 pa=argparse.ArgumentParser()
 pa.add_argument("--root",type=Path)
 pa.add_argument("--archive",type=Path)
 pa.add_argument("--result",type=Path)
 pa.add_argument("--self-test",action="store_true")
 args=pa.parse_args()
 if args.self_test:test();return
 if not args.root or not args.archive or not args.result:pa.error("Three required paths")
 if args.result.exists():pa.error("existing output not overwritten")
 native,spec=pinned_native(args.root)
 streams,prov,m_sha=source_data(args.archive)
 res={"schema":"zel.supertrend.causal_two_close_failure.modelled_dev.v1",
    "rule_frozen_before_run_git_commit":RULE_COMMIT,"source_state":"DEVELOPMENT_PREBOUNDARY_HISTORICAL_NOT_G5_OOS",
    "data_window":{"start":iso(START),"end_exclusive":iso(END),"split":iso(SPLIT),"warmup_240bars":True},
    "source_manifest_sha256":m_sha,"input_file_hash_chain_per_symbol":prov,
    "code_dependencies_sha256":SHA_NATIVE,
    "matched_symbols":list(UNIVERSE),"source_7of7":False,
    "historical_actual_received_time":False,"market_fill_witness":False,
    "real_fee_funding_slippage":False,"costs_modeled_roundtrip_bps":[20,40],
    "real_account_NAV":None,"G4_G5_fresh_authority":False,
    "economic_runs":0,"orders":0,"network_calls":0,
    "results":economic(streams,native,spec)}
 raw=(json.dumps(res,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n").encode()
 with args.result.open("xb") as f:f.write(raw)
 print(json.dumps({"state":"MODELLED_DEV_ONLY", "result_sha256":sha(raw),
 "dev_parent":res["results"]["development"]["parent"]["cost2x"]["net_sum_trade_bps"],
 "dev_child":res["results"]["development"]["child"]["cost2x"]["net_sum_trade_bps"],
 "valid_parent":res["results"]["validation"]["parent"]["cost2x"]["net_sum_trade_bps"],
 "valid_child":res["results"]["validation"]["child"]["cost2x"]["net_sum_trade_bps"]}))
if __name__=="__main__":main()
