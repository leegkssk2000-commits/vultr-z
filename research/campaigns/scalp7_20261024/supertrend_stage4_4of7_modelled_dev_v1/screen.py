#!/usr/bin/env python3
"""One predeclared, historical MODELLED-BAR-CLOSE 4/7-symbol DEV screen.

Parent is frozen a1_top5 replacement-v2 4h H12 high-vol impulse long.
Only changed axis: its previously frozen Stage4 H12-post EMA continuation.
NO actual historical receipt/next-open fill authority, NO fresh/OOS credit.
NO reoptimisation, no data download, no alternative parameter sweeps.

Use only verified 151-day 60m original archive before 2026-02-13 gap.
Complete 4-hour bar features use original signed native EMA/ret/std code.
Child exit deliberately lagged by one 4h BAR after completed signal bar
to avoid same-boundary price certainty. Original H12 parent stays as frozen.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import sys

TF=14_400_000
HOUR=3_600_000
DAY=86_400_000
START=1757894400000
END=1770940800000
SYMS=("BTC-USDT","ETH-USDT","SOL-USDT","LINK-USDT") # exact intersection of original 7 and source 6
NATIVE_PINS={
 "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json":"686a8839bf9de0ef0baf719511910c10982656a20d723c2f997b58cc618576ce",
 "backend/research/rebuild/a1_top5_replacement_child_prospective_v1.py":"d509b69cc80c773d4678613b21259e5d25b1a21407bb41e02bd7077e39bd96d3",
 "backend/research/architecture_factory/a1_gen2_generic_dev_econ_v1.py":"d86a61ed25f8d6f74a8c56e834db13a6ba61daa370731a590bbbab514f5ae736",
}
EXPECTED_ENTRY="abs(ret1) >= 1.5 * retstd20 and ret1 > 0 and ema20 > ema50"
PARENT="supertrend_replacement_highvol_mom_long_4h_h12_v2"
CHILD="supertrend_momentum_h12_ema_persistence_intent_v1"
SOURCESTATE="HOLD_SOURCE_INTEGRITY" # 365d request; source first151d prefix is complete


def sha(b):return hashlib.sha256(b).hexdigest()
def dt(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
def native_lib(root):
 for rel,expected in NATIVE_PINS.items():
  path=root/rel
  if not path.is_file() or sha(path.read_bytes())!=expected:
   raise ValueError("FROZEN_NATIVE_SHA_MISMATCH:"+rel)
 sys.path.insert(0,str(root))
 from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as native
 c=json.loads((root/"backend/research/contracts/a1_top5_replacement_child_freeze_v2.json").read_text())
 child=next(x for x in c["children"] if x["child_id"]==PARENT)
 spec=child["executable_spec"]
 assert spec["entry_rule"]==EXPECTED_ENTRY and spec["max_hold_bars"]==12
 assert spec["exit_rule"]=="time_stop" and spec["entry_timing"]=="next_bar_open"
 assert spec["cost_bps_per_trade"]==20 and spec["side_rule"]=="long"
 assert c["frozen_symbol_universe"]==["1000PEPE-USDT","BCH-USDT","BTC-USDT","ETH-USDT","HYPE-USDT","LINK-USDT","SOL-USDT"]
 return native,spec


def archive(root:Path):
 manifest=json.loads((root/"MANIFEST.json").read_text())
 if manifest.get("state")!=SOURCESTATE or manifest.get("start_ms")!=START:
  raise ValueError("BAD_ARCHIVE_MANIFEST")
 assert set(SYMS).issubset(set(manifest["symbols"]))
 assert all(next(x for x in manifest["symbols_coverage"] if x["symbol"]==s)["rows_1m"]==217440 for s in SYMS)
 streams={}
 fingerprints={}
 for sym in SYMS:
  folder=root/"60m"/sym
  files=sorted(folder.glob("*.csv.gz"))
  if len(files)!=151:raise ValueError("MISSING_DAILY_CHUNKS:"+sym)
  prev=START
  hourly=[]
  inp=[]
  for f in files:
   a,b=map(int,f.name.removesuffix(".csv.gz").split("_"))
   if a!=prev or b!=a+DAY:raise ValueError("UTC_DAY_GAP:"+sym)
   raw=f.read_bytes();inp.append([f.name,sha(raw)])
   with gzip.open(f,"rt") as reader:
    parsed=csv.DictReader(reader)
    if parsed.fieldnames!=["timestamp_ms","open","high","low","close","volume"]:
     raise ValueError("NOT_ORIGINAL_60M_SCHEMA")
    rows=list(parsed)
   if len(rows)!=24:raise ValueError("INCOMPLETE_DAY:"+sym+":"+f.name)
   for k,r in enumerate(rows):
    t=int(r["timestamp_ms"])
    if t!=a+k*HOUR:raise ValueError("INCOMPLETE_OR_NONMONOTONIC_HOUR")
    o,h,l,c=(float(r[col]) for col in ("open","high","low","close"))
    if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or l>min(o,c) or h<max(o,c):
     raise ValueError("OHLC_INVALID")
    hourly.append({"ts":t,"open":o,"high":h,"low":l,"close":c})
   prev=b
  if prev!=END or len(hourly)!=151*24:
   raise ValueError("NOT_FULL_151D_WINDOW")
  bars=[]
  for start in range(0,len(hourly),4):
   chunk=hourly[start:start+4]
   if len(chunk)!=4 or any(chunk[z]["ts"]!=chunk[0]["ts"]+z*HOUR for z in range(4)):
    raise ValueError("NONCONTIGUOUS_4H")
   bars.append({"ts":chunk[0]["ts"],"open":chunk[0]["open"],
                "high":max(x["high"] for x in chunk),
                "low":min(x["low"] for x in chunk),
                "close":chunk[-1]["close"],"volume":0.0})
  if len(bars)!=906:raise ValueError("4H_LENGTH_CHANGED")
  streams[sym]=bars
  fingerprints[sym]={"daily_file_count":151,"hourly":len(hourly),"four_hour":len(bars),
      "digest_file_sha_list":sha(json.dumps(inp,sort_keys=True).encode()),
      "first_bar_utc":dt(bars[0]["ts"]),"last_bar_utc":dt(bars[-1]["ts"])}
 return streams,fingerprints,sha((root/"MANIFEST.json").read_bytes())


def scan(bars,spec,native,mode):
 _,engine=native._features(bars,spec)
 engine.validate(EXPECTED_ENTRY)
 features=engine.features if hasattr(engine,"features") else None
 # Read fully native indicators from the _features returned arrays.
 indicators,nengine=native._features(bars,spec) if features is None else (features,engine)
 # The second calculation above is avoided when engine.fields are accessible.
 n=len(bars)
 i=240
 trades=[];censored=[];fire_count=0;blocked_count=0
 while i < n-1:
  if not bool(nengine.eval(EXPECTED_ENTRY,i)):
   i+=1;continue
  fire_count+=1
  signal=i;enter=i+1;due=enter+11
  if due>=n:
   censored.append({"signal_ts":bars[signal]["ts"],"entry_ts":bars[enter]["ts"],"reason":"PARENT_H12_NOT_OBSERVED"})
   break
  if mode=="parent":
   exit_i=due
   exit_px=bars[exit_i]["close"]
   exit_clock=bars[exit_i]["ts"]+TF
   next_signal_i=exit_i+1
   etype="PARENT_H12_CLOSE_MODEL"
  else:
   # H12 original close cannot be retro-filled after EMA status is known.
   # One full bar latency charged before hypothetical opening fill.
   crossed=None
   for j in range(due,n):
    a=indicators["ema20"][j];b=indicators["ema50"][j]
    if a is None or b is None:raise ValueError("MISSING_NATIVE_EMA_AT_EXIT")
    if a<=b:
     crossed=j;break
   if crossed is None or crossed+2>=n:
    censored.append({"signal_ts":bars[signal]["ts"],"entry_ts":bars[enter]["ts"],
                     "asof_last_close":bars[-1]["ts"]+TF,
                     "mtm_at_end_bps":(bars[-1]["close"]/bars[enter]["open"]-1)*10000,
                     "reason":"UNRESOLVED_EMA_PERSISTENCE"})
    break
   exit_i=crossed+2
   exit_px=bars[exit_i]["open"]
   exit_clock=bars[exit_i]["ts"]
   next_signal_i=exit_i+1
   etype="MODEL_H12_PLUS_EMA_EXIT_1BAR_SIGNAL_LATENCY"
  gross=(exit_px/bars[enter]["open"]-1)*10000
  trades.append({"signal_ts":bars[signal]["ts"],"entry_ts":bars[enter]["ts"],
       "exit_ts":exit_clock,"entry_px":bars[enter]["open"],"exit_px":exit_px,
       "gross_bps":gross,"model_net1_bps":gross-20,"model_net2_bps":gross-40,
       "exit_kind":etype})
  blocked_count+=sum(bool(nengine.eval(EXPECTED_ENTRY,j)) for j in range(enter,next_signal_i))
  i=next_signal_i
 return trades,censored,fire_count,blocked_count


def metrics(trades,key):
 ordered=sorted(trades,key=lambda t:(t["exit_ts"],t["signal_ts"]))
 net=[t[key] for t in ordered];wins=[x for x in net if x>0];losses=[x for x in net if x<0]
 cum=peak=dd=0.;loss_streak=max_loss=0;win_streak=max_win=0
 for x in net:
  cum+=x;peak=max(peak,cum);dd=max(dd,peak-cum)
  if x<0:loss_streak+=1;win_streak=0
  elif x>0:win_streak+=1;loss_streak=0
  else:win_streak=0;loss_streak=0
  max_loss=max(max_loss,loss_streak);max_win=max(max_win,win_streak)
 return {"T":len(net),"win_count":len(wins),"WR":len(wins)/len(net) if net else None,
    "gross_sum_trade_bps":sum(t["gross_bps"] for t in ordered),
    "net_total_trade_bps":sum(net),
    "net_per_T_bps":sum(net)/len(net) if net else None,
    "PF":sum(wins)/-sum(losses) if losses else None,
    "realized_trade_bps_max_DD":dd,"loss_streak":max_loss,
    "win_streak":max_win}


def summarize(streams, native, spec):
 parents=[];children=[];counts={}
 allcensored=[];allcensoredparent=[]
 for sym,bars in streams.items():
  p,cp,fp,bp=scan(bars,spec,native,"parent")
  c,cc,fc,bc=scan(bars,spec,native,"child")
  for row in p:row["symbol"]=sym
  for row in c:row["symbol"]=sym
  parents+=p;children+=c
  for x in cp:allcensoredparent.append(dict(x,symbol=sym))
  for x in cc:allcensored.append(dict(x,symbol=sym))
  counts[sym]={"parent_T":len(p),"child_T":len(c),"parent_censored":len(cp),
              "child_censored":len(cc),"parent_fire":fp,"child_fire":fc,
              "parent_blocked_raw_signal":bp,"child_blocked_raw_signal":bc}
 parent_by={(x["symbol"],x["signal_ts"]):x for x in parents}
 child_by={(x["symbol"],x["signal_ts"]):x for x in children}
 stable=set(parent_by)&set(child_by)
 # Exact opportunity decomposition. No result-based runtime filter.
 exit_delta=sum(child_by[k]["model_net2_bps"]-parent_by[k]["model_net2_bps"] for k in stable)
 excluded_parent=sum(parent_by[k]["model_net2_bps"] for k in set(parent_by)-set(child_by))
 new_child=sum(child_by[k]["model_net2_bps"] for k in set(child_by)-set(parent_by))
 baseline_winners={k for k,v in parent_by.items() if v["model_net2_bps"]>0}
 kept_profitable={k for k in baseline_winners&set(child_by) if child_by[k]["model_net2_bps"]>0}
 top=sorted(parent_by.items(),key=lambda kv:kv[1]["model_net2_bps"],reverse=True)[:2]
 return {
    "dataset_label":"HISTORICAL_USED_DEV_MODELLED_BAR_CLOSE_4OF7_DIAGNOSTIC_NOT_REALIZED",
    "parent_id":PARENT,"child_id":CHILD,"universe":list(SYMS),
    "universe_coverage":"4_OF_7; missing original 1000PEPE BCH HYPE; no population parity",
    "source_window":{"from":dt(START),"until_exclusive":dt(END),"first_240_4h_bars_are_warmup_only":True},
    "fixed_cost_model":"20bps/roundtrip 1x,40bps/roundtrip 2x; actual fee/funding/slippage UNKNOWN",
    "no_original_historical_received_at":True,"no_untouched_OOS":True,"one_heavy":0,
    "parent":{"cost1x":metrics(parents,"model_net1_bps"),"cost2x":metrics(parents,"model_net2_bps"),"censored":len(allcensoredparent)},
    "child":{"cost1x":metrics(children,"model_net1_bps"),"cost2x":metrics(children,"model_net2_bps"),"censored":len(allcensored)},
    "net2_child_minus_parent_trade_bps":sum(t["model_net2_bps"] for t in children)-sum(t["model_net2_bps"] for t in parents),
    "parent_winners_2x":len(baseline_winners),"parent_winners_still_2x_profitable":len(kept_profitable),
    "parent_winner_2x_profit_retained_ratio_on_matched":sum(child_by[k]["model_net2_bps"] for k in kept_profitable)/sum(parent_by[k]["model_net2_bps"] for k in baseline_winners) if baseline_winners else None,
    "parent_top2_still_profitable":[{"symbol":k[0],"signal_time":dt(k[1]),
       "parent_2x":v["model_net2_bps"],"child_2x":child_by[k]["model_net2_bps"] if k in child_by else None} for k,v in top],
    "parent_unmatched_trades":len(set(parent_by)-set(child_by)),
    "child_only_trades":len(set(child_by)-set(parent_by)),
    "opportunity_attribution_cost2_bps":{
       "matched_trade_exit_change":exit_delta,
       "excluded_parent_trade_net2":excluded_parent,
       "child_only_trade_net2":new_child,
       "net_change_reconciled":exit_delta-excluded_parent+new_child,
       "identity_matched_count":len(stable),
       "original_positive_winners_excluded":len(baseline_winners-set(child_by)),
       "original_positive_winners_converted_negative":sum(child_by[k]["model_net2_bps"]<=0 for k in baseline_winners&set(child_by)),
       "original_positive_winners_still_positive":len(kept_profitable)
    },
    "per_symbol":counts,
    "censored_child_unrealized_mark_to_market_diagnostic_bps":[{**x,"entry_ts":dt(x["entry_ts"])} for x in allcensored],
    "original_g5_closed_27_trades_reused":False,
    "formal_G5A_or_G5B_credit":0,"economic_promotion_authority":False,
    "orders":0,"market_requests":0}


def selftest():
 a=[{"signal_ts":1,"exit_ts":10,"gross_bps":100,"model_net2_bps":60}]
 assert metrics(a,"model_net2_bps")["T"]==1
 assert metrics(a,"model_net2_bps")["win_count"]==1
 assert metrics(a,"model_net2_bps")["PF"] is None
 b=a+[{"signal_ts":2,"exit_ts":12,"gross_bps":0,"model_net2_bps":-40}]
 assert metrics(b,"model_net2_bps")["PF"]==1.5
 assert metrics(b,"model_net2_bps")["loss_streak"]==1
 assert len(SYMS)==4
 assert END-START==151*DAY
 assert TF==4*HOUR
 assert CHILD != PARENT
 assert EXPECTED_ENTRY.count("ema")>=2
 print(json.dumps({"tests":10,"status":"PASS","calls":0,"orders":0}))


def main():
 p=argparse.ArgumentParser()
 p.add_argument("--root",type=Path)
 p.add_argument("--archive",type=Path)
 p.add_argument("--out",type=Path)
 p.add_argument("--self-test",action="store_true")
 a=p.parse_args()
 if a.self_test:
  selftest();return
 if not a.root or not a.archive or not a.out:
  p.error("--root --archive --out required")
 if a.out.exists():p.error("output exists, no overwrite")
 native,spec=native_lib(a.root)
 streams,prov,manifest_sha=archive(a.archive)
 result=summarize(streams,native,spec)
 attrib=result["opportunity_attribution_cost2_bps"]
 if abs(attrib["net_change_reconciled"]-result["net2_child_minus_parent_trade_bps"])>1e-7:
  raise ValueError("ATTRIBUTION_DOES_NOT_RECONCILE")
 result["source_daily_receipt_digest_by_symbol"]=prov
 result["source_manifest_sha256"]=manifest_sha
 result["native_code_sha256_pins"]=NATIVE_PINS
 result["execution_state"]="MODELLED_DEV_ONLY_NO_ECONOMIC_FULL"
 body=(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
 with a.out.open("xb") as f:f.write(body)
 print(json.dumps({"status":"RESULT_WRITTEN","receipt_sha256":sha(body),"parentT":result["parent"]["cost2x"]["T"],
       "childT":result["child"]["cost2x"]["T"],"net2_delta":result["net2_child_minus_parent_trade_bps"]}))
if __name__=="__main__":main()
