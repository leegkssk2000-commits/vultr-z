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


SPEC: dict[str, Any] = {
    "identity": IDENTITY,
    "parent": PARENT_IDENTITY,
    "timeframe_min": TIMEFRAME_MIN,
    "axis": AXIS,
    "source": "https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI",
    "source_location": "How this indicator works: final failure-swing bullet",
    "source_case_sha256": SOURCE_CASE_SHA256,
    "source_review_case_sha256": "a9bb1f6ca6345e2d46d40da97403f05f00e47c679842169d60479726592cc5ac",
    "direct": [
        "Bottom failure swing: RSI higher low followed by a move above the previous RSI high.",
        "Top failure swing: RSI lower high followed by a move below the previous RSI low.",
        "No numeric overbought/oversold threshold is stated in the guide's failure-swing rule.",
    ],
    "classification": "NEW_SOURCE_ADAPTATION_NOT_REPAIR_OF_A_VIOLATED_OLD_PRICE_SWEEP_SPEC",
    "adaptation": {
        "initialization": "After parent 101 local bars, seed current RSI. A change from rising to falling confirms a HIGH at the previous completed extreme; falling to rising confirms a LOW. No future right window.",
        "plateau": "Equal RSI neither confirms a pivot nor counts as a break. A plateau extreme uses its most recent completed index.",
        "pattern": "Latest three alternating completed pivots LOW,HIGH,LOW with third>first for long; HIGH,LOW,HIGH with third<first for short.",
        "trigger": "A subsequent completed RSI strictly crosses beyond the middle pivot. The same bar that confirms the third pivot can also cross that middle pivot.",
        "expiry": "Inherited own per-stage 8-bar expiry: clear unfinished oscillator setup if more than8 local bars since the last confirmed pivot. Pending final regime qualification expires more than8 bars after oscillator break.",
        "regime_gate": "Preserve original final abs(EMA21-EMA55)/ATR<=1.2. As in parent, check only on a later bar after oscillator setup is complete; do not retune the threshold.",
        "consumption": "Once oscillator break creates pending qualification, do not form new overlapping setups until it emits or expires. On emission clear pivots and seed current RSI to prevent duplicate entry from the same pattern.",
        "gap": "Parent canonical preparation splits physical gaps and declared segments; reset every oscillator state and101bar warmup at each split.",
        "unchanged": "Parent RSI14/ATR/EMA preparation; stop_atr0.9,target1.6R,max_hold18bars,scratch5bars atMFE<0.4R; next-open execution and occupancy delegated to root; no new30/70 filter.",
        "risk_reference": "Keep price lo20/hi20 invalidation metadata for the parent protocol; control lifecycle does not use that metadata as an exit.",
        "causal_timing": "Source event index is oscillator break. Economic signal index is the later completed bar passing original range gate. Both event and signal timestamps recorded; feature availability remains cumulative parent availability.",
    },
    "preserved": [
        "Parent RSI14, ATR, EMA preparation and cumulative availability.",
        "Final range gate abs(EMA21-EMA55)/ATR<=1.2 on a later completed bar.",
        "Stop0.9ATR, target1.6R, maxhold18, scratch5 withMFE<0.4R.",
        "Parent lifecycle and root next-open execution/occupancy.",
    ],
    "exact_author_strategy_replication": False,
    "historical_data_status": "ALREADY_INSPECTED_DEV_DIAGNOSTIC",
    "order": "BLOCKED",
    "live": "BLOCKED",
}
SPEC_SHA256 = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


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
