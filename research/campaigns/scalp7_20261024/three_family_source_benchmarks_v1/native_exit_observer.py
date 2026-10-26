"""Incremental native conditions for virtual tracks, never historical fills.

Input is an already persisted producer decision. There is no source loader,
network, replay, order call, or execution-price calculation in this module.
All actions require a strictly later observed bid in the caller. Completed-bar
stop touches without an observed execution path censor rather than grant fills.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import time
from typing import Any

import benchmark as native

K117 = "K117_PRICE_ONLY_30M_NATIVE"
FOUR = 14_400_000
HALF = 1_800_000


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _number(value: Any) -> float:
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("NONFINITE_NATIVE_INPUT")
    return x


def _action(update: dict[str, Any]) -> dict[str, Any]:
    """Only actionable outputs affect whether an uncertain entry path agrees."""
    action = {key: update[key] for key in
            ("exit_next_open", "next_stop", "partial_fraction", "partial_price")
            if key in update}
    if update.get("exit_next_open"):
        action["reason"] = update.get("reason")
    return action


def evaluate_native_exit(track: dict[str, Any], decision: dict[str, Any], *,
                         k117_dependencies: Any = None,
                         decision_ms: int | None = None) -> dict[str, Any]:
    """Return state + native action intents; the caller owns later-bid fills.

    ``decision_ms`` is an injectable completion clock for synthetic tests only.
    Live callers omit it. ``k117_dependencies`` is the cached, pin-verified
    k117_adapter.dependencies() object, not an alternate exit implementation.
    No input object is mutated. Preserve the returned state in native_exit_state.
    """
    state = deepcopy(track.get("native_exit_state") or {})
    result: dict[str, Any] = {"state": state, "exit_event": None,
                            "stop_event": None, "partial_event": None,
                            "censor_reason": None}
    try:
        rule = track["rule_id"]
        if rule not in (native.TREND, native.MOM, K117):
            raise ValueError("UNSUPPORTED_NATIVE_IDENTITY")
        if decision.get("symbol") != track["symbol"]:
            raise ValueError("NATIVE_SYMBOL_MISMATCH")
        if rule != K117 and decision.get("rule_id") != rule:
            raise ValueError("NATIVE_RULE_MISMATCH")
        entry_ms = int(track.get("quote_read_at_ms", track["entry_quote_ts_ms"]))
        anchor = int(track["signal_close_ts_ms"])
        interval = HALF if rule == K117 else FOUR
        if anchor % interval or entry_ms < anchor:
            raise ValueError("NATIVE_ENTRY_CLOCK_INVALID")
        producer_ms = int(decision["decision_ts_ms"])
        payload = decision["native_exit_input"]
        bar = deepcopy(payload["bar"])
        if payload.get("source_bar_sha256") != digest(bar):
            raise ValueError("NATIVE_BAR_DIGEST_MISMATCH")
        opening, close = int(bar["open_ts_ms"]), int(bar["close_ts_ms"])
        available = int(bar.get("available_ts_ms", bar.get("observed_source_last_received_ms", 0)))
        if opening % interval or close != opening + interval or not close <= available <= producer_ms:
            raise ValueError("NATIVE_COMPLETED_BAR_CLOCK_INVALID")
        last = int(state.get("last_close_ts_ms", anchor))
        if close <= last or close <= entry_ms:
            return result
        if opening != last:
            raise ValueError("NATIVE_COMPLETED_BAR_SOURCE_GAP")
        if producer_ms < entry_ms:
            raise ValueError("NATIVE_EXIT_PREENTRY_DECISION")
        prices = {key: _number(bar[key]) for key in ("open", "high", "low", "close")}
        if (min(prices.values()) <= 0 or prices["high"] < max(prices.values()) or
                prices["low"] > min(prices.values())):
            raise ValueError("NATIVE_OHLC_INVALID")
        entry = _number(track["entry_ask_price"])
        risk = _number(track["initial_risk_price"])
        stop = _number(track.get("native_active_stop_price", track["base_stop_price"]))
        if min(entry, risk, stop) <= 0 or risk >= entry:
            raise ValueError("NATIVE_POSITION_RISK_INVALID")
        # Full OHLC cannot prove a causal executable bid. Quote stop handling
        # should already have closed a witnessed touch before this helper runs.
        if prices["low"] <= stop:
            raise ValueError("ENTRY_BAR_STOP_PATH_AMBIGUOUS" if opening < entry_ms
                             else "NATIVE_BAR_STOP_WITHOUT_QUOTE_PATH")
        hold_bars = (close - anchor) // interval
        state.update(last_close_ts_ms=close, hold_bars=hold_bars,
                     source_decision_sha256=digest(decision),
                     partial_entry_bar=opening < entry_ms)
        exit_reason = None
        update: dict[str, Any] = {}
        if rule in (native.TREND, native.MOM):
            _, maximum = native.safety(rule)
            if type(decision.get("native_exit_on_close")) is not bool:
                raise ValueError("NATIVE_CLOSE_PREDICATE_MISSING")
            if decision.get("native_safety_max_hold_bars") != maximum:
                raise ValueError("NATIVE_TIME_CAP_CHANGED")
            if hold_bars >= maximum:
                exit_reason = "MAX_HOLD_NEXT_OPEN"
            elif decision["native_exit_on_close"]:
                exit_reason = "GMMA_EMA15_BELOW_EMA30_NEXT_OPEN" if rule == native.TREND else "TSMOM_NEGATIVE_SCORE_NEXT_OPEN"
        else:
            if k117_dependencies is None:
                raise ValueError("K117_PIN_VERIFIED_CALLBACK_REQUIRED")
            signal = deepcopy(track["native_signal"])
            if int(signal["side"]) != 1:
                raise ValueError("K117_LONG_ONLY_VIRTUAL_TRACK")
            signal["identity"] = k117_dependencies.positive.KELTNER_PARENT
            source_bar = deepcopy(track["native_signal_bar"])
            if int(source_bar["available_ts_ms"]) > entry_ms:
                raise ValueError("K117_SIGNAL_NOT_KNOWN_AT_QUOTE_ENTRY")
            if int(source_bar["close_ts_ms"]) != anchor:
                raise ValueError("K117_SIGNAL_ENTRY_ANCHOR_MISMATCH")
            # The native bar clock is preserved; actual delayed quote time is
            # checked separately. Partial entry-bar extrema are bounded, never
            # silently treated as post-entry observations.
            bar["available_ts_ms"] = available
            full_mfe = max(0.0, (prices["high"] - entry) / risk)
            # A later quote cannot establish the high of an earlier native bar.
            # The optional snapshot is an accumulated post-entry MFE observed
            # no later than this close; otherwise only use a still-in-bar quote.
            quote_mfe = 0.0
            snapshot = track.get("native_observed_mfe_snapshot") or {}
            if snapshot and entry_ms <= int(snapshot["through_ts_ms"]) <= close:
                quote_mfe = _number(snapshot["mfe_R"])
            elif entry_ms <= int(track.get("last_quote_read_at_ms",
                                          track.get("last_quote_ts_ms", entry_ms))) <= close:
                quote_mfe = _number(track.get("best_observed_R", 0))
            observed = max(0.0, quote_mfe, (prices["close"] - entry) / risk)
            lower = max(float(state.get("mfe_lower_R", 0)), observed)
            upper = max(float(state.get("mfe_upper_R", 0)), full_mfe, lower)
            if opening >= entry_ms:
                lower = max(lower, full_mfe)
            state.update(mfe_lower_R=lower, mfe_upper_R=upper)
            remaining = _number(track.get("remaining_fraction", 1.0))
            if remaining not in (1.0, 0.9):
                raise ValueError("K117_NATIVE_REMAINING_FRACTION_INVALID")
            intended = float(state.get("remaining_intent", 1.0))
            if intended < remaining:
                raise ValueError("K117_NATIVE_PARTIAL_NOT_YET_OBSERVED_AT_BID")
            if remaining < intended:
                raise ValueError("K117_NATIVE_PARTIAL_WITHOUT_PRIOR_INTENT")

            def invoke(mfe: float, high: float) -> dict[str, Any]:
                # This is explicitly a virtual suffix-bound projection, not a
                # replacement source candle. The immutable source bar/hash and
                # its actual received-at clock remain in the evidence. Native
                # guards require both source-known-at-entry and post-entry bar;
                # using the earlier theoretical next-open would backdate entry.
                candidate = {**bar, "high": high,
                             "open_ts_ms": max(opening, entry_ms)}
                position = {"signal": signal, "side": 1, "entry_price": entry,
                            "entry_ts_ms": entry_ms, "initial_risk": risk,
                            "stop_price": stop, "hold_bars": hold_bars,
                            "mfe_R": mfe, "remaining": remaining}
                callback = k117_dependencies.structural(True).callback(signal, source_bar, [])
                history = k117_dependencies.pd.DataFrame([candidate])
                return callback(position, candidate, history)

            lower_high = max(entry, prices["close"], entry + observed * risk) if opening < entry_ms else prices["high"]
            update = invoke(lower, lower_high)
            possible = invoke(upper, prices["high"])
            if _action(update) != _action(possible):
                raise ValueError("K117_ENTRY_BAR_MFE_OR_PARTIAL_PATH_AMBIGUOUS")
            if update.get("exit_next_open"):
                exit_reason = str(update["reason"])
            elif hold_bars >= 50:
                exit_reason = "MAX_HOLD_NEXT_OPEN"

        completed_ms = int(time.time() * 1000) if decision_ms is None else int(decision_ms)
        if completed_ms < producer_ms:
            raise ValueError("NATIVE_HELPER_CLOCK_BEFORE_PRODUCER")
        common = {"rule_id": rule, "symbol": track["symbol"],
                  "decision_ts_ms": completed_ms, "source_decision_ts_ms": producer_ms,
                  "native_bar_close_ts_ms": close, "hold_bars": hold_bars,
                  "source_decision_sha256": digest(decision),
                  "source_bar_sha256": payload["source_bar_sha256"],
                  "native_condition_reuse": True, "native_next_open_fill_verified": False,
                  "entry_bar_suffix_bound_projection": opening < entry_ms,
                  "original_source_bar_open_ts_ms": opening,
                  "callback_bar_open_ts_ms": max(opening, entry_ms),
                  "actual_virtual_entry_read_at_ms": entry_ms,
                  "requires_strictly_later_observed_bid": True,
                  "real_broker_fill": False, "order_calls": 0}
        if "next_stop" in update:
            next_stop = max(stop, _number(update["next_stop"]))
            if next_stop > stop:
                result["stop_event"] = {**common, "reason": update["reason"],
                                        "next_stop_price": next_stop}
        if update.get("partial_fraction"):
            fraction = _number(update["partial_fraction"])
            if fraction != 0.10 or remaining != 1.0:
                raise ValueError("K117_FROZEN_PARTIAL_CHANGED")
            result["partial_event"] = {**common, "reason": "NATIVE_2R_PARTIAL_OBSERVED_CONDITION",
                                       "partial_fraction": fraction,
                                       "reference_native_partial_price": _number(update["partial_price"])}
            state["remaining_intent"] = 0.9
        if exit_reason:
            result["exit_event"] = {**common, "reason": exit_reason}
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        # Return the prior checkpoint on any failed/ambiguous observation.
        result.update(state=deepcopy(track.get("native_exit_state") or {}),
                      exit_event=None, stop_event=None, partial_event=None,
                      censor_reason=str(exc))
        return result
