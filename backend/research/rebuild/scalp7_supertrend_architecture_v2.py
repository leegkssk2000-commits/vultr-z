"""Frozen 30m native-band impulse/pullback grammar; no economic runner/order API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping

import pandas as pd  # type: ignore[import-untyped]

IDENTITY = "scalp7_supertrend_native_impulse_pullback_30m_v2"
LANE = "supertrend_pullback"
TIMEFRAME_MIN = 30
TIMEFRAME_MS = 1_800_000
ATR_LENGTH = 10
MULTIPLIER = 3.0
MAX_HOLD_BARS = 16
FREEZE_SHA256 = "ff20ffc5bd7bfce0792d499eb10e0d0f4f67a77aebca219b260707b4e64ab328"


@dataclass
class BandState:
    segment_id: str = ""
    last_open_ts_ms: int = -1
    available_ts_ms: int = 0
    previous_close: float = 0.0
    seed: list[float] = field(default_factory=list)
    atr: float | None = None
    upper: float | None = None
    lower: float | None = None
    direction: int = 0
    line: float | None = None


@dataclass
class Setup:
    side: int
    since: int
    impulse_origin: float
    impulse_open_ts_ms: int
    pullback_trigger: float | None = None
    pullback_extreme: float | None = None
    pullback_open_ts_ms: int | None = None


def _bar(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    )
    if any(k not in raw for k in required):
        raise ValueError("SUPERTREND_REQUIRED_CANDLE_FIELD_MISSING")
    row = dict(raw)
    for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        value = float(row[k])
        if not math.isfinite(value) or value != int(value):
            raise ValueError("SUPERTREND_INVALID_TIMESTAMP")
        row[k] = int(value)
    if (
        row["open_ts_ms"] % TIMEFRAME_MS
        or row["close_ts_ms"] - row["open_ts_ms"] != TIMEFRAME_MS
    ):
        raise ValueError("SUPERTREND_REQUIRES_UTC_COMPLETE_30M")
    if row["available_ts_ms"] < row["close_ts_ms"]:
        raise ValueError("SUPERTREND_BAR_AVAILABLE_BEFORE_CLOSE")
    if row["segment_id"] is None or pd.isna(row["segment_id"]):
        raise ValueError("SUPERTREND_SEGMENT_REQUIRED")
    row["segment_id"] = str(row["segment_id"])
    for k in ("open", "high", "low", "close"):
        row[k] = float(row[k])
        if not math.isfinite(row[k]) or row[k] <= 0:
            raise ValueError("SUPERTREND_INVALID_PRICE")
    if not (
        row["low"]
        <= min(row["open"], row["close"])
        <= max(row["open"], row["close"])
        <= row["high"]
    ):
        raise ValueError("SUPERTREND_INVALID_OHLC")
    return row


def _contiguous(state: BandState, row: Mapping[str, Any]) -> bool:
    return bool(
        state.last_open_ts_ms >= 0
        and str(row["segment_id"]) == state.segment_id
        and int(row["open_ts_ms"]) == state.last_open_ts_ms + TIMEFRAME_MS
    )


def _step(state: BandState, row: Mapping[str, Any]) -> BandState:
    if not _contiguous(state, row):
        state = BandState(segment_id=str(row["segment_id"]))
    high, low, close = (float(row[k]) for k in ("high", "low", "close"))
    previous = state.previous_close if state.last_open_ts_ms >= 0 else close
    tr = max(high - low, abs(high - previous), abs(low - previous))
    state.seed.append(tr)
    state.seed = state.seed[-ATR_LENGTH:]
    if state.atr is not None:
        state.atr = ((ATR_LENGTH - 1) * state.atr + tr) / ATR_LENGTH
    elif len(state.seed) == ATR_LENGTH:
        state.atr = sum(state.seed) / ATR_LENGTH
    if state.atr is not None:
        midpoint = (high + low) / 2.0
        upper, lower = (
            midpoint + MULTIPLIER * state.atr,
            midpoint - MULTIPLIER * state.atr,
        )
        if state.upper is None or state.lower is None:
            state.direction = 1 if close >= midpoint else -1
        else:
            upper = (
                upper if upper < state.upper or previous > state.upper else state.upper
            )
            lower = (
                lower if lower > state.lower or previous < state.lower else state.lower
            )
            if state.direction == 1 and close < lower:
                state.direction = -1
            elif state.direction == -1 and close > upper:
                state.direction = 1
        state.upper, state.lower = upper, lower
        state.line = lower if state.direction == 1 else upper
    state.previous_close = close
    state.last_open_ts_ms = int(row["open_ts_ms"])
    state.available_ts_ms = max(state.available_ts_ms, int(row["available_ts_ms"]))
    return state


def indicator_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Expose causal native state for inspection without creating economic trades."""
    state = BandState()
    output = []
    previous_open = -1
    for raw in frame.to_dict("records"):
        row = _bar(raw)
        if row["open_ts_ms"] <= previous_open:
            raise ValueError("SUPERTREND_NONINCREASING_CANDLE_TIME")
        previous_open = row["open_ts_ms"]
        state = _step(state, row)
        output.append({**row, "native_state": asdict(state)})
    return output


def _advance_setup(
    pending: Setup | None,
    i: int,
    row: Mapping[str, Any],
    previous: Mapping[str, Any],
    side: int,
) -> tuple[Setup | None, bool]:
    close = float(row["close"])
    if pending is not None and (
        pending.side != side
        or i - pending.since > MAX_HOLD_BARS
        or side * (close - pending.impulse_origin) <= 0
    ):
        return None, False
    if pending is None:
        prior_extreme = float(previous["high" if side == 1 else "low"])
        if side * (close - prior_extreme) > 0:
            pending = Setup(
                side,
                i,
                float(row["low" if side == 1 else "high"]),
                int(row["open_ts_ms"]),
            )
        return pending, False
    if pending.pullback_trigger is None:
        if side * (close - float(previous["close"])) < 0:
            pending.pullback_trigger = float(row["high" if side == 1 else "low"])
            pending.pullback_extreme = float(row["low" if side == 1 else "high"])
            pending.pullback_open_ts_ms = int(row["open_ts_ms"])
        return pending, False
    extreme = float(row["low" if side == 1 else "high"])
    assert pending.pullback_extreme is not None
    pending.pullback_extreme = (
        min(pending.pullback_extreme, extreme)
        if side == 1
        else max(pending.pullback_extreme, extreme)
    )
    return pending, side * (close - pending.pullback_trigger) > 0


def generate_signals(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        rows = indicator_rows(frame)
        pending: Setup | None = None
        for i in range(1, len(rows)):
            row, previous = rows[i], rows[i - 1]
            native = row["native_state"]
            direction = int(native["direction"])
            contiguous = (
                row["segment_id"] == previous["segment_id"]
                and row["open_ts_ms"] == previous["open_ts_ms"] + TIMEFRAME_MS
            )
            if (
                not contiguous
                or direction == 0
                or direction != int(previous["native_state"]["direction"])
            ):
                pending = None
                continue
            if direction * (float(row["close"]) - float(native["line"])) <= 0:
                pending = None
                continue
            pending, emit = _advance_setup(pending, i, row, previous, direction)
            if not emit or pending is None:
                continue
            assert pending.pullback_extreme is not None
            stop = (
                min(pending.impulse_origin, pending.pullback_extreme)
                if direction == 1
                else max(pending.impulse_origin, pending.pullback_extreme)
            )
            if direction * (float(row["close"]) - stop) <= 0:
                pending = None
                continue
            signals.append(
                {
                    "identity": IDENTITY,
                    "lane": LANE,
                    "timeframe_min": TIMEFRAME_MIN,
                    "symbol": symbol,
                    "side": direction,
                    "signal_open_ts_ms": int(row["open_ts_ms"]),
                    "signal_ts_ms": max(
                        int(row["close_ts_ms"]), int(native["available_ts_ms"])
                    ),
                    "segment_id": str(row["segment_id"]),
                    "stop_price": stop,
                    "max_hold_bars": MAX_HOLD_BARS,
                    "take_profit_r": None,
                    "invalidation_price": pending.impulse_origin,
                    "exit_policy": "NATIVE_ST_STRUCTURE",
                    "meta": {
                        "freeze_sha256": FREEZE_SHA256,
                        "event_trace": [
                            "NATIVE_TREND",
                            "IMPULSE",
                            "PULLBACK",
                            "RECLAIM",
                        ],
                        "impulse_open_ts_ms": pending.impulse_open_ts_ms,
                        "pullback_open_ts_ms": pending.pullback_open_ts_ms,
                        "pullback_trigger": pending.pullback_trigger,
                        "native_state": dict(native),
                    },
                }
            )
            pending = None
    return sorted(signals, key=lambda s: (s["signal_ts_ms"], s["symbol"]))


def exit_update(
    position: dict[str, Any],
    bar: dict[str, Any],
    history: pd.DataFrame,
) -> dict[str, Any]:
    """Update from one closed bar; returned stop is effective on the next bar."""
    row = _bar(bar)
    if not history.empty and int(history["open_ts_ms"].max()) > row["open_ts_ms"]:
        raise ValueError("SUPERTREND_FUTURE_HISTORY_FORBIDDEN")
    signal = position["signal"]
    if signal.get("identity") != IDENTITY:
        raise ValueError("SUPERTREND_POSITION_IDENTITY_MISMATCH")
    if row["open_ts_ms"] < int(position["entry_ts_ms"]):
        raise ValueError("SUPERTREND_EXIT_BEFORE_ENTRY")
    cached = position.get("_scalp7_supertrend_exit_cache")
    if cached is not None and cached["open_ts_ms"] == row["open_ts_ms"]:
        return dict(cached["result"])
    saved = position.get("_scalp7_supertrend_state", signal["meta"]["native_state"])
    state = BandState(**{**saved, "seed": list(saved["seed"])})
    if not _contiguous(state, row):
        return {"exit_next_open": True, "reason": "DATA_GAP_HOLD", "next_stop": None}
    state = _step(state, row)
    position["_scalp7_supertrend_state"] = asdict(state)
    side = int(position["side"])
    origin = float(signal["invalidation_price"])
    invalid = side * (float(row["close"]) - origin) <= 0
    flipped = state.direction != side
    next_stop: float | None = None
    if not flipped and not invalid and state.line is not None:
        current_stop = float(position["stop_price"])
        proposed = (
            max(current_stop, state.line)
            if side == 1
            else min(current_stop, state.line)
        )
        if side * (float(row["close"]) - proposed) > 0:
            next_stop = proposed
    result: dict[str, Any] = {
        "exit_next_open": flipped or invalid,
        "reason": (
            "NATIVE_ST_FLIP"
            if flipped
            else "IMPULSE_ORIGIN_FAILURE" if invalid else "NATIVE_ST_TRAIL"
        ),
        "next_stop": next_stop,
    }
    position["_scalp7_supertrend_exit_cache"] = {
        "open_ts_ms": row["open_ts_ms"],
        "result": dict(result),
    }
    return result
