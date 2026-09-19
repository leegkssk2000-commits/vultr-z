"""Source-adapted RSI oscillator failure swings; parent risk and execution preserved.

This is a new interpretation of Fidelity's public oscillator pattern, not an
exact Wilder/Connors reproduction and not a repair of the old price-sweep spec.
Only completed RSI observations form pivots. This module runs no economics.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd  # type: ignore[import-untyped]

from backend.research.rebuild import scalp7_materials_program_v2 as parent

IDENTITY = "rsi_oscillator_failure_swing_30m_source_fidelity_v1"
PARENT_IDENTITY = "rsi_swing_fail_30m_control_v2"
TIMEFRAME_MIN = parent.TIMEFRAME_MIN
TF_MS = parent.TF_MS
AXIS = "ENTRY_ORDERED_RSI_OSCILLATOR_FAILURE_SWING_REPLACES_PRICE_SWEEP"
SOURCE_CASE_SHA256 = "bed680d04fb4331a0e4d3524d1822d6abcc7ff4c8a73e8d72c9d4c2e84465576"
STAGE_TTL = 8
WARMUP_BARS = 101


@dataclass(frozen=True)
class Pivot:
    kind: str
    value: float
    index: int
    confirmed_index: int


@dataclass
class OscillatorState:
    direction: int = 0
    last_rsi: float = math.nan
    extreme: float = math.nan
    extreme_index: int = -1
    since: int = -1
    pivots: list[Pivot] = field(default_factory=list)

    def reset(self, value: float = math.nan, index: int = -1) -> None:
        self.direction = 0
        self.last_rsi = value
        self.extreme = value
        self.extreme_index = index
        self.since = -1
        self.pivots.clear()


def _failure_side(pivots: list[Pivot], value: float) -> int:
    if len(pivots) != 3:
        return 0
    first, middle, third = pivots
    kinds = (first.kind, middle.kind, third.kind)
    if (
        kinds == ("LOW", "HIGH", "LOW")
        and third.value > first.value
        and value > middle.value
    ):
        return 1
    if (
        kinds == ("HIGH", "LOW", "HIGH")
        and third.value < first.value
        and value < middle.value
    ):
        return -1
    return 0


def oscillator_step(
    state: OscillatorState, value: float, index: int
) -> dict[str, Any] | None:
    """Confirm previous extrema on the current reversal; emit once per pattern."""
    if not math.isfinite(value):
        state.reset()
        return None
    if not math.isfinite(state.last_rsi):
        state.reset(value, index)
        return None
    if state.pivots and index - state.since > STAGE_TTL:
        state.reset(value, index)
        return None
    change = value - state.last_rsi
    direction = 1 if change > 0 else -1 if change < 0 else 0
    if direction:
        if state.direction and direction != state.direction:
            state.pivots.append(
                Pivot(
                    "HIGH" if state.direction == 1 else "LOW",
                    state.extreme,
                    state.extreme_index,
                    index,
                )
            )
            state.pivots = state.pivots[-3:]
            state.since = index
        state.direction = direction
        state.extreme = value
        state.extreme_index = index
    elif value == state.extreme:
        # Equality confirms nothing; the rightmost completed plateau is its endpoint.
        state.extreme_index = index
    state.last_rsi = value
    side = _failure_side(state.pivots, value)
    if not side:
        return None
    event = {
        "side": side,
        "oscillator_break_index": index,
        "oscillator_break_rsi": value,
        "pivots": [
            {
                "kind": pivot.kind,
                "rsi": pivot.value,
                "index": pivot.index,
                "confirmed_index": pivot.confirmed_index,
            }
            for pivot in state.pivots
        ],
    }
    state.reset(value, index)
    return event


def _signal(
    symbol: str,
    row: Mapping[str, Any],
    pending: Mapping[str, Any],
) -> dict[str, Any]:
    side = int(pending["side"])
    params = parent.PARAMS["rsi_swing_fail"]
    close, atr = float(row["close"]), float(row["atr"])
    features = {
        key: row[key]
        for key in (
            "open",
            "high",
            "low",
            "close",
            "atr",
            "ema21",
            "ema55",
            "ema100",
            "rsi",
            "macd_hist",
            "hi20",
            "lo20",
        )
    }
    evidence = json.dumps(features, sort_keys=True, allow_nan=False)
    return {
        "identity": IDENTITY,
        "lane": "MATERIAL:rsi_swing_fail",
        "timeframe_min": TIMEFRAME_MIN,
        "symbol": symbol,
        "side": side,
        "signal_open_ts_ms": int(row["open_ts_ms"]),
        "signal_ts_ms": int(row["_feature_available_ts_ms"]),
        "segment_id": row["segment_id"],
        "stop_price": close - side * float(params["stop_atr"]) * atr,
        "max_hold_bars": int(params["max_hold"]),
        "take_profit_r": params["target_r"],
        "invalidation_price": float(row["lo20"] if side == 1 else row["hi20"]),
        "exit_policy": "MATERIAL_LIFECYCLE_V2",
        "meta": {
            "material": "rsi_swing_fail",
            "mode": "RSI_OSCILLATOR_FAILURE_SWING",
            "parent_identity": PARENT_IDENTITY,
            "axis": AXIS,
            "source_case_sha256": SOURCE_CASE_SHA256,
            "source_classification": "PUBLIC_PATTERN_30M_MECHANICAL_ADAPTATION",
            "entry_atr": atr,
            "feature_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
            "features": features,
            "oscillator_event": dict(pending),
            "authority": "RESEARCH_ONLY",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }


def generate_signals(
    frames: dict[str, pd.DataFrame],
    *,
    costs: Mapping[str, float] | None = None,
    identity: str = IDENTITY,
) -> list[dict[str, Any]]:
    # No entry cost gate exists in the parent; root charges its bound execution costs.
    del costs
    if identity != IDENTITY:
        raise ValueError("UNKNOWN_RSI_SOURCE_FIDELITY_IDENTITY")
    events: list[dict[str, Any]] = []
    for symbol, frame in sorted(frames.items()):
        prepared = parent._prepare(frame)
        if prepared.empty:
            continue
        for _, group in prepared.groupby("_local_segment", sort=False):
            rows = group.to_dict("records")
            state = OscillatorState()
            pending: dict[str, Any] | None = None
            for index in range(WARMUP_BARS, len(rows)):
                row = rows[index]
                rsi = float(row["rsi"])
                required = ("close", "high", "low", "atr", "hi20", "lo20")
                if (
                    not all(parent._finite(row[key]) for key in required)
                    or float(row["atr"]) <= 0
                    or not math.isfinite(rsi)
                ):
                    state.reset()
                    pending = None
                    continue
                if pending is not None:
                    if index - int(pending["oscillator_break_index"]) > STAGE_TTL:
                        pending = None
                        state.reset(rsi, index)
                        continue
                    flat = abs(float(row["ema21"]) - float(row["ema55"])) / float(
                        row["atr"]
                    )
                    if flat <= 1.2:
                        event = _signal(symbol, row, pending)
                        if event["stop_price"] > 0:
                            events.append(event)
                        pending = None
                        state.reset(rsi, index)
                    continue
                pending = oscillator_step(state, rsi, index)
                if pending is not None:
                    pending["oscillator_break_open_ts_ms"] = int(row["open_ts_ms"])
                    pending["oscillator_break_available_ts_ms"] = int(
                        row["_feature_available_ts_ms"]
                    )
    return sorted(
        events,
        key=lambda event: (event["signal_ts_ms"], event["identity"], event["symbol"]),
    )


def exit_update(
    position: Mapping[str, Any], bar: Mapping[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    """Delegate exact control scratch/stop/target/hold semantics without mutation."""
    signal = position["signal"]
    if signal["identity"] != IDENTITY:
        raise ValueError("UNKNOWN_RSI_SOURCE_FIDELITY_IDENTITY")
    translated = dict(position)
    translated["signal"] = dict(signal, identity=PARENT_IDENTITY)
    return parent.exit_update(translated, bar, history)
