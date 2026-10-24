#!/usr/bin/env python3
"""SOURCE-FIRST KAMA/EMA 1h isolated six-symbol MODELLED developer comparison.

Rule freeze: GitHub D branch commit 77eabc0a779bf9f6a6a1e55f5b76d8d7c573af38
Perry Kaufman 10,2,30 fast KAMA and 10,5,30 slow KAMA.
No historical received-at and NO actual open fills/funding -> no formal G5.
No market API or order path. Costs 20bps and 40bps fixed roundtrip model.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

FREEZE="77eabc0a779bf9f6a6a1e55f5b76d8d7c573af38"
SOURCE_PATH="/home/z/z/runtime/economic7_campaign_20260915/canonical_postgap_20260213"
IDENTITY="kama_adaptive_slow_rising_fast_price_cross_1h_long_cash_v1"
SYMBOLS=("BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","LINK-USDT","DOGE-USDT")
HOUR=3_600_000; DAY=24*HOUR
START="2026-02-14T00:00:00+00:00"
WARMUP=240
TRAIN_START="2026-03-05T00:00:00+00:00"
SPLIT="2026-06-01T00:00:00+00:00"
END="2026-08-30T00:00:00+00:00"
COS1=20.0
COS2=40.0

def ms(s):return int(datetime.fromisoformat(s).timestamp()*1000)
def ts(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
def sha(bs):return hashlib.sha256(bs).hexdigest()
def read_data(root):
    raw=(root/"MANIFEST.json").read_bytes()
    manifest=json.loads(raw)
    if(manifest.get("state")!="DATA_VALID_VOLUME_AUTHORITY_UNKNOWN"
        or manifest.get("data_integrity_complete") is not True
        or manifest.get("volume_unit")!="UNKNOWN"
        or manifest.get("synthetic_fill") is not False):
        raise ValueError("SOURCE_CONTRACT_DRIFT")
    if manifest["end_exclusive_ms"] < ms(END) or manifest["start_ms"]>ms(START):
        raise ValueError("SOURCE_COVERAGE_MISSING")
    data={};prov={}
    for sym in SYMBOLS:
        root_sym=root/"60m"/sym
        files=sorted(root_sym.glob("*.csv.gz"))
        rows=[];perfile=[];expected=ms(START)
        for p in files:
            a,b=map(int,p.name.removesuffix(".csv.gz").split("_"))
            if b<=ms(START) or a>=ms(END):
                continue
            if a!=expected or b!=a+DAY:
                raise ValueError("UTC_DAILY_GAP:"+sym)
            packed=p.read_bytes()
            perfile.append((p.name,sha(packed)))
            with gzip.open(p,"rt",newline="") as f:
                reader=csv.DictReader(f)
                if reader.fieldnames!=["timestamp_ms","open","high","low","close","volume"]:
                    raise ValueError("UNVERIFIED_COLUMN_SCHEMA")
                chunk=list(reader)
            if len(chunk)!=24:
                raise ValueError("HOUR_CHUNK_INCOMPLETE:"+sym)
            for i,r in enumerate(chunk):
                opened=int(r["timestamp_ms"])
                if opened!=a+i*HOUR:
                    raise ValueError("HOUR_TIME_OR_ORDER_DRIFT")
                vals=[float(r[k]) for k in ("open","high","low","close")]
                if not all(v>0 and math.isfinite(v) for v in vals) or vals[1]<max(vals[0],vals[3]) or vals[2]>min(vals[0],vals[3]):
                    raise ValueError("HOURLY_OHLC_INVALID")
                rows.append(dict(ts=opened,open=vals[0],high=vals[1],low=vals[2],close=vals[3]))
            expected=b
        if expected!=ms(END) or len(rows)!=(ms(END)-ms(START))//HOUR:
            raise ValueError("SOURCE_GAP_OR_SHORT:"+sym)
        data[sym]=rows
        prov[sym]={"daily_files":len(perfile),"original_files_manifest_sha256":sha(json.dumps(perfile,sort_keys=True).encode()),
                   "hour_bars":len(rows),"first_ts":rows[0]["ts"],"last_ts":rows[-1]["ts"]}
    return data,prov,sha(raw)

def kama(prices,er_period:int, fast:int, slow:int):
    if (er_period,fast,slow)!=(10,2,30) and (er_period,fast,slow)!=(10,5,30):
        raise ValueError("UNFROZEN_KAMA_PARAMS")
    if any(not math.isfinite(x) or x<=0 for x in prices):raise ValueError("INVALID_SOURCE_PRICES")
    out=[None]*len(prices)
    if len(prices)<er_period:
        return out
    out[er_period-1]=sum(prices[:er_period])/er_period
    fsc=2/(fast+1)
    ssc=2/(slow+1)
    for t in range(er_period,len(prices)):
        change=abs(prices[t]-prices[t-er_period])
        volatility=sum(abs(prices[k]-prices[k-1]) for k in range(t-er_period+1,t+1))
        er=change/volatility if volatility>0 else 0.
        smoothing=(er*(fsc-ssc)+ssc)**2
        out[t]=out[t-1]+smoothing*(prices[t]-out[t-1])
    return out

def ema(prices,n):
    alpha=2/(n+1)
    out=[prices[0]]
    for p in prices[1:]:
        out.append(alpha*p+(1-alpha)*out[-1])
    return out

def signal_arrays(bars,mechanism):
    closes=[x["close"] for x in bars]
    if mechanism=="KAMA":
        fast=kama(closes,10,2,30)
        slow=kama(closes,10,5,30)
    elif mechanism=="EMA_COMPARATOR":
        fast=ema(closes,20)
        slow=ema(closes,50)
    else:
        raise ValueError("NOT_FROZEN_MECHANISM")
    return fast,slow

def simulate(bars,mechanism,lo,hi):
    fast,slow=signal_arrays(bars,mechanism)
    closes=[x["close"] for x in bars]
    trades=[];signals=0;blocked=0
    position=None
    censored=[]
    for t in range(WARMUP,len(bars)-1):
        closed_at=bars[t]["ts"]+HOUR
        next_bar=bars[t+1]
        if closed_at<lo or closed_at>=hi:
            continue
        if any(v is None for v in (fast[t],fast[t-1],slow[t],slow[t-1])):
            raise ValueError("INDICATOR_NOT_READY")
        if position is not None:
            do_exit=closes[t]<fast[t] or slow[t]<=slow[t-1]
            if do_exit and next_bar["ts"]<hi:
                exit_px=next_bar["open"]
                gross=(exit_px/position["entry_px"]-1)*10_000
                trades.append({"entry_ts":position["entry_ts"],"exit_ts":next_bar["ts"],
                 "signal_ts":position["signal_ts"],"exit_signal_close_ts":closed_at,
                 "entry_px":position["entry_px"],"exit_px":exit_px,
                 "gross_bps":gross,"net_1x_bps":gross-COS1,"net_2x_bps":gross-COS2,
                 "exit_reason":"CLOSE_BROKE_FAST_KAMA_OR_SLOW_SLOPE" if mechanism=="KAMA" else "EMA_COMPARATOR_EXIT"})
                position=None
            continue
        entry=(closes[t-1]<=fast[t-1] and closes[t]>fast[t]
               and slow[t]>slow[t-1])
        if entry:
            signals+=1
            if next_bar["ts"]>=hi:
                censored.append({"signal_ts":bars[t]["ts"],"reason":"NEXT_BAR_OUT_OF_WINDOW"})
                continue
            position={"signal_ts":bars[t]["ts"],"entry_ts":next_bar["ts"],
                     "entry_px":next_bar["open"]}
    if position is not None:
        last_idx=next((i for i,x in enumerate(bars) if x["ts"]>=hi),len(bars))-1
        last=bars[last_idx]
        censored.append({"entry_ts":position["entry_ts"],
          "entry_px":position["entry_px"],"last_complete_close_ts":last["ts"]+HOUR,
          "mtm_gross_only_bps":(last["close"]/position["entry_px"]-1)*10000,
          "reason":"OPEN_AT_SOURCE_PARTITION_END_NO_FAVORABLE_SYNTHETIC_EXIT"})
    return trades,censored,signals

def metric(rows,key):
    rows=sorted(rows,key=lambda r:(r["exit_ts"],r["symbol"],r["entry_ts"]))
    nums=[r[key] for r in rows]
    wins=[x for x in nums if x>0];losses=[x for x in nums if x<0]
    equity=peak=dd=0.
    streak=max_streak=0
    for n in nums:
        equity+=n;peak=max(peak,equity);dd=max(dd,peak-equity)
        streak=streak+1 if n<0 else 0
        max_streak=max(max_streak,streak)
    bycohort=defaultdict(list)
    for r in rows:bycohort[r["exit_ts"]].append(r[key])
    losing_cohort_streak=current=0
    for ts in sorted(bycohort):
        if sum(bycohort[ts])<0:current+=1
        else:current=0
        losing_cohort_streak=max(losing_cohort_streak,current)
    top2=sorted(wins,reverse=True)[:2]
    return {"T":len(nums),"gross_sum_trade_bps":sum(r["gross_bps"] for r in rows),
       "net_sum_trade_bps":sum(nums),"net_per_T_bps":sum(nums)/len(nums) if nums else None,
       "PF":sum(wins)/(-sum(losses)) if losses else None,
       "WR":len(wins)/len(nums) if nums else None,
       "max_realized_trade_bps_DD":dd,"max_trade_loss_streak":max_streak,
       "max_negative_exit_cohort_streak":losing_cohort_streak,
       "top2_win_trade_bps_sum":sum(top2),
       "top2_share_of_net":sum(top2)/sum(nums) if sum(nums)>0 else None,
       "sameday_exit_multi_groups":sum(len(a)>1 for a in bycohort.values())}

def overlap(rows):
    es=[]
    for row in rows:
        es.append((row["entry_ts"],1))
        es.append((row["exit_ts"],-1))
    active=max_active=0
    for ts,inc in sorted(es,key=lambda x:(x[0],x[1])):
        active+=inc;max_active=max(active,max_active)
    return {"peak_concurrent_position_candidates":max_active,
      "capital_authority":"NOT_MODELLED"}

def report(data,provenance,manifestsha):
    periods=[("train",ms(TRAIN_START),ms(SPLIT)),("validation",ms(SPLIT),ms(END))]
    reports={}
    for name,a,b in periods:
        block={}
        for strategy in ("KAMA","EMA_COMPARATOR"):
            trades=[];unresolved=[];per_symbol={}
            for symbol,bars in data.items():
                t,c,signals=simulate(bars,strategy,a,b)
                for x in t:x["symbol"]=symbol
                for x in c:x["symbol"]=symbol
                trades.extend(t);unresolved.extend(c)
                per_symbol[symbol]={"T":len(t),"signal_count":signals,
                          "censored":len(c),"net2_sum_bps":sum(z["net_2x_bps"] for z in t)}
            block[strategy]={
              "cost1x":metric(trades,"net_1x_bps"),
              "cost2x":metric(trades,"net_2x_bps"),
              "censored":len(unresolved),
              "censored_rows":unresolved,
              "per_symbol":per_symbol,
              "raw_opportunities_per_calendar_day":len(trades)/((b-a)/DAY),
              "position_overlap":overlap(trades),
              "closed_rows":trades}
        reports[name]={"start_utc":ts(a),"end_exclusive_utc":ts(b),**block,
            "delta_kama_minus_ema_modelled_net2_trade_bps":
             block["KAMA"]["cost2x"]["net_sum_trade_bps"]-block["EMA_COMPARATOR"]["cost2x"]["net_sum_trade_bps"]}
    return {"schema":"zel.d.benchmark.original_kama_source_first.v1",
       "frozen_rule_git_commit":FREEZE,
       "classification":"MODELLED_HISTORICAL_DEVELOPMENT_6SYMBOL_NOT_FRESH_OR_LIVE",
       "source_manifest_sha256":manifestsha,
       "source_hourly_sha_by_symbol":provenance,
       "source_true_received_at_ms_available":False,
       "source_volume_unit":"UNKNOWN_UNNEEDED_PRICE_ONLY",
       "modeled_next_open_from_completed_hour":True,
       "assumed_same_boundary_quote_witness":False,
       "cost_model_roundtrip_trade_bps":{"1x":20,"2x":40},
       "real_fee_funding_slippage":None,
       "reused_market_history":True,
       "no_untouched_strict_oos_claim":True,
       "calendar_partitions":reports,
       "formal_G5_credit":False,"economic_heavy_runs":0,
       "orders":0,"market_requests":0}

def selftest():
    flat=[10.0]*15
    a=kama(flat,10,2,30)
    assert a[9]==10 and all(x==10. for x in a[10:])
    test=[10.+math.sin(i*.3)+.08*i for i in range(60)]
    a=kama(test,10,2,30);b=kama(test[:40],10,2,30)
    assert all(a[i]==b[i] for i in range(40)) # no lookahead
    c=kama(test,10,5,30);assert c[10]!=a[10]
    assert len(ema(test,20))==len(test)
    x=[{"entry_ts":1,"exit_ts":2,"symbol":"BTC","entry_px":10,"exit_px":11,"gross_bps":1000,
        "net_1x_bps":980,"net_2x_bps":960}]
    m=metric(x,"net_2x_bps")
    assert m["T"]==1 and m["net_sum_trade_bps"]==960
    assert m["PF"] is None
    assert overlap(x)["peak_concurrent_position_candidates"]==1
    assert WARMUP>10
    assert COS2==2*COS1
    assert ms(SPLIT)>ms(TRAIN_START)
    print(json.dumps({"synthetic_tests":10,"status":"PASS","market_requests":0,"orders":0}))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path)
    ap.add_argument("--out",type=Path)
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        selftest();return
    if not args.source_root or not args.out:ap.error("source-root and out required")
    if args.out.exists():ap.error("existing output immutable")
    data,prov,msha=read_data(args.source_root)
    body=report(data,prov,msha)
    raw=(json.dumps(body,indent=2,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n").encode()
    with args.out.open("xb") as f:f.write(raw)
    print(json.dumps({"state":"RESULT_WRITTEN","sha256":sha(raw),
       "train_T":body["calendar_partitions"]["train"]["KAMA"]["cost2x"]["T"],
       "train_Net2":body["calendar_partitions"]["train"]["KAMA"]["cost2x"]["net_sum_trade_bps"],
       "validation_T":body["calendar_partitions"]["validation"]["KAMA"]["cost2x"]["T"],
       "validation_Net2":body["calendar_partitions"]["validation"]["KAMA"]["cost2x"]["net_sum_trade_bps"]}))

if __name__=="__main__":
    main()
