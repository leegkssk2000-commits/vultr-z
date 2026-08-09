# -*- coding: utf-8 -*-
"""
Evidence-derived research alpha families.
Research-only signal constructors. No order/execution authority.
All functions are causal and inspect only completed rows supplied by the caller.
HTF-dependent families fail closed if htf_ohlc is absent.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from engine.registry import register

def _none(source, reason):
    return {"side": None, "confidence": 0.0, "ttl": 300, "source": source, "research_only": True, "reason": reason}

def _ema(s, n): return s.ewm(span=n, adjust=False).mean()

def _atr(df, n=14):
    pc=df["close"].shift(1)
    tr=pd.concat([(df["high"]-df["low"]).abs(), (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def _htf_bias(htf):
    if htf is None or len(htf) < 205: return None
    c=htf["close"].astype(float); e50=_ema(c,50).iloc[-1]; e200=_ema(c,200).iloc[-1]; px=c.iloc[-1]
    if px > e50 > e200: return "buy"
    if px < e50 < e200: return "sell"
    return None

def _risk_payload(side, px, atr, source, conf, stop_atr, target_r, reason):
    if side=="buy": stop=px-stop_atr*atr; target=px+target_r*(px-stop)
    else: stop=px+stop_atr*atr; target=px-target_r*(stop-px)
    return {"side":side,"confidence":float(max(0,min(1,conf))),"ttl":300,"source":source,
            "research_only":True,"entry_reference":float(px),"stop":float(stop),"target":float(target),"reason":reason}

@register("eaf_trend_pullback_continuation_v1")
def trend_pullback_continuation(ohlc=None, htf_ohlc=None, pullback_atr=None, stop_atr=None, target_r=None, **kw):
    src="eaf_trend_pullback_continuation_v1"
    if ohlc is None or len(ohlc)<205: return _none(src,"insufficient_ltf")
    bias=_htf_bias(htf_ohlc)
    if bias is None: return _none(src,"htf_not_aligned")
    if pullback_atr is None or stop_atr is None or target_r is None: return _none(src,"calibrate_micro_required")
    c=ohlc["close"].astype(float); px=float(c.iloc[-1]); e21=float(_ema(c,21).iloc[-1]); e50=float(_ema(c,50).iloc[-1]); a=float(_atr(ohlc).iloc[-1])
    if not np.isfinite(a) or a<=0: return _none(src,"atr_invalid")
    resumed=(bias=="buy" and px>e21>e50 and abs(float(ohlc["low"].iloc[-2])-e21)<=pullback_atr*a) or (bias=="sell" and px<e21<e50 and abs(float(ohlc["high"].iloc[-2])-e21)<=pullback_atr*a)
    if not resumed: return _none(src,"no_pullback_resumption")
    return _risk_payload(bias,px,a,src,abs(px-e21)/a,stop_atr,target_r,"htf_align_pullback_resumption")

@register("eaf_volatility_breakout_v1")
def volatility_breakout(ohlc=None, htf_ohlc=None, channel=None, breakout_atr_min=None, stop_atr=None, target_r=None, **kw):
    src="eaf_volatility_breakout_v1"
    if ohlc is None: return _none(src,"missing_ohlc")
    if None in (channel,breakout_atr_min,stop_atr,target_r): return _none(src,"calibrate_micro_required")
    channel=int(channel)
    if len(ohlc)<max(channel+2,205): return _none(src,"insufficient_ltf")
    bias=_htf_bias(htf_ohlc)
    if bias is None: return _none(src,"htf_not_aligned")
    hi=float(ohlc["high"].rolling(channel).max().iloc[-2]); lo=float(ohlc["low"].rolling(channel).min().iloc[-2]); px=float(ohlc["close"].iloc[-1]); a=float(_atr(ohlc).iloc[-1])
    if not np.isfinite(a) or a<=0: return _none(src,"atr_invalid")
    dist=(px-hi)/a if bias=="buy" else (lo-px)/a
    if dist < float(breakout_atr_min): return _none(src,"breakout_too_weak")
    return _risk_payload(bias,px,a,src,min(1,dist),float(stop_atr),float(target_r),"aligned_volatility_breakout")

@register("eaf_liquidity_reclaim_reversal_v1")
def liquidity_reclaim_reversal(ohlc=None, lookback=None, reclaim_atr_min=None, stop_atr=None, target_r=None, **kw):
    src="eaf_liquidity_reclaim_reversal_v1"
    if ohlc is None: return _none(src,"missing_ohlc")
    if None in (lookback,reclaim_atr_min,stop_atr,target_r): return _none(src,"calibrate_micro_required")
    lookback=int(lookback)
    if len(ohlc)<lookback+3: return _none(src,"insufficient_ltf")
    prev=ohlc.iloc[-lookback-2:-2]; bar=ohlc.iloc[-1]; prior=ohlc.iloc[-2]; a=float(_atr(ohlc).iloc[-1])
    if not np.isfinite(a) or a<=0: return _none(src,"atr_invalid")
    support=float(prev["low"].min()); resistance=float(prev["high"].max())
    buy=float(prior["low"])<support and float(bar["close"])>support and (float(bar["close"])-support)/a>=float(reclaim_atr_min)
    sell=float(prior["high"])>resistance and float(bar["close"])<resistance and (resistance-float(bar["close"]))/a>=float(reclaim_atr_min)
    if buy==sell: return _none(src,"no_unique_sweep_reclaim")
    side="buy" if buy else "sell"; px=float(bar["close"])
    return _risk_payload(side,px,a,src,min(1,abs(px-(support if buy else resistance))/a),float(stop_atr),float(target_r),"sweep_reclaim")

@register("eaf_htf_structure_ltf_execution_v1")
def htf_structure_ltf_execution(ohlc=None, htf_ohlc=None, retest_atr=None, stop_atr=None, target_r=None, **kw):
    src="eaf_htf_structure_ltf_execution_v1"
    if ohlc is None or len(ohlc)<55: return _none(src,"insufficient_ltf")
    bias=_htf_bias(htf_ohlc)
    if bias is None: return _none(src,"htf_not_aligned")
    if None in (retest_atr,stop_atr,target_r): return _none(src,"calibrate_micro_required")
    c=ohlc["close"].astype(float); a=float(_atr(ohlc).iloc[-1]); e50=float(_ema(c,50).iloc[-1]); px=float(c.iloc[-1])
    if not np.isfinite(a) or a<=0: return _none(src,"atr_invalid")
    p=ohlc.iloc[-2]
    retest=(bias=="buy" and float(p["low"])<=e50+float(retest_atr)*a and px>float(p["high"])) or (bias=="sell" and float(p["high"])>=e50-float(retest_atr)*a and px<float(p["low"]))
    if not retest: return _none(src,"no_ltf_retest_break")
    return _risk_payload(bias,px,a,src,min(1,abs(px-e50)/a),float(stop_atr),float(target_r),"htf_structure_ltf_retest_break")

@register("eaf_cost_aware_momentum_v1")
def cost_aware_momentum(ohlc=None, htf_ohlc=None, momentum_bars=None, move_cost_multiple=None, round_trip_cost_pct=None, stop_atr=None, target_r=None, **kw):
    src="eaf_cost_aware_momentum_v1"; required=(momentum_bars,move_cost_multiple,round_trip_cost_pct,stop_atr,target_r)
    if ohlc is None or any(x is None for x in required): return _none(src,"calibrate_micro_or_cost_required")
    n=int(momentum_bars)
    if len(ohlc)<max(n+2,205): return _none(src,"insufficient_ltf")
    bias=_htf_bias(htf_ohlc)
    if bias is None: return _none(src,"htf_not_aligned")
    px=float(ohlc["close"].iloc[-1]); old=float(ohlc["close"].iloc[-1-n]); mom=px/old-1.0; hurdle=float(round_trip_cost_pct)*float(move_cost_multiple)
    if bias=="buy" and mom<=hurdle: return _none(src,"momentum_below_cost_hurdle")
    if bias=="sell" and -mom<=hurdle: return _none(src,"momentum_below_cost_hurdle")
    a=float(_atr(ohlc).iloc[-1])
    if not np.isfinite(a) or a<=0: return _none(src,"atr_invalid")
    return _risk_payload(bias,px,a,src,min(1,abs(mom)/max(hurdle,1e-9)-1.0),float(stop_atr),float(target_r),"momentum_clears_cost_hurdle")
