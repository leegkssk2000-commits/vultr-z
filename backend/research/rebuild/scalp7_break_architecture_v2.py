"""Frozen 15m breakout / literal retest / reclaim research grammar.

No orders, costs, outcomes, feature fit, or economic execution occurs here.
Bars use UTC interval-open and exclusive interval-close timestamps. The caller
owns next-open fills and conservative stop / gap / portfolio accounting.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import pandas as pd

IDENTITY = "scalp7_break_15m_anchored_retest_reclaim_v2"
LANE = "break_and_continue"
TIMEFRAME_MIN = 15
TIMEFRAME_MS = TIMEFRAME_MIN * 60_000
SPEC: dict[str, Any] = {
    "identity": IDENTITY,
    "lane": LANE,
    "timeframe_min": TIMEFRAME_MIN,
    "channel_bars": 20,
    "setup_max_bars_from_break": 10,
    "max_hold_bars": 24,
    "side": "SYMMETRIC_LONG_SHORT_RESEARCH_ONLY",
    "grammar": [
        "PRIOR_20_COMPLETED_BAR_CHANNEL",
        "CLOSE_BREAK",
        "LITERAL_LEVEL_RETEST_CLOSE_OUTSIDE",
        "LATER_RETEST_EXTREME_RECLAIM",
        "NEXT_UTC_BAR_OPEN",
    ],
    "setup_failure": "close inside original channel or post-retest adverse extreme breach",
    "stop": "frozen literal retest adverse extreme",
    "exit": "stop intrabar; original breakout level loss at close exits next open; 24 bar cap",
    "profit_target": None,
    "trail": None,
    "threshold_grid": False,
    "historical_outcome_features": False,
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(
    json.dumps(SPEC, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
).hexdigest()


@dataclass
class Setup:
    side: int
    reference: float
    break_open_ts_ms: int
    break_available_ts_ms: int
    channel_high: float
    channel_low: float
    stage: str = "AWAIT_RETEST"
    retest_open_ts_ms: int | None = None
    retest_available_ts_ms: int | None = None
    retest_high: float | None = None
    retest_low: float | None = None


def _bar(row: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(row)
    for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        number = float(value[key])
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError("INVALID_TIMESTAMP")
        value[key] = int(number)
    if value["open_ts_ms"] % TIMEFRAME_MS:
        raise ValueError("UTC_15M_ALIGNMENT_REQUIRED")
    if value["close_ts_ms"] != value["open_ts_ms"] + TIMEFRAME_MS:
        raise ValueError("EXCLUSIVE_15M_CLOSE_REQUIRED")
    if value["available_ts_ms"] < value["close_ts_ms"]:
        raise ValueError("CLOSED_BAR_AVAILABILITY_REQUIRED")
    if value.get("segment_id") is None or str(value["segment_id"]) == "":
        raise ValueError("SEGMENT_ID_REQUIRED")
    for key in ("open", "high", "low", "close"):
        number = float(value[key])
        if not math.isfinite(number) or number <= 0:
            raise ValueError("POSITIVE_FINITE_OHLC_REQUIRED")
        value[key] = number
    if not (
        value["low"]
        <= min(value["open"], value["close"])
        <= max(value["open"], value["close"])
        <= value["high"]
    ):
        raise ValueError("INVALID_CANDLE_GEOMETRY")
    return value


class BreakArchitecture:
    """One symbol's deterministic closed-bar setup producer, without fills."""

    def __init__(self, symbol: str) -> None:
        if not symbol:
            raise ValueError("SYMBOL_REQUIRED")
        self.symbol = symbol
        self.history: deque[dict[str, Any]] = deque(maxlen=20)
        self.setup: Setup | None = None
        self.last_open: int | None = None
        self.last_segment: Any = None

    def observe(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        bar = _bar(row)
        opened = bar["open_ts_ms"]
        if self.last_open is not None:
            if opened <= self.last_open:
                raise ValueError("DUPLICATE_OR_REVERSED_BAR")
            if (
                opened != self.last_open + TIMEFRAME_MS
                or bar["segment_id"] != self.last_segment
            ):
                self.history.clear()
                self.setup = None
        self.last_open = opened
        self.last_segment = bar["segment_id"]
        signal = self._step(bar)
        self.history.append(bar)
        return signal

    def _step(self, bar: dict[str, Any]) -> dict[str, Any] | None:
        state = self.setup
        if state is None:
            if len(self.history) != 20:
                return None
            high = max(x["high"] for x in self.history)
            low = min(x["low"] for x in self.history)
            side = 1 if bar["close"] > high else -1 if bar["close"] < low else 0
            if side:
                self.setup = Setup(
                    side,
                    high if side == 1 else low,
                    bar["open_ts_ms"],
                    max(
                        bar["available_ts_ms"],
                        max(x["available_ts_ms"] for x in self.history),
                    ),
                    high,
                    low,
                )
            return None
        elapsed = (bar["open_ts_ms"] - state.break_open_ts_ms) // TIMEFRAME_MS
        inside = state.side * (bar["close"] - state.reference) <= 0
        if elapsed > 10 or inside:
            self.setup = None
            return None
        if state.stage == "AWAIT_RETEST":
            touched = (
                bar["low"] <= state.reference
                if state.side == 1
                else bar["high"] >= state.reference
            )
            if touched:
                state.stage = "AWAIT_RECLAIM"
                state.retest_open_ts_ms = bar["open_ts_ms"]
                state.retest_available_ts_ms = bar["available_ts_ms"]
                state.retest_high = bar["high"]
                state.retest_low = bar["low"]
            return None
        assert state.retest_high is not None and state.retest_low is not None
        adverse_breach = (
            bar["low"] < state.retest_low
            if state.side == 1
            else bar["high"] > state.retest_high
        )
        if adverse_breach:
            self.setup = None
            return None
        reclaimed = (
            bar["close"] > state.retest_high
            if state.side == 1
            else bar["close"] < state.retest_low
        )
        if not reclaimed:
            return None
        stop = state.retest_low if state.side == 1 else state.retest_high
        assert state.retest_available_ts_ms is not None
        available = max(
            bar["available_ts_ms"],
            state.break_available_ts_ms,
            state.retest_available_ts_ms,
            max(x["available_ts_ms"] for x in self.history),
        )
        setup_key = {
            "identity": IDENTITY,
            "symbol": self.symbol,
            "break_open_ts_ms": state.break_open_ts_ms,
            "segment_id": bar["segment_id"],
            "side": state.side,
        }
        signal = {
            "identity": IDENTITY,
            "lane": LANE,
            "timeframe_min": TIMEFRAME_MIN,
            "symbol": self.symbol,
            "side": state.side,
            "signal_open_ts_ms": bar["open_ts_ms"],
            "signal_ts_ms": available,
            "segment_id": bar["segment_id"],
            "stop_price": stop,
            "max_hold_bars": 24,
            "take_profit_r": None,
            "invalidation_price": state.reference,
            "exit_policy": "STRUCTURAL_CLOSE",
            "meta": {
                **setup_key,
                "spec_sha256": SPEC_SHA256,
                "setup_id": hashlib.sha256(
                    json.dumps(setup_key, sort_keys=True).encode()
                ).hexdigest(),
                "feature_available_ts_ms": available,
                "channel_high": state.channel_high,
                "channel_low": state.channel_low,
                "retest_open_ts_ms": state.retest_open_ts_ms,
                "retest_high": state.retest_high,
                "retest_low": state.retest_low,
                "event_trace": SPEC["grammar"],
                "historical_outcome_features": False,
            },
        }
        self.setup = None
        return signal


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        machine = BreakArchitecture(symbol)
        for row in frames[symbol].to_dict("records"):
            signal = machine.observe(row)
            if signal is not None:
                signals.append(signal)
    return sorted(signals, key=lambda x: (x["signal_ts_ms"], x["symbol"]))


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    """Closed-bar thesis loss requests a later open; it never fills an exit."""
    closed = _bar(bar)
    signal = position["signal"]
    if signal["identity"] != IDENTITY or int(position["side"]) not in (-1, 1):
        raise ValueError("POSITION_IDENTITY_OR_SIDE_MISMATCH")
    if closed["segment_id"] != signal["segment_id"]:
        return {"exit_next_open": False, "reason": "GAP_HOLD_ENGINE_OWNS_BOUNDARY"}
    failed = (
        int(position["side"]) * (closed["close"] - float(signal["invalidation_price"]))
        <= 0
    )
    return {
        "exit_next_open": failed,
        "reason": "ANCHORED_BREAKOUT_LEVEL_LOST" if failed else "THESIS_INTACT",
    }
