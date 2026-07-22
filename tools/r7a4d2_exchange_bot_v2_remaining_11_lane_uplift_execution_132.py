#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

PLAN_PATH = Path("runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_plan/remaining_11_lane_uplift_plan_v1.json")
CALIBRATION_PATH = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json")
MANIFEST_PATH = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132")

EXPECTED_BUNDLES = 22
EXPECTED_CELLS = 132
EXPECTED_STRESS_PER_BUNDLE = 6
EXPECTED_SEGMENTS = 24
EXPECTED_FOLDS = 6
MINIMUM_TRADES = 24
MINIMUM_SYMBOLS = 3
MINIMUM_POSITIVE_FOLDS = 4
MINIMUM_POSITIVE_PRIMARY_CELLS = 3
REFERENCE_LANE_ID = "dual_donchian_trend_bot:15m"

VARIANT_IDS = {
    "atr15_close_retest_maker",
    "atr15_breakout_persistence",
    "atr5_with_15m_context_retest",
    "atr5_impulse_quality_filter",
    "donchian5_15m_context_retest",
    "donchian5_false_break_filter",
    "ma15_cross_then_pullback",
    "ma15_slope_acceleration",
    "vwap15_range_only_outer_reclaim",
    "vwap15_session_anchor_reversion",
    "neutral_grid5_cost_spaced_inventory_cap",
    "neutral_grid5_volatility_scaled",
    "ma5_as_15m_context_trigger",
    "ma5_donchian_confluence",
    "vwap5_with_15m_range_context",
    "vwap5_failed_auction_reclaim",
    "grid15_context_5m_execution",
    "grid15_session_range_engine",
    "trend_grid15_context_5m_ladder",
    "trend_grid15_breakout_retest_ladder",
    "trend_grid5_donchian15_context",
    "trend_grid5_impulse_retest",
}

EXECUTION_TIMEFRAME = {
    "grid15_context_5m_execution": "5m",
    "trend_grid15_context_5m_ladder": "5m",
    "trend_grid15_breakout_retest_ladder": "5m",
}

def import_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)

def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()

def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    tr = pd.concat([(high-low), (high-previous).abs(), (low-previous).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def rolling_vwap(frame: pd.DataFrame, lookback: int) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (frame["high"].astype(float)+frame["low"].astype(float)+frame["close"].astype(float))/3.0
    weighted = (typical*volume).rolling(lookback, min_periods=lookback).sum()
    total = volume.rolling(lookback, min_periods=lookback).sum()
    fallback = typical.rolling(lookback, min_periods=lookback).mean()
    return weighted.div(total.where(total>0)).fillna(fallback)

def anchored_vwap(frame: pd.DataFrame) -> pd.Series:
    volume = frame["volume"].astype(float)
    typical = (frame["high"].astype(float)+frame["low"].astype(float)+frame["close"].astype(float))/3.0
    total = volume.cumsum()
    return (typical*volume).cumsum().div(total.where(total>0)).fillna(typical.expanding().mean())

def volume_z(frame: pd.DataFrame, lookback: int = 20) -> pd.Series:
    volume = frame["volume"].astype(float)
    mean = volume.rolling(lookback, min_periods=lookback).mean()
    std = volume.rolling(lookback, min_periods=lookback).std(ddof=0).replace(0, np.nan)
    return (volume-mean).div(std)

def edge(condition: pd.Series) -> pd.Series:
    clean = condition.fillna(False).astype(bool)
    return clean & ~clean.shift(1, fill_value=False)

def context_columns(frame5: pd.DataFrame, frame15: pd.DataFrame) -> pd.DataFrame:
    base = frame5.copy()
    ctx = pd.DataFrame({
        "__timestamp": frame15["__timestamp"].astype(float),
        "ctx_close": frame15["close"].astype(float),
        "ctx_atr": atr(frame15, 14),
    })
    ctx["ctx_ema20"] = ema(frame15["close"], 20)
    ctx["ctx_ema50"] = ema(frame15["close"], 50)
    ctx["ctx_slope"] = ctx["ctx_ema50"].diff(4).div(4.0*ctx["ctx_atr"])
    ctx["ctx_high20"] = frame15["high"].astype(float).shift(1).rolling(20, min_periods=20).max()
    ctx["ctx_low20"] = frame15["low"].astype(float).shift(1).rolling(20, min_periods=20).min()
    ctx["ctx_mid20"] = (ctx["ctx_high20"]+ctx["ctx_low20"])/2.0
    ctx["ctx_width_atr"] = (ctx["ctx_high20"]-ctx["ctx_low20"]).div(ctx["ctx_atr"])
    ctx["ctx_mid_slope"] = ctx["ctx_mid20"].diff(4).abs().div(4.0*ctx["ctx_atr"])
    left = base.sort_values("__timestamp").reset_index().rename(columns={"index":"__original_index"})
    merged = pd.merge_asof(
        left,
        ctx.sort_values("__timestamp"),
        on="__timestamp",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("__original_index").drop(columns=["__original_index"]).reset_index(drop=True)
    return merged

def base_round_trip_cost(calibration: dict[str, Any]) -> float:
    model = calibration.get("corrected_execution_model", {})
    for profile in model.get("profiles", []):
        if isinstance(profile, dict) and str(profile.get("id")) == "cost_profile_0":
            return finite(profile.get("round_trip_cost_pct"), math.nan)
    return math.nan

def append_signal(
    signals: list[dict[str, Any]],
    rejected: Counter[str],
    frame: pd.DataFrame,
    measurement: pd.Series,
    base_cost_pct: float,
    index: int,
    side: str,
    stop: float,
    target: float,
    timeout: int,
    reason: str,
    level_id: str | None = None,
) -> None:
    if index < 0 or index+1 >= len(frame):
        rejected["NO_NEXT_BAR"] += 1
        return
    if not bool(measurement.iloc[index]) or not bool(measurement.iloc[index+1]):
        rejected["OUTSIDE_MEASUREMENT"] += 1
        return
    entry = finite(frame.iloc[index+1]["open"], math.nan)
    if not all(math.isfinite(x) for x in (entry, stop, target)):
        rejected["GEOMETRY_NONFINITE"] += 1
        return
    if side == "long":
        valid = 0 < stop < entry < target
    else:
        valid = stop > entry > target > 0
    if not valid:
        rejected["GEOMETRY_INVALID"] += 1
        return
    risk_pct = abs(entry-stop)/entry*100.0
    target_pct = abs(target-entry)/entry*100.0
    if target_pct/base_cost_pct < 3.0 or risk_pct/base_cost_pct < 2.0:
        rejected["ECONOMIC_ADMISSION_REJECT"] += 1
        return
    signals.append({
        "signal_bar_index": int(index),
        "entry_bar_index": int(index+1),
        "side": side,
        "stop_price": float(stop),
        "target_price": float(target),
        "timeout_bars": int(max(2, timeout)),
        "reason": reason,
        "level_id": level_id,
        "risk_pct_at_admission": risk_pct,
        "target_move_pct_at_admission": target_pct,
        "target_to_base_cost_ratio": target_pct/base_cost_pct,
        "risk_to_base_cost_ratio": risk_pct/base_cost_pct,
    })

def retest_after_break(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    boundary: pd.Series,
    break_cond: pd.Series,
    side: str,
    window: int,
) -> list[int]:
    out: list[int] = []
    breaks = np.flatnonzero(edge(break_cond).to_numpy(dtype=bool))
    for raw in breaks:
        b = int(raw)
        for i in range(b+1, min(len(close), b+window+1)):
            level = finite(boundary.iloc[b], math.nan)
            if not math.isfinite(level):
                continue
            if side == "long" and low.iloc[i] <= level and close.iloc[i] > level:
                out.append(i); break
            if side == "short" and high.iloc[i] >= level and close.iloc[i] < level:
                out.append(i); break
    return out

def generate_variant_signals(
    variant_id: str,
    frame: pd.DataFrame,
    measurement: pd.Series,
    frame15: pd.DataFrame,
    segment_regime: str,
    base_cost_pct: float,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    signals: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    close = frame["close"].astype(float)
    open_v = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    a = atr(frame, 14)
    vz = volume_z(frame)
    body = (close-open_v).abs()
    span = (high-low).replace(0, np.nan)
    clv = (close-low).div(span)
    tf = str(frame.get("timeframe", pd.Series(["5m"])).iloc[0])
    ctx = context_columns(frame, frame15) if tf == "5m" else frame.assign(
        ctx_close=close,
        ctx_atr=a,
        ctx_ema20=ema(close,20),
        ctx_ema50=ema(close,50),
        ctx_slope=ema(close,50).diff(4).div(4.0*a),
        ctx_high20=high.shift(1).rolling(20,min_periods=20).max(),
        ctx_low20=low.shift(1).rolling(20,min_periods=20).min(),
    )
    if "ctx_mid20" not in ctx:
        ctx["ctx_mid20"]=(ctx["ctx_high20"]+ctx["ctx_low20"])/2.0
        ctx["ctx_width_atr"]=(ctx["ctx_high20"]-ctx["ctx_low20"]).div(ctx["ctx_atr"])
        ctx["ctx_mid_slope"]=ctx["ctx_mid20"].diff(4).abs().div(4.0*ctx["ctx_atr"])

    def add(i:int, side:str, risk_mult:float, reward_mult:float, timeout:int, reason:str, anchor:float|None=None, level_id:str|None=None):
        av=finite(a.iloc[i], math.nan)
        cv=finite(close.iloc[i], math.nan)
        if not math.isfinite(av) or av<=0: return
        if side=="long":
            stop=min(finite(low.iloc[i],cv)-0.10*av, cv-risk_mult*av)
            target=(anchor if anchor is not None and anchor>cv else cv+reward_mult*av)
        else:
            stop=max(finite(high.iloc[i],cv)+0.10*av, cv+risk_mult*av)
            target=(anchor if anchor is not None and 0<anchor<cv else cv-reward_mult*av)
        append_signal(signals,rejected,frame,measurement,base_cost_pct,i,side,stop,target,timeout,reason,level_id)

    if variant_id == "atr15_close_retest_maker":
        if segment_regime not in {"trend_up","trend_down"}: return signals, Counter({"REGIME_VETO":1})
        ph=high.shift(1).rolling(10,min_periods=10).max(); pl=low.shift(1).rolling(10,min_periods=10).min()
        lb=(span>=1.25*a)&(clv>=0.70)&(vz>=0)&(close>=ph)
        sb=(span>=1.25*a)&(clv<=0.30)&(vz>=0)&(close<=pl)
        for i in retest_after_break(close,high,low,ph,lb,"long",4): add(i,"long",1.25,3.5,24,"atr15_close_retest")
        for i in retest_after_break(close,high,low,pl,sb,"short",4): add(i,"short",1.25,3.5,24,"atr15_close_retest")

    elif variant_id == "atr15_breakout_persistence":
        ph=high.shift(2).rolling(10,min_periods=10).max(); pl=low.shift(2).rolling(10,min_periods=10).min()
        e50=ema(close,50); slope=e50.diff(4).div(4*a)
        long=(close>ph)&(close.shift(1)>ph.shift(1))&(slope>0.02)&(vz>0)
        short=(close<pl)&(close.shift(1)<pl.shift(1))&(slope<-0.02)&(vz>0)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.2,4.0,32,"atr15_two_close_persistence")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.2,4.0,32,"atr15_two_close_persistence")

    elif variant_id == "atr5_with_15m_context_retest":
        ph=high.shift(1).rolling(10,min_periods=10).max(); pl=low.shift(1).rolling(10,min_periods=10).min()
        long_ctx=(ctx["ctx_close"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0.01)
        short_ctx=(ctx["ctx_close"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<-0.01)
        lb=(span>=1.20*a)&(clv>0.68)&(vz>0)&(close>=ph)&long_ctx
        sb=(span>=1.20*a)&(clv<0.32)&(vz>0)&(close<=pl)&short_ctx
        for i in retest_after_break(close,high,low,ph,lb,"long",3): add(i,"long",1.0,3.2,18,"atr5_15m_context_retest")
        for i in retest_after_break(close,high,low,pl,sb,"short",3): add(i,"short",1.0,3.2,18,"atr5_15m_context_retest")

    elif variant_id == "atr5_impulse_quality_filter":
        ph=high.shift(1).rolling(12,min_periods=12).max(); pl=low.shift(1).rolling(12,min_periods=12).min()
        long=(span>=1.40*a)&(body/span>=0.65)&(clv>=0.82)&(vz>=1.0)&(close>=ph)
        short=(span>=1.40*a)&(body/span>=0.65)&(clv<=0.18)&(vz>=1.0)&(close<=pl)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.1,3.6,12,"atr5_top_quality_impulse")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.1,3.6,12,"atr5_top_quality_impulse")

    elif variant_id == "donchian5_15m_context_retest":
        ph=high.shift(1).rolling(20,min_periods=20).max(); pl=low.shift(1).rolling(20,min_periods=20).min()
        lb=(close>ph)&(ctx["ctx_close"]>ctx["ctx_high20"])&(ctx["ctx_slope"]>0)
        sb=(close<pl)&(ctx["ctx_close"]<ctx["ctx_low20"])&(ctx["ctx_slope"]<0)
        for i in retest_after_break(close,high,low,ph,lb,"long",5): add(i,"long",1.1,3.4,24,"donchian5_15m_context_retest")
        for i in retest_after_break(close,high,low,pl,sb,"short",5): add(i,"short",1.1,3.4,24,"donchian5_15m_context_retest")

    elif variant_id == "donchian5_false_break_filter":
        ph=high.shift(2).rolling(20,min_periods=20).max(); pl=low.shift(2).rolling(20,min_periods=20).min()
        lb=(close>ph)&(close.shift(1)>ph.shift(1))
        sb=(close<pl)&(close.shift(1)<pl.shift(1))
        for i in retest_after_break(close,high,low,ph,lb,"long",4): add(i,"long",1.0,3.5,28,"donchian5_two_close_retest")
        for i in retest_after_break(close,high,low,pl,sb,"short",4): add(i,"short",1.0,3.5,28,"donchian5_two_close_retest")

    elif variant_id == "ma15_cross_then_pullback":
        f=ema(close,12); s=ema(close,26); cross_up=edge((f>s)&(f.shift(1)<=s.shift(1))); cross_dn=edge((f<s)&(f.shift(1)>=s.shift(1)))
        recent_up=cross_up.rolling(7,min_periods=1).max().astype(bool); recent_dn=cross_dn.rolling(7,min_periods=1).max().astype(bool)
        long=recent_up&(low<=f)&(close>f)&(f>s)&((f-s)/a>0.05)
        short=recent_dn&(high>=f)&(close<f)&(f<s)&((s-f)/a>0.05)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.15,3.2,36,"ma15_cross_first_pullback")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.15,3.2,36,"ma15_cross_first_pullback")

    elif variant_id == "ma15_slope_acceleration":
        f=ema(close,12); s=ema(close,26); spread=(f-s).div(a); accel=spread.diff(2)
        long=(spread>0.12)&(accel>0.025)&(close>f)&(f>s)&(segment_regime=="trend_up")
        short=(spread<-0.12)&(accel<-0.025)&(close<f)&(f<s)&(segment_regime=="trend_down")
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.25,3.3,40,"ma15_slope_acceleration")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.25,3.3,40,"ma15_slope_acceleration")

    elif variant_id == "vwap15_range_only_outer_reclaim":
        if segment_regime!="range": return signals, Counter({"REGIME_VETO":1})
        vw=rolling_vwap(frame,24); dev=close-vw; std=dev.rolling(24,min_periods=24).std(ddof=0)
        upper=vw+1.75*std; lower=vw-1.75*std
        long=(low<lower)&(close>lower)&(close>open_v); short=(high>upper)&(close<upper)&(close<open_v)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.0,2.8,24,"vwap15_outer_reclaim",finite(vw.iloc[int(i)],math.nan))
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.0,2.8,24,"vwap15_outer_reclaim",finite(vw.iloc[int(i)],math.nan))

    elif variant_id == "vwap15_session_anchor_reversion":
        vw=anchored_vwap(frame); slope=vw.diff(4).abs().div(4*a); dev=close-vw; std=dev.rolling(20,min_periods=20).std(ddof=0)
        compressed=a.div(a.rolling(30,min_periods=30).median())<1.05
        long=(low<vw-1.8*std)&(close>vw-1.8*std)&(slope<0.04)&compressed
        short=(high>vw+1.8*std)&(close<vw+1.8*std)&(slope<0.04)&compressed
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.0,2.6,20,"vwap15_session_anchor",finite(vw.iloc[int(i)],math.nan))
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.0,2.6,20,"vwap15_session_anchor",finite(vw.iloc[int(i)],math.nan))

    elif variant_id in {"neutral_grid5_cost_spaced_inventory_cap","neutral_grid5_volatility_scaled","grid15_context_5m_execution"}:
        if segment_regime!="range": return signals, Counter({"REGIME_VETO":1})
        h=ctx["ctx_high20"]; l=ctx["ctx_low20"]; width=h-l
        stable=(ctx["ctx_width_atr"].between(5.0,10.0))&(ctx["ctx_mid_slope"]<0.06)
        if variant_id=="neutral_grid5_cost_spaced_inventory_cap":
            fractions=(0.18,0.38,0.62,0.82)
        elif variant_id=="neutral_grid5_volatility_scaled":
            fractions=(0.20,0.40,0.60,0.80)
        else:
            fractions=(0.25,0.42,0.58,0.75)
        levels=[l+f*width for f in fractions]
        pairs=[(0,1,"long"),(1,2,"long"),(3,2,"short"),(2,1,"short")]
        for src,dst,side in pairs:
            cond=stable&((low<=levels[src])&(close>levels[src]) if side=="long" else (high>=levels[src])&(close<levels[src]))
            for ii in np.flatnonzero(edge(cond).to_numpy(bool)):
                i=int(ii); target=finite(levels[dst].iloc[i],math.nan)
                add(i,side,0.9,3.0,18,variant_id,target,f"L{src}->L{dst}")

    elif variant_id == "grid15_session_range_engine":
        if segment_regime!="range": return signals, Counter({"REGIME_VETO":1})
        look=12; rh=high.shift(1).rolling(look,min_periods=look).max(); rl=low.shift(1).rolling(look,min_periods=look).min(); w=rh-rl
        stable=(w/a).between(4.5,9.0)
        for f0,f1,side in ((0.2,0.4,"long"),(0.4,0.6,"long"),(0.8,0.6,"short"),(0.6,0.4,"short")):
            e=rl+f0*w; t=rl+f1*w
            cond=stable&((low<=e)&(close>e) if side=="long" else (high>=e)&(close<e))
            for ii in np.flatnonzero(edge(cond).to_numpy(bool)): add(int(ii),side,0.85,3.0,16,"grid15_session_range",finite(t.iloc[int(ii)],math.nan))

    elif variant_id == "ma5_as_15m_context_trigger":
        f=ema(close,9); s=ema(close,21)
        long_ctx=(ctx["ctx_close"]>ctx["ctx_ema20"])&(ctx["ctx_ema20"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0)
        short_ctx=(ctx["ctx_close"]<ctx["ctx_ema20"])&(ctx["ctx_ema20"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<0)
        long=long_ctx&(low<=f)&(close>f)&(f>s); short=short_ctx&(high>=f)&(close<f)&(f<s)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.0,3.2,24,"ma5_15m_context_pullback")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.0,3.2,24,"ma5_15m_context_pullback")

    elif variant_id == "ma5_donchian_confluence":
        f=ema(close,9); s=ema(close,21)
        long=(ctx["ctx_close"]>ctx["ctx_high20"])&(low<=f)&(close>f)&(f>s)
        short=(ctx["ctx_close"]<ctx["ctx_low20"])&(high>=f)&(close<f)&(f<s)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.0,3.3,24,"ma5_donchian_confluence")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.0,3.3,24,"ma5_donchian_confluence")

    elif variant_id in {"vwap5_with_15m_range_context","vwap5_failed_auction_reclaim"}:
        vw=rolling_vwap(frame,24); dev=close-vw; std=dev.rolling(24,min_periods=24).std(ddof=0)
        range_ctx=(ctx["ctx_width_atr"].between(4.0,10.0))&(ctx["ctx_mid_slope"]<0.08)
        if variant_id=="vwap5_with_15m_range_context":
            long=range_ctx&(low<vw-2.0*std)&(close>vw-2.0*std)&(segment_regime=="range")
            short=range_ctx&(high>vw+2.0*std)&(close<vw+2.0*std)&(segment_regime=="range")
        else:
            lower_wick=(np.minimum(open_v,close)-low).div(span)
            upper_wick=(high-np.maximum(open_v,close)).div(span)
            vol_contract=volume<volume.rolling(12,min_periods=12).median()
            long=range_ctx&(low<vw-1.7*std)&(close>vw-1.7*std)&(lower_wick>0.45)&vol_contract
            short=range_ctx&(high>vw+1.7*std)&(close<vw+1.7*std)&(upper_wick>0.45)&vol_contract
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",0.95,2.8,16,variant_id,finite(vw.iloc[int(i)],math.nan))
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",0.95,2.8,16,variant_id,finite(vw.iloc[int(i)],math.nan))

    elif variant_id in {"trend_grid15_context_5m_ladder","trend_grid15_breakout_retest_ladder","trend_grid5_donchian15_context","trend_grid5_impulse_retest"}:
        e20=ema(close,20)
        long_ctx=(ctx["ctx_close"]>ctx["ctx_ema50"])&(ctx["ctx_slope"]>0.01)
        short_ctx=(ctx["ctx_close"]<ctx["ctx_ema50"])&(ctx["ctx_slope"]<-0.01)
        if variant_id in {"trend_grid15_breakout_retest_ladder","trend_grid5_donchian15_context"}:
            long_ctx=long_ctx&(ctx["ctx_close"]>ctx["ctx_high20"])
            short_ctx=short_ctx&(ctx["ctx_close"]<ctx["ctx_low20"])
        if variant_id=="trend_grid5_impulse_retest":
            impulse_long=(span>=1.2*a)&(clv>0.7)&(vz>0)
            impulse_short=(span>=1.2*a)&(clv<0.3)&(vz>0)
            recent_l=impulse_long.rolling(4,min_periods=1).max().astype(bool)
            recent_s=impulse_short.rolling(4,min_periods=1).max().astype(bool)
            long=long_ctx&recent_l&(low<=e20)&(close>e20)
            short=short_ctx&recent_s&(high>=e20)&(close<e20)
        else:
            long=long_ctx&(low<=e20-0.35*a)&(close>e20)
            short=short_ctx&(high>=e20+0.35*a)&(close<e20)
        for i in np.flatnonzero(edge(long).to_numpy(bool)): add(int(i),"long",1.15,3.0,22,variant_id,level_id="L1")
        for i in np.flatnonzero(edge(short).to_numpy(bool)): add(int(i),"short",1.15,3.0,22,variant_id,level_id="L1")

    else:
        raise ValueError(f"VARIANT_UNSUPPORTED:{variant_id}")

    signals.sort(key=lambda r:(int(r["entry_bar_index"]),str(r["side"]),str(r.get("level_id") or ""),str(r["reason"])))
    return signals,rejected

def fold_metrics(helper: Any, trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[int,list[dict[str,Any]]] = defaultdict(list)
    for row in trades: grouped[int(row["fold"])].append(row)
    rows: dict[str,dict[str,Any]] = {}
    positive=0
    for fold in range(EXPECTED_FOLDS):
        m=helper.aggregate_trades(grouped.get(fold,[])); rows[str(fold)]=m
        if helper.finite_metric(m.get("net_pnl_sum_pct"))>0: positive+=1
    return {"rows":rows,"fold_count":EXPECTED_FOLDS,"positive_fold_count":positive,"positive_fold_ratio":positive/EXPECTED_FOLDS}

def cell_gate(helper: Any, cell: dict[str,Any]) -> dict[str,bool]:
    return {
        "trade_gate":int(cell.get("trade_count") or 0)>=MINIMUM_TRADES,
        "symbol_gate":len(cell.get("symbol_histogram") or {})>=MINIMUM_SYMBOLS,
        "profit_factor_gate":helper.finite_metric(cell.get("profit_factor"))>1.0,
        "expectancy_gate":helper.finite_metric(cell.get("expectancy_r"))>0.0,
        "net_pnl_gate":helper.finite_metric(cell.get("net_pnl_sum_pct"))>0.0,
        "walk_forward_gate":int((cell.get("fold_metrics") or {}).get("positive_fold_count") or 0)>=MINIMUM_POSITIVE_FOLDS,
    }

def risk_score(metrics: dict[str,Any]) -> float:
    exp=finite(metrics.get("expectancy_r"))
    pnl=finite(metrics.get("net_pnl_sum_pct"))
    dd=max(finite(metrics.get("max_drawdown_pct")),0.25)
    pf=max(finite(metrics.get("profit_factor")),0.0)
    folds=int((metrics.get("fold_metrics") or {}).get("positive_fold_count") or metrics.get("positive_fold_count") or 0)
    return exp + 0.20*(pnl/dd) + 0.10*(pf-1.0) + 0.03*folds

def self_test() -> int:
    assert len(VARIANT_IDS)==EXPECTED_BUNDLES
    assert len(EXECUTION_TIMEFRAME)==3
    size=360; x=np.arange(size,dtype=float)
    close=pd.Series(100+0.02*x+1.4*np.sin(x/8.0))
    open_v=close.shift(1).fillna(close.iloc[0])
    frame5=pd.DataFrame({"__timestamp":x*300000,"open":open_v,"high":pd.concat([close,open_v],axis=1).max(axis=1)+0.3,"low":pd.concat([close,open_v],axis=1).min(axis=1)-0.3,"close":close,"volume":100+(x%19)*4,"symbol":"TEST","timeframe":"5m"})
    frame15=frame5.iloc[::3].reset_index(drop=True).copy(); frame15["timeframe"]="15m"
    mask5=pd.Series([True]*len(frame5)); mask15=pd.Series([True]*len(frame15))
    for vid in sorted(VARIANT_IDS):
        frame=frame5 if EXECUTION_TIMEFRAME.get(vid, "5m" if "5" in vid else "15m")=="5m" else frame15
        mask=mask5 if len(frame)==len(frame5) else mask15
        sig,rej=generate_variant_signals(vid,frame,mask,frame15,"trend_up" if "grid" not in vid and "vwap" not in vid else "range",0.12)
        assert isinstance(sig,list) and isinstance(rej,Counter)
    print("STATE=PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_SELF_TEST")
    print("RC=0")
    return 0

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",default="/home/z/z")
    parser.add_argument("--target-sha",default="UNKNOWN")
    parser.add_argument("--raw-module")
    parser.add_argument("--helper-module")
    parser.add_argument("--benchmark-module")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test: return self_test()
    if not all([args.raw_module,args.helper_module,args.benchmark_module,args.a4d_contract]):
        raise SystemExit("--raw-module --helper-module --benchmark-module --a4d-contract required")
    root=Path(args.root).resolve()
    raw=import_module(Path(args.raw_module).resolve(),"r7a4d2_uplift_raw")
    helper=import_module(Path(args.helper_module).resolve(),"r7a4d2_uplift_helper")
    benchmark=import_module(Path(args.benchmark_module).resolve(),"r7a4d2_uplift_benchmark")
    contract=load_json(Path(args.a4d_contract).resolve())
    required=[root/PLAN_PATH,root/CALIBRATION_PATH,root/MANIFEST_PATH]
    missing=[str(p) for p in required if not p.is_file()]
    if missing:
        print("STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT")
        print("BLOCKER_COUNT=1"); print("BLOCKERS="+json.dumps(["REQUIRED_EVIDENCE_MISSING:"+",".join(missing)])); print("RC=2"); return 2
    plan=load_json(root/PLAN_PATH); calibration=load_json(root/CALIBRATION_PATH); manifest=load_json(root/MANIFEST_PATH)
    blockers:list[str]=[]
    if plan.get("state")!="PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN": blockers.append("UPLIFT_PLAN_NOT_PASS")
    bundles=[r for r in plan.get("uplift_rows",[]) if isinstance(r,dict)]
    if len(bundles)!=EXPECTED_BUNDLES: blockers.append(f"BUNDLE_COUNT_INVALID:{len(bundles)}")
    if {str(r.get("variant_id")) for r in bundles}!=VARIANT_IDS: blockers.append("VARIANT_SET_INVALID")
    segments={str(r["segment_id"]):r for r in manifest.get("selected_segments",[]) if isinstance(r,dict)}
    if len(segments)!=EXPECTED_SEGMENTS: blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    model=calibration.get("corrected_execution_model",{})
    costs=[r for r in model.get("profiles",[]) if isinstance(r,dict)]
    timings=[r for r in model.get("timing_perturbations",[]) if isinstance(r,dict)]
    if len(costs)*len(timings)!=EXPECTED_STRESS_PER_BUNDLE: blockers.append("STRESS_GRID_INVALID")
    base_cost_pct=base_round_trip_cost(calibration)
    if not math.isfinite(base_cost_pct) or base_cost_pct<=0: blockers.append("BASE_COST_INVALID")
    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132_INPUT")
        print("BLOCKER_COUNT="+str(len(blockers))); print("BLOCKERS="+json.dumps(blockers)); print("RC=2"); return 2

    source_sha={str(r.get("source_path")):str(r.get("source_sha256") or "") for r in manifest.get("selected_segments",[]) if isinstance(r,dict)}
    source_paths=sorted({str(r["source_path"]) for r in segments.values()})
    selected=[root/raw.safe_repo_path(p) for p in source_paths]
    protected=[Path(str(v)) for v in contract.get("protected_paths",[])]
    before=helper.snapshot(required+selected+protected)
    source_cache:dict[str,pd.DataFrame]={}; frame_cache:dict[tuple[str,str],pd.DataFrame]={}; mask_cache:dict[tuple[str,str],pd.Series]={}
    trade_rows:list[dict[str,Any]]=[]; cell_rows:list[dict[str,Any]]=[]; bundle_rows:list[dict[str,Any]]=[]
    for bundle_number,bundle in enumerate(sorted(bundles,key=lambda r:str(r["variant_id"])),1):
        vid=str(bundle["variant_id"]); source_lane=str(bundle["lane_id"])
        original_tf=source_lane.rsplit(":",1)[1]
        exec_tf=EXECUTION_TIMEFRAME.get(vid,original_tf)
        signal_cache:dict[str,list[dict[str,Any]]]={}; reject_total:Counter[str]=Counter()
        for segment_id,segment in sorted(segments.items()):
            sp=str(segment["source_path"])
            if sp not in source_cache: source_cache[sp]=raw.fixed_ohlcv_frame(root/raw.safe_repo_path(sp),source_sha[sp])
            for tf in {exec_tf,"15m"}:
                key=(segment_id,tf)
                if key not in frame_cache:
                    frame_cache[key]=raw.resample_for_segment(source_cache[sp],int(segment["start_row"]),int(segment["end_row_exclusive"]),tf)
                    mask_cache[key]=raw.measurement_mask(frame_cache[key],int(segment["start_row"]),int(segment["end_row_exclusive"]))
            sig,rej=generate_variant_signals(vid,frame_cache[(segment_id,exec_tf)],mask_cache[(segment_id,exec_tf)],frame_cache[(segment_id,"15m")],str(segment["regime"]),base_cost_pct)
            signal_cache[segment_id]=sig; reject_total.update(rej)
        cell_map:dict[tuple[str,str],dict[str,Any]]={}
        for cost in costs:
            for timing in timings:
                cell_trades:list[dict[str,Any]]=[]
                for segment_id,segment in sorted(segments.items()):
                    frame=frame_cache[(segment_id,exec_tf)]; measurement=mask_cache[(segment_id,exec_tf)]; last_exit=-1
                    for signal in signal_cache[segment_id]:
                        if int(signal["entry_bar_index"])<=last_exit: continue
                        trade=benchmark.simulate_trade(frame,measurement,signal,cost,timing,exec_tf)
                        if trade is None: continue
                        last_exit=int(trade["exit_index"])
                        trade.update({"variant_id":vid,"source_lane_id":source_lane,"execution_timeframe":exec_tf,"repair_class":bundle["repair_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"segment_id":segment_id,"fold":int(segment["fold"]),"regime":str(segment["regime"]),"symbol":str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or ""),"signal_reason":signal["reason"],"target_to_base_cost_ratio":signal["target_to_base_cost_ratio"],"risk_to_base_cost_ratio":signal["risk_to_base_cost_ratio"]})
                        cell_trades.append(trade); trade_rows.append(trade)
                metrics=helper.aggregate_trades(cell_trades); metrics.update({"variant_id":vid,"source_lane_id":source_lane,"execution_timeframe":exec_tf,"repair_class":bundle["repair_class"],"family":bundle["family"],"cost_profile_id":str(cost["id"]),"timing_id":str(timing["id"]),"fold_metrics":fold_metrics(helper,cell_trades)})
                metrics["gate_status"]=cell_gate(helper,metrics); metrics["economic_pass"]=all(metrics["gate_status"].values())
                cell_rows.append(metrics); cell_map[(str(cost["id"]),str(timing["id"]))]=metrics
        primary=[m for (cid,tid),m in cell_map.items() if cid in {"cost_profile_0","cost_profile_1"}]
        base=cell_map.get(("cost_profile_0","timing_0"),{})
        adverse=cell_map.get(("cost_profile_1","timing_1"),{})
        severe=cell_map.get(("cost_profile_2","timing_1"),{})
        positive_primary=sum(1 for m in primary if bool(m.get("economic_pass")))
        base_adverse=bool(base.get("economic_pass")) and bool(adverse.get("economic_pass"))
        baseline=bundle.get("baseline_metrics") or {}
        baseline_score=(risk_score((baseline.get("base") or {}))+risk_score((baseline.get("adverse") or {})))/2.0
        candidate_score=(risk_score(base)+risk_score(adverse))/2.0
        ref=plan.get("reference_metrics") or {}
        reference_score=(risk_score((ref.get("base") or {}))+risk_score((ref.get("adverse") or {})))/2.0
        uplift=base_adverse and positive_primary>=MINIMUM_POSITIVE_PRIMARY_CELLS and candidate_score>baseline_score
        reference_beat=uplift and candidate_score>reference_score
        bundle_rows.append({"variant_id":vid,"source_lane_id":source_lane,"execution_timeframe":exec_tf,"repair_class":bundle["repair_class"],"family":bundle["family"],"signal_count":sum(len(v) for v in signal_cache.values()),"rejection_histogram":dict(sorted(reject_total.items())),"positive_primary_cell_count":positive_primary,"base_and_adverse_positive":base_adverse,"baseline_risk_score":baseline_score,"candidate_risk_score":candidate_score,"reference_risk_score":reference_score,"uplift_discovery_pass":uplift,"reference_beating_discovery_pass":reference_beat,"base_metrics":base,"adverse_metrics":adverse,"severe_tail_metrics":severe})
        print(f"A4D2_REMAINING_11_UPLIFT_PROGRESS={bundle_number}/{EXPECTED_BUNDLES} CELLS={bundle_number*EXPECTED_STRESS_PER_BUNDLE}/{EXPECTED_CELLS} TRADES={len(trade_rows)}")

    lane_best:dict[str,dict[str,Any]]={}
    for row in bundle_rows:
        lid=str(row["source_lane_id"])
        if lid not in lane_best or finite(row["candidate_risk_score"],-1e9)>finite(lane_best[lid]["candidate_risk_score"],-1e9): lane_best[lid]=row
    uplifted=sorted([lid for lid,row in lane_best.items() if bool(row["uplift_discovery_pass"])])
    ref_beats=sorted([lid for lid,row in lane_best.items() if bool(row["reference_beating_discovery_pass"])])
    output=root/OUTPUT_DIR
    trade_count,trade_sha=atomic_jsonl(output/"uplift_trade_rows_v1.jsonl",trade_rows)
    cell_count,cell_sha=atomic_jsonl(output/"uplift_cell_rows_v1.jsonl",cell_rows)
    summary={"state":"PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132","target_sha":args.target_sha,"bundle_count":len(bundle_rows),"cell_result_count":cell_count,"trade_result_count":trade_count,"trade_sha256":trade_sha,"cell_sha256":cell_sha,"uplift_discovery_pass_bundle_count":sum(bool(r["uplift_discovery_pass"]) for r in bundle_rows),"reference_beating_bundle_count":sum(bool(r["reference_beating_discovery_pass"]) for r in bundle_rows),"uplifted_lane_count":len(uplifted),"uplifted_lane_ids":uplifted,"reference_beating_lane_count":len(ref_beats),"reference_beating_lane_ids":ref_beats,"lane_best_rows":[lane_best[k] for k in sorted(lane_best)],"mutation_rows":[],"next_stage":"R7.A4D2_EXCHANGE_BOT_V2_UPLIFT_DISJOINT_VALIDATION_AND_SECOND_WAVE_REPAIR" if uplifted else "R7.A4D2_EXCHANGE_BOT_V2_FEATURE_AND_DATA_EXPANSION_REDESIGN"}
    atomic_json(output/"remaining_11_lane_uplift_summary_v1.json",summary)
    after=helper.snapshot(required+selected+protected)
    mutations=helper.diff_snapshot(before,after)
    final_blockers=[]
    if cell_count!=EXPECTED_CELLS: final_blockers.append(f"CELL_COUNT_INVALID:{cell_count}")
    if mutations: final_blockers.append(f"PROTECTED_MUTATIONS:{len(mutations)}")
    if final_blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132")
        print("BLOCKER_COUNT="+str(len(final_blockers))); print("BLOCKERS="+json.dumps(final_blockers)); print("RC=2"); return 2
    print("STATE=PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132")
    print("BLOCKER_COUNT=0")
    print("REPAIR_BUNDLE_COUNT="+str(len(bundle_rows)))
    print("UPLIFT_CELL_RESULT_COUNT="+str(cell_count))
    print("UPLIFT_TRADE_RESULT_COUNT="+str(trade_count))
    print("UPLIFT_DISCOVERY_PASS_BUNDLE_COUNT="+str(summary["uplift_discovery_pass_bundle_count"]))
    print("REFERENCE_BEATING_BUNDLE_COUNT="+str(summary["reference_beating_bundle_count"]))
    print("UPLIFTED_LANE_COUNT="+str(len(uplifted)))
    print("UPLIFTED_LANE_IDS="+json.dumps(uplifted))
    print("REFERENCE_BEATING_LANE_COUNT="+str(len(ref_beats)))
    print("REFERENCE_BEATING_LANE_IDS="+json.dumps(ref_beats))
    print("LANE_BEST_ROWS="+json.dumps(summary["lane_best_rows"],sort_keys=True))
    print("SUMMARY_JSON="+str(output/"remaining_11_lane_uplift_summary_v1.json"))
    print("NEXT_STAGE="+summary["next_stage"])
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
