"""Non-economic native preparation for the approved Squeeze successor.

This module binds the signal low at signal availability, adapts the frozen
parent exit callback, and scans SAVED overlay trades for earlier causal triggers.
It does not regenerate the rejected overlay, compute PnL, or launch a replay.
Full chronological occupancy and next-open arbitration remain execution gates.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Callable, Mapping

import pandas as pd

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from research.campaigns.scalp7_20261013.dual_streak_v1.streak_successor_policies import (
    SQUEEZE_SUCCESSOR,
    squeeze_signal_low_invalidation,
)


SAVED_OVERLAY = "scalp7_squeeze_panic_plus_trend_disperse_utc30m_v1"
SAVED_RECEIPT = "8389495e62fb1da211c7b360de621ed782322280552d627dea58909eee6025e8"
INVENTORY = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
BINDING = "successor_signal_low_binding_v1"
EXIT_REASON = "TREND_SIGNAL_BAR_LOW_INVALIDATION_NEXT_OPEN"


def bind_signal_low(signal: Mapping[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """Copy a native parent signal; bind only its already-available source bar."""
    if signal.get("identity") != positive.SQUEEZE_PARENT:
        raise ValueError("SQUEEZE_PARENT_CALLBACK_IDENTITY_REQUIRED")
    execution.validate_signal(signal)
    if int(signal["timeframe_min"]) != 30 or signal["side"] != 1:
        raise ValueError("FROZEN_SQUEEZE_30M_LONG_REQUIRED")
    out = deepcopy(dict(signal))
    regime = out["meta"]["regime"]
    if regime == "PANIC_DISPERSION":
        return out
    if regime != "TREND_DISPERSED":
        raise ValueError("UNAUTHORIZED_SUCCESSOR_REGIME")
    if BINDING in out["meta"]:
        raise ValueError("SIGNAL_LOW_ALREADY_BOUND")
    required = {"open_ts_ms", "close_ts_ms", "available_ts_ms", "segment_id", "low"}
    if not required.issubset(frame.columns):
        raise ValueError("SIGNAL_LOW_SOURCE_SCHEMA_REQUIRED")
    hits = frame.loc[frame.open_ts_ms == int(signal["signal_open_ts_ms"])]
    if len(hits) != 1:
        raise ValueError("SIGNAL_BAR_MISSING_OR_DUPLICATE")
    row = hits.to_dict("records")[0]
    opened = execution._integer(row["open_ts_ms"], "signal_low_open_ts_ms")
    closed = execution._integer(row["close_ts_ms"], "signal_low_close_ts_ms")
    available = execution._integer(row["available_ts_ms"], "signal_low_available_ts_ms")
    low = float(row["low"])
    if (
        closed != opened + positive.TIMEFRAME_MS
        or not closed <= available <= int(signal["signal_ts_ms"])
        or row["segment_id"] != signal["segment_id"]
        or not math.isfinite(low)
        or low <= 0
    ):
        raise ValueError("SIGNAL_LOW_NOT_CAUSALLY_BOUND")
    out["meta"][BINDING] = {
        "low": low,
        "signal_open_ts_ms": opened,
        "available_ts_ms": available,
        "segment_id": row["segment_id"],
    }
    return out


def native_exit_update(
    position: dict[str, Any],
    bar: dict[str, Any],
    history: pd.DataFrame,
    *,
    parent_callback: Callable[..., dict[str, Any]] = positive.exit_update,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use the original callback FIRST; no stop/price/partial-fill mutation.

    The native engine checks current-bar stops before this callback. Its max-hold
    exit also takes precedence at the same close. This is a callback, not permission
    to skip full next-open gap/occupancy verification before an economic run.
    """
    signal = position["signal"]
    if signal.get("identity") != positive.SQUEEZE_PARENT:
        raise ValueError("SQUEEZE_PARENT_CALLBACK_IDENTITY_REQUIRED")
    result = parent_callback(position, bar, history)
    regime = signal["meta"]["regime"]
    if regime == "PANIC_DISPERSION":
        return result
    binding = signal["meta"].get(BINDING)
    if not isinstance(binding, dict):
        raise ValueError("FROZEN_SIGNAL_LOW_BINDING_REQUIRED")
    if (
        binding["signal_open_ts_ms"] != signal["signal_open_ts_ms"]
        or binding["segment_id"] != signal["segment_id"]
        or binding["available_ts_ms"] > signal["signal_ts_ms"]
    ):
        raise ValueError("SIGNAL_LOW_BINDING_IDENTITY_DRIFT")
    if int(position["hold_bars"]) >= int(signal["max_hold_bars"]):
        return result
    updated = squeeze_signal_low_invalidation(
        regime=regime,
        signal_low=binding["low"],
        signal_segment=binding["segment_id"],
        bar=bar,
        signal_available_ts_ms=int(signal["signal_ts_ms"]),
        entry_ts_ms=int(position["entry_ts_ms"]),
        asof_ms=int(bar["available_ts_ms"]),
        parent_update=result,
    )
    if updated.get("reason") == EXIT_REASON and trace is not None:
        trace.append(
            {
                "symbol": signal["symbol"],
                "signal_ts_ms": int(signal["signal_ts_ms"]),
                "frozen_signal_low": binding["low"],
                "invalidation_available_ts_ms": int(bar["available_ts_ms"]),
                "invalidation_close": float(bar["close"]),
                "action": "SCHEDULE_NEXT_ACTUAL_OPEN_NOT_INTRABAR_FILL",
            }
        )
    return updated


def scan_saved_trend_triggers(
    frames: Mapping[str, pd.DataFrame],
    saved_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Diagnostic only: count eligible earlier exits on the receipt-bound rows.

    Original exit timestamps are used ONLY as diagnostic comparison cutoffs. They
    are not passed to the runtime callback or used to choose which trades to admit.
    No PnL is calculated and the old candidate is never regenerated or replayed.
    """
    unsigned = dict(saved_report)
    receipt = unsigned.pop("receipt_sha256", None)
    raw = (
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    if receipt != SAVED_RECEIPT or hashlib.sha256(raw).hexdigest() != SAVED_RECEIPT:
        raise ValueError("SAVED_SQUEEZE_RECEIPT_MISMATCH")
    if saved_report.get("source_inventory_sha256") != INVENTORY:
        raise ValueError("SAVED_SQUEEZE_SOURCE_MISMATCH")
    if saved_report.get("child_identity") != SAVED_OVERLAY:
        raise ValueError("SAVED_SQUEEZE_IDENTITY_MISMATCH")
    rows = saved_report.get("trade_rows")
    if not isinstance(rows, list) or len(rows) != 57:
        raise ValueError("SAVED_SQUEEZE_T_MISMATCH")
    if any(
        frame.attrs.get("source_inventory_sha256") != INVENTORY
        for frame in frames.values()
    ):
        raise ValueError("NATIVE_SOURCE_INVENTORY_MISMATCH")
    return _scan_rows(frames, rows)


def _scan_rows(
    frames: Mapping[str, pd.DataFrame], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    triggers: list[dict[str, Any]] = []
    trend_count = 0
    for trade in rows:
        if trade["regime"] != "TREND_DISPERSED":
            continue
        trend_count += 1
        signal = deepcopy(trade["signal"])
        if (
            signal["identity"] != SAVED_OVERLAY
            or signal["meta"].get("lifecycle_adapter_parent_identity")
            != positive.SQUEEZE_PARENT
        ):
            raise ValueError("SAVED_SIGNAL_PARENT_BINDING_MISMATCH")
        signal["identity"] = positive.SQUEEZE_PARENT
        frame = frames[str(trade["symbol"])]
        bound = bind_signal_low(signal, frame)
        records, index = execution._frame_records(frame, 30)
        entry_i = index.get(int(trade["entry_ts_ms"]))
        source_i = index.get(int(signal["signal_open_ts_ms"]))
        if entry_i is None or source_i is None or entry_i != source_i + 1:
            raise ValueError("SAVED_ENTRY_CLOCK_UNBOUND")
        entry = float(trade["entry_prices"][str(trade["symbol"])])
        if float(records[entry_i]["open"]) != entry:
            raise ValueError("SAVED_ENTRY_PRICE_UNBOUND")
        admission = positive.entry_update(bound, entry)
        if admission.get("reject"):
            raise ValueError("SAVED_ENTRY_REJECTED_BY_FROZEN_PARENT")
        stop = float(admission.get("stop_price", bound["stop_price"]))
        previous = records[source_i]
        for i in range(entry_i, len(records)):
            bar = records[i]
            if int(bar["open_ts_ms"]) >= int(trade["exit_ts_ms"]):
                break
            if not execution._can_follow(previous, bar):
                raise ValueError("SAVED_PATH_SOURCE_GAP")
            if int(bar["available_ts_ms"]) != int(bar["close_ts_ms"]):
                raise ValueError("SAVED_PATH_LATE_AVAILABILITY")
            # Existing current-bar stop and original earlier/same exit win.
            if float(bar["low"]) <= stop:
                stop_ts = int(
                    bar["open_ts_ms"]
                    if float(bar["open"]) < stop
                    else bar["close_ts_ms"]
                )
                if stop_ts < int(trade["exit_ts_ms"]):
                    raise ValueError("SAVED_PATH_EARLIER_STOP_CONFLICT")
                break
            if int(bar["close_ts_ms"]) >= int(trade["exit_ts_ms"]):
                break
            if float(bar["close"]) < float(bound["meta"][BINDING]["low"]):
                if i + 1 >= len(records) or not execution._can_follow(
                    bar, records[i + 1]
                ):
                    raise ValueError("INVALIDATION_NEXT_OPEN_UNVERIFIED")
                following = records[i + 1]
                if int(following["open_ts_ms"]) < int(trade["exit_ts_ms"]):
                    triggers.append(
                        {
                            "symbol": trade["symbol"],
                            "signal_ts_ms": int(signal["signal_ts_ms"]),
                            "frozen_signal_low": bound["meta"][BINDING]["low"],
                            "invalidation_available_ts_ms": int(bar["available_ts_ms"]),
                            "next_actual_open_ts_ms": int(following["open_ts_ms"]),
                            "diagnostic_original_exit_ts_ms": int(trade["exit_ts_ms"]),
                        }
                    )
                break
            previous = bar
    return {
        "successor_identity": SQUEEZE_SUCCESSOR,
        "state": "DIAGNOSTIC_TRIGGER_SCAN_ONLY_NOT_ECONOMIC_REPLAY",
        "saved_trend_trades_scanned": trend_count,
        "earlier_invalidation_count": len(triggers),
        "records": triggers,
        "old_candidate_replayed": False,
        "new_native_candidate_comparisons": 0,
        "economic_result": None,
        "full_required_only_if_earlier_trigger_count_positive": True,
        "zero_count_is_not_a_profit_or_survivor_pass": True,
    }
