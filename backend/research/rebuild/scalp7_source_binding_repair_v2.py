"""Canonical source-ID representation repair; frozen economic rules unchanged."""

from __future__ import annotations

import copy
import importlib
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

engine: Any = importlib.import_module("backend.research.rebuild.scalp7_execution_v2")


def bind_segments(
    signals: list[dict[str, Any]], frames: Mapping[str, pd.DataFrame]
) -> list[dict[str, Any]]:
    indexes = {
        symbol: {
            int(row["open_ts_ms"]): row["segment_id"]
            for row in frame[["open_ts_ms", "segment_id"]].to_dict("records")
        }
        for symbol, frame in frames.items()
    }
    result = []
    for raw in signals:
        signal = copy.deepcopy(raw)
        if not signal.get("legs"):
            source = indexes[str(signal["symbol"])].get(
                int(signal["signal_open_ts_ms"])
            )
            if source is not None:
                # Permit only an exact lexical ID-equivalence. No gap removal,
                # index remapping, rounded timestamp or mismatched source repair.
                if str(source) != str(signal["segment_id"]):
                    raise ValueError("SOURCE_SEGMENT_VALUE_MISMATCH")
                signal["segment_id"] = source
        result.append(signal)
    return result


def replay(
    signals: list[dict[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    *,
    exit_update: Callable[..., dict[str, Any]],
    identity: str,
    entry_update: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bound = bind_segments(signals, frames)
    cashflows: dict[tuple[str, str, int], list[dict[str, Any]]] = {}

    def observe(position: dict[str, Any], bar: Any, history: Any) -> dict[str, Any]:
        update = exit_update(position, bar, history)
        if update.get("partial_fraction"):
            signal = position["signal"]
            key = (signal["identity"], signal["symbol"], signal["signal_ts_ms"])
            cashflows.setdefault(key, []).append(
                {
                    "fraction_original_notional": float(update["partial_fraction"]),
                    "fill_price": float(update["partial_price"]),
                    "fill_interval_start_ms": int(bar["open_ts_ms"]),
                    "fill_interval_end_ms": int(bar["close_ts_ms"]),
                    "observed_at_ms": int(bar["available_ts_ms"]),
                    "rule": "FROZEN_RESTING_LIMIT_STOP_FIRST",
                }
            )
        return update

    out = engine.replay(
        bound,
        frames,
        costs,
        identity=identity,
        exit_update=observe,
        entry_update=entry_update,
    )
    for row in out["trades"]:
        key = (row["identity"], row["symbol"], row["signal_ts_ms"])
        row["partial_cashflows"] = cashflows.get(key, [])
        row["terminal_fraction_original_notional"] = 1.0 - sum(
            event["fraction_original_notional"] for event in row["partial_cashflows"]
        )
        row["source_binding_revision"] = "EXACT_LEXICAL_SEGMENT_ID_TYPE_NORMALIZATION"
    out["source_binding_revision"] = "EXACT_LEXICAL_SEGMENT_ID_TYPE_NORMALIZATION"
    return out
