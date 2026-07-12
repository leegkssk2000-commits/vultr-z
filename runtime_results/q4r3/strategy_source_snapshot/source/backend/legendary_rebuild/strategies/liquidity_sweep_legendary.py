from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd

from .legendary_shared import (
    build_signal,
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
    name = "liquidity_sweep_legendary"
    df = ensure_ohlcv(df)
    if df.empty or len(df) < 100:
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

    lookback = df.iloc[-31:-1]
    prior_high = to_float(lookback["high"].max())
    prior_low = to_float(lookback["low"].min())
    upper_wick, lower_wick = wick_ratios(row)

    swept_high = to_float(row["high"]) > prior_high + 0.05 * atr_now
    swept_low = to_float(row["low"]) < prior_low - 0.05 * atr_now

    reclaim_short = swept_high and price < prior_high and close_location(row) <= 0.43 and upper_wick >= 0.30 and rsi_now >= 55.0
    reclaim_long = swept_low and price > prior_low and close_location(row) >= 0.57 and lower_wick >= 0.30 and rsi_now <= 45.0

    allowed_regime = ctx.regime in {"range", "squeeze", "mixed"} or ctx.adx <= 26.0

    indicators = {
        "regime": ctx.regime,
        "htf_regime": ctx.htf_regime,
        "atr": round(atr_now, 6),
        "atr_pct": round(ctx.atr_pct, 6),
        "adx": round(ctx.adx, 6),
        "volume_z": round(ctx.volume_z, 6),
        "prior_high": round(prior_high, 6),
        "prior_low": round(prior_low, 6),
        "swept_high": swept_high,
        "swept_low": swept_low,
        "rsi": round(rsi_now, 6),
        "spread_bps": round(ctx.spread_bps, 6),
        "context_flags": list(ctx.context_flags),
    }

    if not allowed_regime:
        return build_signal(name, None, "hold", price, price, price, 0, "bad_regime_for_sweep_reclaim", ["hold", "regime_block"], indicators)

    if reclaim_long:
        entry = price
        sl = min(to_float(row["low"]) - 0.10 * atr_now, prior_low - 0.15 * atr_now)
        tp = entry + 2.4 * (entry - sl)
        conf = 0.74 - ctx.data_penalty + min(max(ctx.volume_z, 0.0) * 0.03, 0.08)
        sig = build_signal(
            name, "long", "enter", entry, sl, tp, conf,
            "sellside_liquidity_sweep_reclaim",
            ["liquidity", "sellside_sweep", "reclaim", "structure_stop"],
            indicators,
            size=0.11,
            pyramiding=0,
        )
        return gate_signal(sig, min_rr=1.65)

    if reclaim_short:
        entry = price
        sl = max(to_float(row["high"]) + 0.10 * atr_now, prior_high + 0.15 * atr_now)
        tp = entry - 2.4 * (sl - entry)
        conf = 0.70 - ctx.data_penalty + min(max(ctx.volume_z, 0.0) * 0.03, 0.08)
        sig = build_signal(
            name, "short", "enter", entry, sl, tp, conf,
            "buyside_liquidity_sweep_reclaim",
            ["liquidity", "buyside_sweep", "reclaim", "structure_stop", "short_supported_lab"],
            indicators,
            size=0.07,
            pyramiding=0,
        )
        return gate_signal(sig, min_rr=1.65)

    why = "liquidity_sweep_no_legendary_trigger"
    if swept_high or swept_low:
        why = "sweep_without_reclaim"
    return build_signal(name, None, "hold", price, price, price, 0, why, ["hold"], indicators)
