#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, COST_BPS, SYMBOLS, bars

INTERVALS=("5m","15m","30m","1h","4h")
HORIZONS=(1,3,6,12)
MIN_EVENTS=20


def _ema(xs:list[float], n:int)->list[float]:
    a=2.0/(n+1.0); out=[]; v=xs[0] if xs else 0.0
    for x in xs:
        v=a*x+(1.0-a)*v; out.append(v)
    return out


def _sma(xs:list[float], n:int)->list[float|None]:
    out=[]; s=0.0
    for i,x in enumerate(xs):
        s+=x
        if i>=n:s-=xs[i-n]
        out.append(s/n if i>=n-1 else None)
    return out


def _std(xs:list[float], n:int)->list[float|None]:
    out=[]
    for i in range(len(xs)):
        if i<n-1: out.append(None); continue
        w=xs[i-n+1:i+1]; m=sum(w)/n
        out.append(math.sqrt(sum((x-m)**2 for x in w)/n))
    return out


def _pf(xs:list[float])->float|None:
    gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0)
    return None if gl<=0 else gp/gl


def _payoff(xs:list[float])->float|None:
    w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]
    return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))


def _dd(xs:list[float])->float:
    eq=peak=mx=0.0
    for x in xs:
        eq+=x; peak=max(peak,eq); mx=max(mx,peak-eq)
    return mx


def _features(rs:list[dict[str,float]])->dict[str,list[Any]]:
    close=[r["close"] for r in rs]; volume=[r["volume"] for r in rs]
    ema20=_ema(close,20); ema50=_ema(close,50); ema100=_ema(close,100)
    sma_vol20=_sma(volume,20); std20=_std(close,20)
    rets=[0.0]
    for i in range(1,len(close)):
        rets.append(close[i]/close[i-1]-1.0 if close[i-1] else 0.0)
    retstd20=_std(rets,20)
    highest20=[]; lowest20=[]; highest50=[]; lowest50=[]
    for i in range(len(rs)):
        w20=rs[max(0,i-19):i+1]; w50=rs[max(0,i-49):i+1]
        highest20.append(max(x["high"] for x in w20)); lowest20.append(min(x["low"] for x in w20))
        highest50.append(max(x["high"] for x in w50)); lowest50.append(min(x["low"] for x in w50))
    return {"ema20":ema20,"ema50":ema50,"ema100":ema100,"sma_vol20":sma_vol20,"std20":std20,"retstd20":retstd20,"highest20":highest20,"lowest20":lowest20,"highest50":highest50,"lowest50":lowest50}


def _events(rs:list[dict[str,float]], f:dict[str,list[Any]])->list[dict[str,Any]]:
    out=[]
    for i in range(100,len(rs)-max(HORIZONS)-1):
        r=rs[i]; prev=rs[i-1]
        vol_ma=f["sma_vol20"][i]; sd=f["std20"][i]; rv=f["retstd20"][i]
        ema20=f["ema20"][i]; ema50=f["ema50"][i]; ema100=f["ema100"][i]
        if not vol_ma or not sd or not rv or r["close"]<=0: continue
        vol_ratio=r["volume"]/vol_ma if vol_ma>0 else 0.0
        z=(r["close"]-ema20)/sd if sd>0 else 0.0
        body=(r["close"]-r["open"])/r["close"]
        body_abs=abs(body); range_pct=(r["high"]-r["low"])/r["close"]
        upper=(r["high"]-max(r["open"],r["close"]))/r["close"]
        lower=(min(r["open"],r["close"])-r["low"])/r["close"]
        ret1=r["close"]/prev["close"]-1.0 if prev["close"] else 0.0
        hour=datetime.fromtimestamp(r["ts"]/1000,tz=timezone.utc).hour
        high_vol=abs(ret1)>=1.5*rv; low_vol=abs(ret1)<=0.5*rv
        london_us=6<=hour<18; asia=0<=hour<6
        defs=[
            ("P_VOL_SHOCK_CONT_LONG", vol_ratio>=2.0 and ret1>0, 1),
            ("P_VOL_SHOCK_CONT_SHORT", vol_ratio>=2.0 and ret1<0, -1),
            ("P_VOL_SHOCK_FADE_LONG", vol_ratio>=2.5 and ret1<=-0.004, 1),
            ("P_VOL_SHOCK_FADE_SHORT", vol_ratio>=2.5 and ret1>=0.004, -1),
            ("P_BREAKOUT20_LONG", r["close"]>f["highest20"][i-1] and vol_ratio>=1.2, 1),
            ("P_BREAKDOWN20_SHORT", r["close"]<f["lowest20"][i-1] and vol_ratio>=1.2, -1),
            ("P_BREAKOUT50_LONG", r["close"]>f["highest50"][i-1] and ema20>ema50 and vol_ratio>=1.1, 1),
            ("P_BREAKDOWN50_SHORT", r["close"]<f["lowest50"][i-1] and ema20<ema50 and vol_ratio>=1.1, -1),
            ("P_TREND_CONT_LONG", ema20>ema50>ema100 and ret1>0 and vol_ratio>=1.0, 1),
            ("P_TREND_CONT_SHORT", ema20<ema50<ema100 and ret1<0 and vol_ratio>=1.0, -1),
            ("P_TREND_PULL_LONG", ema20>ema50 and prev["close"]<=f["ema20"][i-1] and r["close"]>ema20, 1),
            ("P_TREND_PULL_SHORT", ema20<ema50 and prev["close"]>=f["ema20"][i-1] and r["close"]<ema20, -1),
            ("P_ZREV_LONG", z<=-1.5, 1),
            ("P_ZREV_SHORT", z>=1.5, -1),
            ("P_WIDE_BODY_CONT_LONG", body>=0.004 and range_pct>=0.006, 1),
            ("P_WIDE_BODY_CONT_SHORT", body<=-0.004 and range_pct>=0.006, -1),
            ("P_LOWER_WICK_REJECT_LONG", lower>=0.004 and lower>=2.0*body_abs and r["close"]>=r["open"], 1),
            ("P_UPPER_WICK_REJECT_SHORT", upper>=0.004 and upper>=2.0*body_abs and r["close"]<=r["open"], -1),
            ("P_HIGHVOL_MOM_LONG", high_vol and ret1>0 and ema20>ema50, 1),
            ("P_HIGHVOL_MOM_SHORT", high_vol and ret1<0 and ema20<ema50, -1),
            ("P_LOWVOL_BREAK_LONG", low_vol and r["close"]>f["highest20"][i-1], 1),
            ("P_LOWVOL_BREAK_SHORT", low_vol and r["close"]<f["lowest20"][i-1], -1),
            ("P_LONDONUS_BREAK_LONG", london_us and r["close"]>f["highest20"][i-1] and vol_ratio>=1.2, 1),
            ("P_LONDONUS_BREAK_SHORT", london_us and r["close"]<f["lowest20"][i-1] and vol_ratio>=1.2, -1),
            ("P_ASIA_MEANREV_LONG", asia and z<=-1.5, 1),
            ("P_ASIA_MEANREV_SHORT", asia and z>=1.5, -1),
        ]
        for pid,fire,side in defs:
            if fire: out.append({"i":i,"primitive_id":pid,"side":side})
    return out


def mine()->dict[str,Any]:
    buckets:dict[tuple[str,str,int],list[float]]={}; timestamps:dict[tuple[str,str,int],list[int]]={}; source={}
    for interval in INTERVALS:
        source[interval]={}
        for symbol in SYMBOLS:
            rs=bars(symbol,interval); source[interval][symbol]={"bars":len(rs)}; f=_features(rs)
            for ev in _events(rs,f):
                i=int(ev["i"]); side=int(ev["side"]); pid=str(ev["primitive_id"]); entry=rs[i+1]["open"]
                for h in HORIZONS:
                    if i+1+h>=len(rs): continue
                    exit_px=rs[i+1+h]["close"]; gross=(exit_px/entry-1.0)*10000*side
                    key=(interval,pid,h); buckets.setdefault(key,[]).append(gross); timestamps.setdefault(key,[]).append(int(rs[i+1]["ts"]))
    rows=[]
    for (interval,pid,h),gross in buckets.items():
        net=[x-COST_BPS for x in gross]; n=len(net); pf=_pf(net); g=sum(gross)/n if n else None; ne=sum(net)/n if n else None
        ts=timestamps.get((interval,pid,h),[]); days=max(1.0,((max(ts)-min(ts))/86_400_000) if len(ts)>=2 else 1.0)
        usable=bool(n>=MIN_EVENTS and (ne or 0)>0 and (pf or 0)>1.0)
        rows.append({"primitive_id":pid,"interval":interval,"horizon_bars":h,"events":n,"gross_expectancy_bps":g,"net_expectancy_bps":ne,"net_pnl_bps":sum(net),"profit_factor":pf,"payoff":_payoff(net),"win_rate":sum(1 for x in net if x>0)/n if n else None,"drawdown_bps":_dd(net),"cost_bps_per_trade":COST_BPS,"events_per_day":n/days,"net_bps_per_calendar_day":sum(net)/days,"gross_clears_cost":bool(n>=MIN_EVENTS and (g or 0)>COST_BPS),"economically_usable":usable})
    rows.sort(key=lambda x:(not x["economically_usable"],not x["gross_clears_cost"],-(x["net_expectancy_bps"] or -1e9),-x["events"]))
    usable=[x for x in rows if x["economically_usable"]]; gross_clear=[x for x in rows if x["gross_clears_cost"]]
    near=sorted([x for x in rows if x["events"]>=MIN_EVENTS],key=lambda x:-(x["gross_expectancy_bps"] or -1e9))[:20]
    result={"schema_version":"zel.a1_alpha_primitive_miner.v2","boundary":BOUNDARY,"development_only":True,"fixed_library":True,"threshold_sweep":False,"future_or_sealed_outcomes_used":False,"cost_bps_per_trade":COST_BPS,"min_events":MIN_EVENTS,"source":source,"primitive_count":len(rows),"economically_usable_count":len(usable),"gross_clears_cost_count":len(gross_clear),"usable":usable[:30],"gross_clear":gross_clear[:30],"top_by_gross":near,"rows":rows,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"}
    os.environ["GEN2_PRIMITIVE_USABLE_COUNT"]=str(len(usable))
    if not usable:
        os.environ["OPENAI_API_KEY"]=""
        os.environ["GEMINI_API_KEY"]=""
        os.environ["GEN2_PAID_AI_GATE"]="BLOCKED_NO_COST_POSITIVE_PRIMITIVE"
    else:
        os.environ["GEN2_PAID_AI_GATE"]="OPEN_COST_POSITIVE_PRIMITIVE"
    return result


def compact(result:dict[str,Any])->list[dict[str,Any]]:
    keys=("primitive_id","interval","horizon_bars","events","gross_expectancy_bps","net_expectancy_bps","profit_factor","payoff","win_rate","drawdown_bps","events_per_day","net_bps_per_calendar_day","cost_bps_per_trade")
    return [{k:r.get(k) for k in keys} for r in (result.get("usable") or [])]


def main()->int:
    r=mine(); print(json.dumps(r,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
