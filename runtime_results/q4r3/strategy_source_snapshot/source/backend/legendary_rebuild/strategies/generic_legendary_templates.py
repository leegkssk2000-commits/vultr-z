from __future__ import annotations

from typing import Any, Mapping, Optional
import pandas as pd

from .legendary_shared import (
    build_signal,
    body_ratio,
    close_location,
    ema,
    ensure_ohlcv,
    gate_signal,
    infer_regime,
    rsi,
    to_float,
    wick_ratios,
)

def _base(name, df, risk_action, market_context):
    df = ensure_ohlcv(df)
    if df.empty or len(df) < 120:
        return None, build_signal(name, None, "hold", 0, 0, 0, 0, "insufficient_bars", ["hold"], {})
    if str(risk_action).lower() in {"stop", "block", "risk_lock"}:
        px = to_float(df["close"].iloc[-1])
        return None, build_signal(name, None, "hold", px, px, px, 0, "risk_action_block", ["risk_block"], {})
    return infer_regime(df, market_context), None

def legendary_mean_reversion(name, df=None, state=None, risk_action="hold", config=None, market_context=None, **kwargs):
    ctx, early = _base(name, df, risk_action, market_context)
    if early: return early
    df = ensure_ohlcv(df)
    row, prev = df.iloc[-1], df.iloc[-2]
    price = to_float(row["close"])
    rsi_now = to_float(rsi(df["close"], 14).iloc[-1], 50)
    upper_wick, lower_wick = wick_ratios(row)
    in_range = ctx.regime == "range" or (ctx.adx <= 22 and abs(ctx.trend_slope_atr) < 0.30)

    ind = {
        "regime": ctx.regime, "htf_regime": ctx.htf_regime, "atr": round(ctx.atr, 6),
        "atr_pct": round(ctx.atr_pct, 6), "adx": round(ctx.adx, 6),
        "vwap": round(ctx.vwap, 6), "vwap_dev_atr": round(ctx.vwap_dev_atr, 6),
        "rsi": round(rsi_now, 6), "volume_z": round(ctx.volume_z, 6),
        "spread_bps": round(ctx.spread_bps, 6), "context_flags": list(ctx.context_flags)
    }

    if not in_range:
        return build_signal(name, None, "hold", price, price, price, 0, "range_regime_required", ["hold", "range_only"], ind)

    long_ok = ctx.vwap_dev_atr <= -1.15 and price > to_float(prev["close"]) and close_location(row) >= 0.55 and lower_wick >= 0.25 and rsi_now <= 43
    short_ok = ctx.vwap_dev_atr >= 1.15 and price < to_float(prev["close"]) and close_location(row) <= 0.45 and upper_wick >= 0.25 and rsi_now >= 57

    if long_ok:
        entry = price
        sl = min(to_float(row["low"]), price - 1.05 * ctx.atr)
        tp = min(ctx.vwap, entry + 2.2 * (entry - sl))
        sig = build_signal(name, "long", "enter", entry, sl, tp, 0.68 - ctx.data_penalty, "legendary_mean_reversion_long", ["mean_reversion", "range_only", "structure_stop", "legendary_family"], ind, size=0.08)
        return gate_signal(sig)

    if short_ok:
        entry = price
        sl = max(to_float(row["high"]), price + 1.05 * ctx.atr)
        tp = max(ctx.vwap, entry - 2.2 * (sl - entry))
        sig = build_signal(name, "short", "enter", entry, sl, tp, 0.65 - ctx.data_penalty, "legendary_mean_reversion_short", ["mean_reversion", "range_only", "structure_stop", "short_supported_lab", "legendary_family"], ind, size=0.05)
        return gate_signal(sig)

    return build_signal(name, None, "hold", price, price, price, 0, "no_legendary_mean_reversion_trigger", ["hold"], ind)

def legendary_trend_continuation(name, df=None, state=None, risk_action="hold", config=None, market_context=None, **kwargs):
    ctx, early = _base(name, df, risk_action, market_context)
    if early: return early
    df = ensure_ohlcv(df)
    close = df["close"]
    row, prev = df.iloc[-1], df.iloc[-2]
    price = to_float(row["close"])
    ema20 = to_float(ema(close, 20).iloc[-1])
    ema50 = to_float(ema(close, 50).iloc[-1])
    dist20 = abs(price - ema20) / max(ctx.atr, 1e-9)
    dist50 = abs(price - ema50) / max(ctx.atr, 1e-9)
    overextended = dist20 > 1.85 and dist50 > 2.60

    ind = {
        "regime": ctx.regime, "htf_regime": ctx.htf_regime, "atr": round(ctx.atr, 6),
        "adx": round(ctx.adx, 6), "ema20": round(ema20, 6), "ema50": round(ema50, 6),
        "ema200": round(ctx.ema200, 6), "trend_slope_atr": round(ctx.trend_slope_atr, 6),
        "dist_ema20_atr": round(dist20, 6), "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags)
    }

    if overextended:
        return build_signal(name, None, "hold", price, price, price, 0, "late_chase_blocked", ["hold", "no_late_chase"], ind)

    long_ok = ctx.htf_regime == "trend_up" and ctx.regime in {"trend_up", "mixed"} and to_float(row["low"]) <= ema20 + 0.35 * ctx.atr and price > ema20 and close_location(row) >= 0.58 and body_ratio(row) >= 0.25
    short_ok = ctx.htf_regime == "trend_down" and ctx.regime in {"trend_down", "mixed"} and to_float(row["high"]) >= ema20 - 0.35 * ctx.atr and price < ema20 and close_location(row) <= 0.42 and body_ratio(row) >= 0.25

    if long_ok:
        entry = price
        sl = min(to_float(df["low"].tail(10).min()), ema50 - 0.45 * ctx.atr)
        tp = entry + 2.4 * (entry - sl)
        sig = build_signal(name, "long", "enter", entry, sl, tp, 0.70 - ctx.data_penalty, "legendary_trend_pullback_long", ["trend", "htf_alignment", "pullback_reclaim", "no_late_chase", "structure_stop"], ind, size=0.10, pyramiding=1)
        return gate_signal(sig, min_rr=1.65)

    if short_ok:
        entry = price
        sl = max(to_float(df["high"].tail(10).max()), ema50 + 0.45 * ctx.atr)
        tp = entry - 2.4 * (sl - entry)
        sig = build_signal(name, "short", "enter", entry, sl, tp, 0.66 - ctx.data_penalty, "legendary_trend_pullback_short", ["trend", "htf_alignment", "pullback_reclaim", "no_late_chase", "structure_stop", "short_supported_lab"], ind, size=0.05, pyramiding=1)
        return gate_signal(sig, min_rr=1.65)

    return build_signal(name, None, "hold", price, price, price, 0, "no_legendary_trend_trigger", ["hold"], ind)

def legendary_liquidity_reclaim(name, df=None, state=None, risk_action="hold", config=None, market_context=None, **kwargs):
    ctx, early = _base(name, df, risk_action, market_context)
    if early: return early
    df = ensure_ohlcv(df)
    row = df.iloc[-1]
    price = to_float(row["close"])
    lookback = df.iloc[-31:-1]
    prior_high = to_float(lookback["high"].max())
    prior_low = to_float(lookback["low"].min())
    upper_wick, lower_wick = wick_ratios(row)
    rsi_now = to_float(rsi(df["close"], 14).iloc[-1], 50)

    swept_high = to_float(row["high"]) > prior_high + 0.05 * ctx.atr
    swept_low = to_float(row["low"]) < prior_low - 0.05 * ctx.atr
    allowed = ctx.regime in {"range", "squeeze", "mixed"} or ctx.adx <= 26

    ind = {
        "regime": ctx.regime, "htf_regime": ctx.htf_regime, "atr": round(ctx.atr, 6),
        "adx": round(ctx.adx, 6), "volume_z": round(ctx.volume_z, 6),
        "prior_high": round(prior_high, 6), "prior_low": round(prior_low, 6),
        "swept_high": swept_high, "swept_low": swept_low,
        "rsi": round(rsi_now, 6), "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags)
    }

    if not allowed:
        return build_signal(name, None, "hold", price, price, price, 0, "bad_regime_for_liquidity_reclaim", ["hold", "regime_block"], ind)

    long_ok = swept_low and price > prior_low and close_location(row) >= 0.57 and lower_wick >= 0.30 and rsi_now <= 46
    short_ok = swept_high and price < prior_high and close_location(row) <= 0.43 and upper_wick >= 0.30 and rsi_now >= 54

    if long_ok:
        entry = price
        sl = min(to_float(row["low"]) - 0.10 * ctx.atr, prior_low - 0.15 * ctx.atr)
        tp = entry + 2.4 * (entry - sl)
        sig = build_signal(name, "long", "enter", entry, sl, tp, 0.72 - ctx.data_penalty, "legendary_sellside_sweep_reclaim", ["liquidity", "sellside_sweep", "reclaim", "structure_stop"], ind, size=0.09)
        return gate_signal(sig, min_rr=1.65)

    if short_ok:
        entry = price
        sl = max(to_float(row["high"]) + 0.10 * ctx.atr, prior_high + 0.15 * ctx.atr)
        tp = entry - 2.4 * (sl - entry)
        sig = build_signal(name, "short", "enter", entry, sl, tp, 0.68 - ctx.data_penalty, "legendary_buyside_sweep_reclaim", ["liquidity", "buyside_sweep", "reclaim", "structure_stop", "short_supported_lab"], ind, size=0.05)
        return gate_signal(sig, min_rr=1.65)

    return build_signal(name, None, "hold", price, price, price, 0, "no_legendary_liquidity_trigger", ["hold"], ind)

def legendary_breakout(name, df=None, state=None, risk_action="hold", config=None, market_context=None, **kwargs):
    ctx, early = _base(name, df, risk_action, market_context)
    if early: return early
    df = ensure_ohlcv(df)
    row, prev = df.iloc[-1], df.iloc[-2]
    price = to_float(row["close"])
    prior = df.iloc[-31:-1]
    prior_high = to_float(prior["high"].max())
    prior_low = to_float(prior["low"].min())
    body = body_ratio(row)
    cl = close_location(row)
    allowed = ctx.regime in {"squeeze", "mixed", "breakout"} or (ctx.adx >= 18 and ctx.volume_z >= 0.8)

    ind = {
        "regime": ctx.regime, "htf_regime": ctx.htf_regime, "atr": round(ctx.atr, 6),
        "adx": round(ctx.adx, 6), "volume_z": round(ctx.volume_z, 6),
        "prior_high": round(prior_high, 6), "prior_low": round(prior_low, 6),
        "body_ratio": round(body, 6), "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags)
    }

    if not allowed:
        return build_signal(name, None, "hold", price, price, price, 0, "breakout_regime_required", ["hold", "regime_block"], ind)

    long_ok = price > prior_high + 0.10 * ctx.atr and cl >= 0.62 and body >= 0.30 and ctx.volume_z >= 0.5
    short_ok = price < prior_low - 0.10 * ctx.atr and cl <= 0.38 and body >= 0.30 and ctx.volume_z >= 0.5

    if long_ok:
        entry = price
        sl = max(prior_high - 0.50 * ctx.atr, entry - 1.25 * ctx.atr)
        tp = entry + 2.3 * (entry - sl)
        sig = build_signal(name, "long", "enter", entry, sl, tp, 0.68 - ctx.data_penalty, "legendary_breakout_long", ["breakout", "structure_stop", "volume_confirmed"], ind, size=0.08)
        return gate_signal(sig, min_rr=1.55)

    if short_ok:
        entry = price
        sl = min(prior_low + 0.50 * ctx.atr, entry + 1.25 * ctx.atr)
        tp = entry - 2.3 * (sl - entry)
        sig = build_signal(name, "short", "enter", entry, sl, tp, 0.64 - ctx.data_penalty, "legendary_breakout_short", ["breakout", "structure_stop", "volume_confirmed", "short_supported_lab"], ind, size=0.05)
        return gate_signal(sig, min_rr=1.55)

    return build_signal(name, None, "hold", price, price, price, 0, "no_legendary_breakout_trigger", ["hold"], ind)

def legendary_meta_hold(name, df=None, state=None, risk_action="hold", config=None, market_context=None, **kwargs):
    df = ensure_ohlcv(df)
    price = to_float(df["close"].iloc[-1]) if not df.empty else 0.0
    return build_signal(name, None, "hold", price, price, price, 0, "meta_router_not_standalone_entry", ["hold", "meta_not_entry"], {})
