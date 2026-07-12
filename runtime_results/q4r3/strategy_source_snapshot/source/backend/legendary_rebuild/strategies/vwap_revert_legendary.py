from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd

from .legendary_shared import (
    build_signal,
    body_ratio,
    close_location,
    ensure_ohlcv,
    gate_signal,
    infer_regime,
    rsi,
    to_float,
    wick_ratios,
)


def strategy(
    df: Optional[pd.DataFrame] = None,
    state: Optional[Mapping[str, Any]] = None,
    risk_action: str = "hold",
    config: Any = None,
    market_context: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> dict:
    name = "vwap_revert_legendary"
    df = ensure_ohlcv(df)
    if df.empty or len(df) < 120:
        return build_signal(name, None, "hold", 0, 0, 0, 0, "insufficient_bars", ["hold"], {})

    if str(risk_action).lower() in {"stop", "block", "risk_lock"}:
        px = to_float(df["close"].iloc[-1])
        return build_signal(name, None, "hold", px, px, px, 0, "risk_action_block", ["risk_block"], {})

    ctx = infer_regime(df, market_context)
    row = df.iloc[-1]
    prev = df.iloc[-2]
    price = to_float(row["close"])
    atr_now = ctx.atr
    rsi_now = to_float(rsi(df["close"], 14).iloc[-1], 50.0)
    upper_wick, lower_wick = wick_ratios(row)

    in_range = ctx.regime == "range" or (ctx.adx <= 22.0 and abs(ctx.trend_slope_atr) < 0.30)
    long_extension = ctx.vwap_dev_atr <= -1.20
    short_extension = ctx.vwap_dev_atr >= 1.20

    long_reclaim = (
        long_extension
        and price > to_float(prev["close"])
        and close_location(row) >= 0.55
        and lower_wick >= 0.28
        and rsi_now <= 42.0
    )
    short_reclaim = (
        short_extension
        and price < to_float(prev["close"])
        and close_location(row) <= 0.45
        and upper_wick >= 0.28
        and rsi_now >= 58.0
    )

    indicators = {
        "regime": ctx.regime,
        "htf_regime": ctx.htf_regime,
        "atr": round(atr_now, 6),
        "atr_pct": round(ctx.atr_pct, 6),
        "adx": round(ctx.adx, 6),
        "vwap": round(ctx.vwap, 6),
        "vwap_dev_atr": round(ctx.vwap_dev_atr, 6),
        "rsi": round(rsi_now, 6),
        "volume_z": round(ctx.volume_z, 6),
        "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags),
    }

    if not in_range:
        return build_signal(name, None, "hold", price, price, price, 0, "range_regime_required", ["hold", "range_only"], indicators)

    if long_reclaim:
        entry = price
        sl = min(to_float(row["low"]), price - 1.05 * atr_now)
        tp = min(ctx.vwap, entry + 2.2 * (entry - sl))
        conf = 0.70 - ctx.data_penalty + min(abs(ctx.vwap_dev_atr) * 0.03, 0.08)
        sig = build_signal(
            name, "long", "enter", entry, sl, tp, conf,
            "range_vwap_lower_extension_reclaim",
            ["vwap", "mean_reversion", "range_only", "lower_reclaim", "structure_stop"],
            indicators,
            size=0.10,
            pyramiding=0,
        )
        return gate_signal(sig)

    if short_reclaim:
        entry = price
        sl = max(to_float(row["high"]), price + 1.05 * atr_now)
        tp = max(ctx.vwap, entry - 2.2 * (sl - entry))
        conf = 0.66 - ctx.data_penalty + min(abs(ctx.vwap_dev_atr) * 0.03, 0.08)
        sig = build_signal(
            name, "short", "enter", entry, sl, tp, conf,
            "range_vwap_upper_extension_reclaim",
            ["vwap", "mean_reversion", "range_only", "upper_reclaim", "structure_stop", "short_supported_lab"],
            indicators,
            size=0.06,
            pyramiding=0,
        )
        return gate_signal(sig)

    why = "vwap_revert_no_legendary_trigger"
    if long_extension or short_extension:
        why = "extension_without_reclaim"
    return build_signal(name, None, "hold", price, price, price, 0, why, ["hold"], indicators)
