"""Frozen30m confirmed-box rotation; research signals, never orders.

The complete deterministic rule is a ZEL adaptation, not an Al Brooks replica.
Execution/fees/gap ownership remain in unchanged scalp7_execution_v2.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as execution

SPEC = json.loads(Path(__file__).with_name("SPEC.json").read_text())
IDENTITY = SPEC["identity"]
TIMEFRAME_MIN = SPEC["timeframe_min"]
LANE = "fixed_confirmed_box_rotation"
P = SPEC["parameters"]


def _confirmed_box(rows: list[dict[str, Any]]) -> tuple[float, float] | None:
    low = min(float(b["low"]) for b in rows)
    high = max(float(b["high"]) for b in rows)
    width = high - low
    if width <= 0:
        return None
    lower, upper = [], []
    for i, bar in enumerate(rows):
        near_low = float(bar["low"]) <= low + P["edge_test_width_fraction"] * width
        near_high = float(bar["high"]) >= high - P["edge_test_width_fraction"] * width
        # A whole-range candle cannot confirm either independent edge test.
        if near_low and not near_high:
            lower.append(i)
        if near_high and not near_low:
            upper.append(i)
    separation = P["minimum_test_separation_bars"]
    if len(lower) < 2 or len(upper) < 2:
        return None
    if lower[-1] - lower[0] < separation or upper[-1] - upper[0] < separation:
        return None
    if lower[-1] <= upper[0] or upper[-1] <= lower[0]:
        return None
    return low, high


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        rows, _ = execution._frame_records(frames[symbol], TIMEFRAME_MIN)
        if any(pd.isna(r["segment_id"]) or not str(r["segment_id"]).strip() for r in rows):
            raise ValueError("BOX_SEGMENT_REQUIRED")
        first_eligible = 0
        state: dict[str, Any] | None = None
        for i, bar in enumerate(rows):
            timely = int(bar["available_ts_ms"]) == int(bar["close_ts_ms"])
            follows = not i or execution._can_follow(rows[i - 1], bar)
            if not follows or not timely:
                state = None
                first_eligible = i if timely else i + 1
            if not timely:
                continue
            if state is None:
                count = P["formation_bars"]
                if i - first_eligible + 1 < count:
                    continue
                box = _confirmed_box(rows[i - count + 1:i + 1])
                if box is not None:
                    state = {"low": box[0], "high": box[1], "index": i,
                             "formed_at_ms": int(bar["close_ts_ms"]),
                             "start_open_ms": int(rows[i - count + 1]["open_ts_ms"])}
                continue
            low, high = state["low"], state["high"]
            width = high - low
            if (i - state["index"] > P["setup_ttl_bars"]
                    or float(bar["low"]) < low or float(bar["high"]) > high):
                state = None
                first_eligible = i + 1
                continue
            midpoint = low + P["target_width_fraction"] * width
            close = float(bar["close"])
            if (float(bar["low"]) <= low + P["entry_edge_fraction"] * width
                    and close > float(bar["open"])
                    and close > float(rows[i - 1]["close"])
                    and low + P["entry_close_min_fraction"] * width <= close < midpoint):
                signals.append({
                    "identity": IDENTITY, "lane": LANE, "symbol": symbol,
                    "timeframe_min": TIMEFRAME_MIN, "side": 1,
                    "signal_open_ts_ms": int(bar["open_ts_ms"]),
                    "signal_ts_ms": int(bar["close_ts_ms"]),
                    "segment_id": bar["segment_id"], "stop_price": low,
                    "max_hold_bars": P["max_hold_bars"], "take_profit_r": None,
                    "meta": {"box_low": low, "box_high": high, "target_price": midpoint,
                             "formation_start_open_ts_ms": state["start_open_ms"],
                             "box_available_ts_ms": state["formed_at_ms"],
                             "feature_available_ts_ms": int(bar["available_ts_ms"]),
                             "source_exact": False,
                             "rule_origin": "ZEL_INTERNAL_ADAPTATION"},
                })
                state = None
                first_eligible = i + 1
    return sorted(signals, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def entry_update(signal: dict[str, Any], entry: float) -> dict[str, Any]:
    """Only actual next-open entry and already frozen geometry are inspected."""
    if entry <= float(signal["stop_price"]):
        return {"reject": True, "reason": "BOX_ENTRY_AT_OR_BELOW_FLOOR"}
    if entry >= float(signal["meta"]["target_price"]):
        return {"reject": True, "reason": "BOX_ENTRY_AT_OR_ABOVE_CENTER"}
    return {}


def exit_update(position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame) -> dict[str, Any]:
    if history.empty or int(history.iloc[-1]["close_ts_ms"]) != int(bar["close_ts_ms"]):
        raise ValueError("BOX_EXIT_PREFIX_MISMATCH")
    target = float(position["signal"]["meta"]["target_price"])
    return {"exit_next_open": float(bar["close"]) >= target,
            "reason": "BOX_CENTER_CLOSE_NEXT_OPEN"}
