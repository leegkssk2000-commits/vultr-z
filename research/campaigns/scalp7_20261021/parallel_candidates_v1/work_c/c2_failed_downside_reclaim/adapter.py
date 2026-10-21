"""Closed-bar failed downside break: frozen research adaptation, never orders."""
from __future__ import annotations

from typing import Any
import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as execution

IDENTITY = "scalp7_c2_closed_downside_failure_reclaim_30m_v1"
TIMEFRAME_MIN = 30
LOOKBACK, AGE, RECOVERY, HOLD = 20, 4, 3, 12


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    signals = []
    for symbol in sorted(frames):
        rows, _ = execution._frame_records(frames[symbol], TIMEFRAME_MIN)
        past: list[dict[str, Any]] = []
        setup = None
        consumed: set[int] = set()
        previous = None
        for bar in rows:
            if pd.isna(bar["segment_id"]) or not str(bar["segment_id"]).strip():
                raise ValueError("SEGMENT_ID_REQUIRED")
            if previous is not None and not execution._can_follow(previous, bar):
                past, setup = [], None
            previous = bar
            # A delayed final OHLC cannot retroactively fill the next open.
            if bar["available_ts_ms"] != bar["close_ts_ms"]:
                past, setup = [], None
                continue
            close = float(bar["close"])
            if setup is not None:
                setup["age"] += 1
                setup["stop"] = min(setup["stop"], float(bar["low"]))
                if setup["age"] > RECOVERY or close >= setup["midpoint"]:
                    setup = None
                elif close > setup["low"]:
                    signals.append({
                        "identity": IDENTITY, "lane": "closed_downside_failure",
                        "symbol": symbol, "side": 1, "timeframe_min": TIMEFRAME_MIN,
                        "signal_open_ts_ms": int(bar["open_ts_ms"]),
                        "signal_ts_ms": int(bar["available_ts_ms"]),
                        "segment_id": bar["segment_id"], "stop_price": setup["stop"],
                        "max_hold_bars": HOLD, "take_profit_r": None,
                        "invalidation_price": setup["low"],
                        "meta": {"reference_low": setup["low"],
                                 "reference_high": setup["high"],
                                 "target_price": setup["midpoint"],
                                 "reference_low_ts_ms": setup["reference_ts"],
                                 "setup_ts_ms": setup["setup_ts"],
                                 "feature_available_ts_ms": int(bar["available_ts_ms"]),
                                 "regime": "FAILED_CLOSED_DOWNSIDE_BREAK"},
                    })
                    setup = None
            elif len(past) >= LOOKBACK:
                context = past[-LOOKBACK:]
                low = min(float(r["low"]) for r in context)
                high = max(float(r["high"]) for r in context)
                last_low = max(j for j, r in enumerate(context) if float(r["low"]) == low)
                ref_ts = int(context[last_low]["open_ts_ms"])
                if (close < low and high > low and LOOKBACK - last_low >= AGE
                        and ref_ts not in consumed):
                    consumed.add(ref_ts)
                    setup = {"low": low, "high": high, "midpoint": (low + high) / 2,
                             "stop": float(bar["low"]), "age": 0,
                             "reference_ts": ref_ts, "setup_ts": int(bar["close_ts_ms"])}
            past.append(bar)
            past = past[-LOOKBACK:]
    return sorted(signals, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def entry_update(signal: dict, entry: float) -> dict:
    meta = signal["meta"]
    if not meta["reference_low"] < entry < meta["target_price"]:
        return {"reject": True, "reason": "ENTRY_OUTSIDE_RECOVERY_REWARD_INTERVAL"}
    return {}


def exit_update(position: dict, bar: dict, history: pd.DataFrame) -> dict:
    del history
    meta = position["signal"]["meta"]
    if float(bar["close"]) >= meta["target_price"]:
        return {"exit_next_open": True, "reason": "FROZEN_MIDPOINT_CLOSE"}
    if float(bar["close"]) < meta["reference_low"]:
        return {"exit_next_open": True, "reason": "RECOVERY_FAILED_CLOSE"}
    return {"exit_next_open": False}
