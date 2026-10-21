"""C3: completed-hour context and one closed 15m inside-bar expansion.

Internal research adaptation. No market I/O, orders or economic invocation.
"""
from __future__ import annotations

from typing import Any
import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as execution

IDENTITY = "scalp7_c3_hour_structure_inside15m_v1"
TIMEFRAME_MIN = 15
STEP = 900_000
HOUR = 3_600_000
TTL = 4
MAX_HOLD_BARS = 16


def _context(hours: dict[int, dict[str, Any]], mother: dict[str, Any]):
    end = int(mother["open_ts_ms"]) // HOUR * HOUR
    selected = [hours.get(end - n * HOUR) for n in (2, 1, 0)]
    if any(row is None for row in selected):
        return None
    if any(row["available_ts_ms"] > mother["open_ts_ms"] for row in selected):
        return None
    if not all(
        selected[0][field] < selected[1][field] < selected[2][field]
        for field in ("high", "low", "close")
    ):
        return None
    return selected


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        frame = frames[symbol].copy().reset_index(drop=True)
        rows, _ = execution._frame_records(frame, TIMEFRAME_MIN)
        hours: dict[int, dict[str, Any]] = {}
        bucket: list[dict[str, Any]] = []
        state = None
        previous = None
        for i, bar in enumerate(rows):
            if pd.isna(bar["segment_id"]) or not str(bar["segment_id"]).strip():
                raise ValueError("SEGMENT_REQUIRED")
            if previous is not None and not execution._can_follow(previous, bar):
                hours.clear()
                bucket = []
                state = None
                previous = None
            # Synchronous historical path: a delayed bar cannot retroactively
            # complete context or create a fill at an already elapsed open.
            if int(bar["available_ts_ms"]) != int(bar["close_ts_ms"]):
                hours.clear()
                bucket = []
                state = None
                previous = None
                continue
            if int(bar["open_ts_ms"]) % HOUR == 0:
                bucket = [bar]
            elif bucket and execution._can_follow(bucket[-1], bar):
                bucket.append(bar)
            else:
                bucket = []
            if len(bucket) == 4 and int(bar["close_ts_ms"]) % HOUR == 0:
                close_ts = int(bar["close_ts_ms"])
                hours[close_ts] = {
                    "open_ts_ms": int(bucket[0]["open_ts_ms"]),
                    "close_ts_ms": close_ts,
                    "available_ts_ms": max(int(x["available_ts_ms"]) for x in bucket),
                    "high": max(float(x["high"]) for x in bucket),
                    "low": min(float(x["low"]) for x in bucket),
                    "close": float(bar["close"]),
                }
                hours = {k: v for k, v in hours.items() if k >= close_ts - 3 * HOUR}
                bucket = []
            active_on_arrival = state is not None
            if state is not None:
                if i - state["inside_index"] > TTL or float(bar["low"]) <= state["low"]:
                    state = None
                elif float(bar["close"]) > state["high"]:
                    signals.append({
                        "identity": IDENTITY,
                        "lane": "mtf_inside_continuation",
                        "symbol": symbol,
                        "timeframe_min": TIMEFRAME_MIN,
                        "side": 1,
                        "signal_open_ts_ms": int(bar["open_ts_ms"]),
                        "signal_ts_ms": int(bar["available_ts_ms"]),
                        "segment_id": bar["segment_id"],
                        "stop_price": state["low"],
                        "take_profit_r": 2.0,
                        "max_hold_bars": MAX_HOLD_BARS,
                        "meta": {
                            "mother_open_ts_ms": state["mother_open_ts_ms"],
                            "inside_open_ts_ms": state["inside_open_ts_ms"],
                            "mother_high": state["high"],
                            "mother_low": state["low"],
                            "hour_context": state["hour_context"],
                            "feature_available_ts_ms": int(bar["available_ts_ms"]),
                            "source_exact": False,
                        },
                    })
                    state = None
            # A consumed/failed setup cannot rearm on its terminal bar.
            if not active_on_arrival and previous is not None:
                mother = previous
                strict_inside = (
                    float(bar["high"]) < float(mother["high"])
                    and float(bar["low"]) > float(mother["low"])
                    and float(mother["close"]) > float(mother["open"])
                )
                context = _context(hours, mother) if strict_inside else None
                if context is not None:
                    state = {
                        "inside_index": i,
                        "mother_open_ts_ms": int(mother["open_ts_ms"]),
                        "inside_open_ts_ms": int(bar["open_ts_ms"]),
                        "high": float(mother["high"]),
                        "low": float(mother["low"]),
                        "hour_context": context,
                    }
            previous = bar
    return sorted(signals, key=lambda row: (row["signal_ts_ms"], row["symbol"]))


def exit_update(position, bar, history):
    """Fixed protective stop/2R/max-hold are handled by frozen common engine."""
    del position, bar, history
    return {"exit_next_open": False, "reason": "FIXED_MOTHER_STOP_TARGET_TIME"}
