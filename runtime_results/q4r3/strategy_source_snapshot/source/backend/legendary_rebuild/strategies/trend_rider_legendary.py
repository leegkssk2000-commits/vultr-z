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
    to_float,
)


def _swing_low(df: pd.DataFrame, n: int = 8) -> float:
    return to_float(df["low"].tail(n).min())


def _swing_high(df: pd.DataFrame, n: int = 8) -> float:
    return to_float(df["high"].tail(n).max())


def strategy(
    df: Optional[pd.DataFrame] = None,
    state: Optional[Mapping[str, Any]] = None,
    risk_action: str = "hold",
    config: Any = None,
    market_context: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> dict:
    name = "trend_rider_legendary"
    df = ensure_ohlcv(df)
    if df.empty or len(df) < 220:
        return build_signal(name, None, "hold", 0, 0, 0, 0, "insufficient_htf_bars", ["hold"], {})

    if str(risk_action).lower() in {"stop", "block", "risk_lock"}:
        px = to_float(df["close"].iloc[-1])
        return build_signal(name, None, "hold", px, px, px, 0, "risk_action_block", ["risk_block"], {})

    ctx = infer_regime(df, market_context)
    close = df["close"]
    price = to_float(close.iloc[-1])
    row = df.iloc[-1]
    prev = df.iloc[-2]
    ema20_now = to_float(ema(close, 20).iloc[-1])
    ema50_now = to_float(ema(close, 50).iloc[-1])

    dist_ema20_atr = abs(price - ema20_now) / max(ctx.atr, 1e-9)
    dist_ema50_atr = abs(price - ema50_now) / max(ctx.atr, 1e-9)

    pullback_long = to_float(row["low"]) <= ema20_now + 0.35 * ctx.atr and price > ema20_now
    pullback_short = to_float(row["high"]) >= ema20_now - 0.35 * ctx.atr and price < ema20_now

    reclaim_long = pullback_long and price > to_float(prev["high"]) - 0.15 * ctx.atr and close_location(row) >= 0.58 and body_ratio(row) >= 0.28
    reclaim_short = pullback_short and price < to_float(prev["low"]) + 0.15 * ctx.atr and close_location(row) <= 0.42 and body_ratio(row) >= 0.28

    overextended = dist_ema20_atr > 1.85 and dist_ema50_atr > 2.60

    indicators = {
        "regime": ctx.regime,
        "htf_regime": ctx.htf_regime,
        "atr": round(ctx.atr, 6),
        "atr_pct": round(ctx.atr_pct, 6),
        "adx": round(ctx.adx, 6),
        "ema20": round(ema20_now, 6),
        "ema50": round(ema50_now, 6),
        "ema200": round(ctx.ema200, 6),
        "trend_slope_atr": round(ctx.trend_slope_atr, 6),
        "dist_ema20_atr": round(dist_ema20_atr, 6),
        "dist_ema50_atr": round(dist_ema50_atr, 6),
        "volume_z": round(ctx.volume_z, 6),
        "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags),
    }

    if overextended:
        return build_signal(name, None, "hold", price, price, price, 0, "late_chase_blocked", ["hold", "no_late_chase"], indicators)

    if ctx.htf_regime == "trend_up" and ctx.regime in {"trend_up", "mixed"} and reclaim_long:
        entry = price
        sl = min(_swing_low(df, 10), ema50_now - 0.45 * ctx.atr)
        tp = entry + 2.4 * (entry - sl)
        conf = 0.72 - ctx.data_penalty + min(ctx.adx / 200.0, 0.08)
        sig = build_signal(
            name, "long", "enter", entry, sl, tp, conf,
            "htf_trend_up_pullback_reclaim",
            ["trend", "htf_alignment", "pullback_reclaim", "no_late_chase", "structure_stop"],
            indicators,
            size=0.12,
            pyramiding=1,
        )
        return gate_signal(sig, min_rr=1.65)

    if ctx.htf_regime == "trend_down" and ctx.regime in {"trend_down", "mixed"} and reclaim_short:
        entry = price
        sl = max(_swing_high(df, 10), ema50_now + 0.45 * ctx.atr)
        tp = entry - 2.4 * (sl - entry)
        conf = 0.68 - ctx.data_penalty + min(ctx.adx / 200.0, 0.08)
        sig = build_signal(
            name, "short", "enter", entry, sl, tp, conf,
            "htf_trend_down_pullback_reclaim",
            ["trend", "htf_alignment", "pullback_reclaim", "no_late_chase", "structure_stop", "short_supported_lab"],
            indicators,
            size=0.07,
            pyramiding=1,
        )
        return gate_signal(sig, min_rr=1.65)

    return build_signal(name, None, "hold", price, price, price, 0, "trend_rider_no_legendary_trigger", ["hold"], indicators)
