"""One source-grounded shallow path beside the frozen literal Break producer.

Brooks supplies the pullback concept. The exact conjunction and inherited
20/10/24-bar rules are our preregistered adaptation, never source-exact alpha.
Only logical signal/lifecycle work occurs here; root owns fills and economics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_break_architecture_v2 as parent

IDENTITY = "scalp7_break_shallow_additional_path_15m_v1"
PARENT_IDENTITY = parent.IDENTITY
LANE = parent.LANE
TIMEFRAME_MIN = parent.TIMEFRAME_MIN
TIMEFRAME_MS = parent.TIMEFRAME_MS
SOURCE_URL = "https://www.brookstradingcourse.com/price-action-trading-terms-glossary/"


def _is_shallow(
    setup: parent.Setup, bar: dict[str, Any], previous: dict[str, Any]
) -> bool:
    if setup.side == 1:
        return bool(
            bar["low"] > setup.reference
            and bar["low"] < previous["low"]
            and bar["close"] < previous["close"]
        )
    return bool(
        bar["high"] < setup.reference
        and bar["high"] > previous["high"]
        and bar["close"] > previous["close"]
    )


def _shallow_signal(
    symbol: str, state: parent.Setup, bar: dict[str, Any]
) -> dict[str, Any]:
    assert state.retest_low is not None and state.retest_high is not None
    available = max(
        bar["available_ts_ms"],
        state.break_available_ts_ms,
        state.retest_available_ts_ms or 0,
    )
    key = {
        "identity": PARENT_IDENTITY,
        "symbol": symbol,
        "break_open_ts_ms": state.break_open_ts_ms,
        "segment_id": bar["segment_id"],
        "side": state.side,
    }
    return {
        "identity": PARENT_IDENTITY,
        "lane": LANE,
        "timeframe_min": TIMEFRAME_MIN,
        "symbol": symbol,
        "side": state.side,
        "signal_open_ts_ms": bar["open_ts_ms"],
        "signal_ts_ms": available,
        "segment_id": bar["segment_id"],
        "stop_price": state.retest_low if state.side == 1 else state.retest_high,
        "max_hold_bars": parent.SPEC["max_hold_bars"],
        "take_profit_r": None,
        "invalidation_price": state.reference,
        "exit_policy": "STRUCTURAL_CLOSE",
        "meta": {
            **key,
            "spec_sha256": parent.SPEC_SHA256,
            "setup_id": hashlib.sha256(
                json.dumps(key, sort_keys=True).encode()
            ).hexdigest(),
            "feature_available_ts_ms": available,
            "channel_high": state.channel_high,
            "channel_low": state.channel_low,
            "retest_open_ts_ms": state.retest_open_ts_ms,
            "retest_high": state.retest_high,
            "retest_low": state.retest_low,
            "event_trace": [
                "PRIOR_20_COMPLETED_BAR_CHANNEL",
                "CLOSE_BREAK",
                "SHALLOW_COUNTERTREND_BAR_OUTSIDE_RAIL",
                "LATER_PULLBACK_EXTREME_RECLAIM",
                "NEXT_UTC_BAR_OPEN",
            ],
            "historical_outcome_features": False,
        },
    }


def _advance_shallow(
    symbol: str,
    state: parent.Setup,
    bar: dict[str, Any],
    previous: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    elapsed = (bar["open_ts_ms"] - state.break_open_ts_ms) // TIMEFRAME_MS
    inside = state.side * (bar["close"] - state.reference) <= 0
    if elapsed > int(parent.SPEC["setup_max_bars_from_break"]) or inside:
        return False, None
    state.break_available_ts_ms = max(
        state.break_available_ts_ms, bar["available_ts_ms"]
    )
    if state.stage == "AWAIT_RETEST":
        if _is_shallow(state, bar, previous):
            state.retest_open_ts_ms = bar["open_ts_ms"]
            state.retest_available_ts_ms = bar["available_ts_ms"]
            state.retest_high = bar["high"]
            state.retest_low = bar["low"]
            state.stage = "AWAIT_RECLAIM"
        return True, None
    assert state.retest_low is not None and state.retest_high is not None
    adverse = (
        bar["low"] < state.retest_low
        if state.side == 1
        else bar["high"] > state.retest_high
    )
    if adverse:
        return False, None
    reclaimed = (
        bar["close"] > state.retest_high
        if state.side == 1
        else bar["close"] < state.retest_low
    )
    if reclaimed:
        return False, _shallow_signal(symbol, state, bar)
    return True, None


def _project(signal: dict[str, Any], path: str) -> dict[str, Any]:
    result = deepcopy(signal)
    result["identity"] = IDENTITY
    result["meta"]["fidelity"] = {
        "path": path,
        "parent_identity": PARENT_IDENTITY,
        "source_url": SOURCE_URL,
        "classification": "OWN_MECHANICAL_ADAPTATION_OF_SOURCE_PULLBACK_CONCEPT",
        "axis": "ADDITIONAL_SHALLOW_PATH_ONLY",
    }
    return result


def _deduplicate(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for signal in signals:
        key = (
            signal["symbol"],
            signal["meta"]["break_open_ts_ms"],
            signal["segment_id"],
            signal["side"],
            signal["signal_ts_ms"],
        )
        incumbent = unique.get(key)
        if incumbent is None or signal["meta"]["fidelity"]["path"] == "LITERAL_PARENT":
            unique[key] = signal
    return sorted(
        unique.values(),
        key=lambda s: (s["signal_ts_ms"], s["symbol"]),
    )


def generate_signals(
    frames: dict[str, pd.DataFrame],
    costs: dict[str, float] | None = None,
    identity: str = IDENTITY,
) -> list[dict[str, Any]]:
    """Keep every original literal event; add at most one shallow event/origin."""
    if identity != IDENTITY:
        raise ValueError("BREAK_FIDELITY_IDENTITY_MISMATCH")
    signals: list[dict[str, Any]] = []
    for symbol in sorted(frames):
        literal = parent.BreakArchitecture(symbol)
        shadows: dict[int, parent.Setup] = {}
        previous: dict[str, Any] | None = None
        for raw in frames[symbol].to_dict("records"):
            before = literal.setup
            original = literal.observe(raw)
            bar = literal.history[-1]
            if previous is not None and (
                bar["segment_id"] != previous["segment_id"]
                or bar["open_ts_ms"] != previous["close_ts_ms"]
            ):
                shadows.clear()
            if previous is not None:
                for origin, state in list(shadows.items()):
                    alive, added = _advance_shallow(symbol, state, bar, previous)
                    if not alive:
                        del shadows[origin]
                    if added is not None:
                        signals.append(_project(added, "SHALLOW"))
            # Only origins actually discovered by the untouched parent qualify.
            if before is None and literal.setup is not None:
                state = literal.setup
                shadows[state.break_open_ts_ms] = replace(state)
            if original is not None:
                signals.append(_project(original, "LITERAL_PARENT"))
            previous = bar
    return _deduplicate(signals)


def exit_update(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    """Translate identity only; use the exact parent's close-rail lifecycle."""
    signal = position["signal"]
    if signal["identity"] != IDENTITY:
        raise ValueError("BREAK_FIDELITY_POSITION_IDENTITY_MISMATCH")
    translated = dict(position)
    translated["signal"] = {**signal, "identity": PARENT_IDENTITY}
    return parent.exit_update(translated, bar, history)
