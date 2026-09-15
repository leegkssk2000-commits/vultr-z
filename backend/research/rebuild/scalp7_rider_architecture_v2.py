"""Frozen causal 15m impulse / pullback / reclaim architecture.

This emits research signals and lifecycle instructions only, never orders.
Outcome labels from the saved-parent anatomy are never imported here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

IDENTITY = "scalp7_rider_15m_impulse_pullback_reclaim_v2"
LANE = "trend_rider"
TIMEFRAME_MIN = 15
TIMEFRAME_MS = 900_000
CONTEXT_BARS = 4
SETUP_TTL_BARS = 8
MAX_HOLD_BARS = 36


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "open",
        "high",
        "low",
        "close",
        "segment_id",
    }
    if not required.issubset(frame.columns):
        raise ValueError("RIDER_BAR_SCHEMA_INCOMPLETE")
    x = frame.copy().reset_index(drop=True)
    if x.empty:
        return x
    if (
        not x["open_ts_ms"].is_monotonic_increasing
        or x["open_ts_ms"].duplicated().any()
    ):
        raise ValueError("RIDER_BAR_ORDER_INVALID")
    for _, r in x.iterrows():
        opening = int(r["open_ts_ms"])
        closing = int(r["close_ts_ms"])
        if opening % TIMEFRAME_MS or closing != opening + TIMEFRAME_MS:
            raise ValueError("RIDER_UTC_15M_REQUIRED")
        if int(r["available_ts_ms"]) < closing:
            raise ValueError("RIDER_PREMATURE_BAR_AVAILABILITY")
        prices = [float(r[k]) for k in ("open", "high", "low", "close")]
        if any(not pd.notna(v) or abs(v) == float("inf") or v <= 0 for v in prices):
            raise ValueError("RIDER_INVALID_PRICE")
        if not (
            prices[2]
            <= min(prices[0], prices[3])
            <= max(prices[0], prices[3])
            <= prices[1]
        ):
            raise ValueError("RIDER_INVALID_CANDLE_GEOMETRY")
        if pd.isna(r["segment_id"]):
            raise ValueError("RIDER_SEGMENT_REQUIRED")
    return x


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Read completed chronological bars; no fill price or future bar is read."""
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        x = _validate(frames[symbol])
        state: dict[str, Any] | None = None
        segment_start = 0
        for i in range(len(x)):
            bar = x.iloc[i]
            if i and (
                bar["segment_id"] != x.iloc[i - 1]["segment_id"]
                or int(bar["open_ts_ms"]) != int(x.iloc[i - 1]["close_ts_ms"])
                or int(x.iloc[i - 1]["available_ts_ms"]) > int(bar["close_ts_ms"])
            ):
                state = None
                segment_start = i
            if i - segment_start < CONTEXT_BARS:
                continue
            previous = x.iloc[i - 1]
            if state is not None:
                side = int(state["side"])
                broken = (
                    float(bar["low"]) <= state["origin"]
                    if side == 1
                    else float(bar["high"]) >= state["origin"]
                )
                if broken or i - int(state["impulse_index"]) > SETUP_TTL_BARS:
                    state = None
            if state is None:
                context = x.iloc[i - CONTEXT_BARS : i]
                high = float(context["high"].max())
                low = float(context["low"].min())
                close = float(bar["close"])
                side = 1 if close > high else -1 if close < low else 0
                if side:
                    state = {
                        "side": side,
                        "stage": "IMPULSE",
                        "impulse_index": i,
                        "impulse_open_ts_ms": int(bar["open_ts_ms"]),
                        "origin": low if side == 1 else high,
                        "level": high if side == 1 else low,
                    }
                continue
            side = int(state["side"])
            if state["stage"] == "IMPULSE":
                pullback = (
                    float(bar["low"]) < float(previous["low"])
                    and float(bar["close"]) < float(previous["close"])
                    if side == 1
                    else float(bar["high"]) > float(previous["high"])
                    and float(bar["close"]) > float(previous["close"])
                )
                if pullback:
                    state.update(
                        {
                            "stage": "PULLBACK",
                            "pullback_index": i,
                            "pullback_open_ts_ms": int(bar["open_ts_ms"]),
                            "extreme": float(bar["low"] if side == 1 else bar["high"]),
                            "reclaim": float(bar["high"] if side == 1 else bar["low"]),
                        }
                    )
                continue
            extreme = (
                min(float(state["extreme"]), float(bar["low"]))
                if side == 1
                else max(float(state["extreme"]), float(bar["high"]))
            )
            reclaim = (
                float(bar["close"]) > float(state["reclaim"])
                if side == 1
                else float(bar["close"]) < float(state["reclaim"])
            )
            if reclaim:
                signals.append(
                    {
                        "identity": IDENTITY,
                        "lane": LANE,
                        "timeframe_min": TIMEFRAME_MIN,
                        "symbol": symbol,
                        "side": side,
                        "signal_open_ts_ms": int(bar["open_ts_ms"]),
                        "signal_ts_ms": max(
                            int(bar["close_ts_ms"]), int(bar["available_ts_ms"])
                        ),
                        "segment_id": bar["segment_id"],
                        "stop_price": extreme,
                        "max_hold_bars": MAX_HOLD_BARS,
                        "take_profit_r": None,
                        "invalidation_price": extreme,
                        "exit_policy": "RIDER_CONFIRMED_SWING",
                        "meta": {
                            "grammar": ["IMPULSE", "COUNTERTREND_PULLBACK", "RECLAIM"],
                            "impulse_open_ts_ms": state["impulse_open_ts_ms"],
                            "pullback_open_ts_ms": state["pullback_open_ts_ms"],
                            "origin": state["origin"],
                            "impulse_break_level": state["level"],
                            "reclaim_level": state["reclaim"],
                            "feature_available_ts_ms": int(bar["available_ts_ms"]),
                        },
                    }
                )
                state = None
            else:
                state["extreme"] = extreme
                state["reclaim"] = float(bar["high"] if side == 1 else bar["low"])
    return sorted(signals, key=lambda r: (r["signal_ts_ms"], r["symbol"]))


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    """A confirmed pullback pivot protects the next bar, never the current one."""
    result: dict[str, Any] = {"exit_next_open": False, "reason": "RIDER_STRUCTURE_HOLD"}
    if len(history) < 3:
        return result
    left, pivot, right = (history.iloc[-3], history.iloc[-2], history.iloc[-1])
    if int(right["close_ts_ms"]) != int(bar["close_ts_ms"]):
        raise ValueError("RIDER_LIFECYCLE_PREFIX_MISMATCH")
    if any(
        int(r["close_ts_ms"]) > int(bar["close_ts_ms"]) for r in (left, pivot, right)
    ):
        raise ValueError("RIDER_LIFECYCLE_FUTURE_BAR")
    if (
        int(pivot["open_ts_ms"]) < int(position["entry_ts_ms"])
        or left["segment_id"] != pivot["segment_id"]
        or pivot["segment_id"] != right["segment_id"]
        or int(left["close_ts_ms"]) != int(pivot["open_ts_ms"])
        or int(pivot["close_ts_ms"]) != int(right["open_ts_ms"])
    ):
        return result
    decision_available = int(bar["available_ts_ms"])
    if any(
        int(r["available_ts_ms"]) > decision_available for r in (left, pivot, right)
    ):
        return {"exit_next_open": False, "reason": "RIDER_PIVOT_NOT_AVAILABLE_HOLD"}
    side = int(position["side"])
    current = float(position["stop_price"])
    if side == 1:
        level = float(pivot["low"])
        confirmed = (
            level < float(left["low"])
            and level <= float(right["low"])
            and float(right["close"]) > float(pivot["high"])
            and current < level < float(right["close"])
        )
    elif side == -1:
        level = float(pivot["high"])
        confirmed = (
            level > float(left["high"])
            and level >= float(right["high"])
            and float(right["close"]) < float(pivot["low"])
            and current > level > float(right["close"])
        )
    else:
        raise ValueError("RIDER_SIDE_INVALID")
    if confirmed:
        result.update({"next_stop": level, "reason": "RIDER_CONFIRMED_PULLBACK_PIVOT"})
    return result
