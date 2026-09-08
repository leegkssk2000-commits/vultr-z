"""Independent D2 rules for Freqtrade 2026.7 offline engine comparison.

No native imports, stored trade inputs, future path evaluator, network or I/O.
Indicators and the virtual reservation clock read prefixes only. Actual held
state advances exclusively in Freqtrade's completed-candle callbacks.

Known irreducible comparison boundary: a native timeout fills at the completed
candle CLOSE; standard FT custom_exit fills at the following candle OPEN. The
target close is recorded separately, never substituted into an FT order.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import math

from pandas import DataFrame
from freqtrade.strategy import IStrategy

BAR = 14_400_000
HOLD = 12
DELAY = 6
UNCHECKED = "FIRST_LOW_BREACH_UNCHECKED"
SUPPRESSED = "LOW_EXIT_SUPPRESSED_FOR_THIS_POSITION"
ALLOWED = "LOW_EXIT_PENDING_NEXT_OPEN"


def bounded_ema(values, n):
    """First-value seeded EMA, reinitialized over exactly the last 4*n values."""
    result = []
    alpha = 2.0 / (n + 1.0)
    for i in range(len(values)):
        window = values[max(0, i - 4 * n + 1):i + 1]
        out = float(window[0])
        for value in window[1:]:
            out = alpha * float(value) + (1.0 - alpha) * out
        result.append(out)
    return result


def directional_half(row):
    return float(row["close"]) >= (float(row["high"]) + float(row["low"])) / 2.0


def prepare_causal(rows, start_ms, end_ms):
    """Prefix causal raw signals, wait/recheck and virtual reservations only.

    No actual position, fill, PnL, or future exit is simulated here. This can be
    vectorized ahead of backtesting because every event is a function of its
    completed prefix and the prespecified end calendar alone.
    """
    close = [float(r["close"]) for r in rows]
    e20, e50 = bounded_ema(close, 20), bounded_ema(close, 50)
    scheduled = {}
    active = None
    last_exit_index = -1
    last_reference_origin = None
    opportunities, references, reference_events, raw_signals = [], [], [], []
    eligible = [False] * len(rows)
    origins = [-1] * len(rows)
    for j, row in enumerate(rows):
        opened, closed = row["bar_open_ts"], row["bar_close_ts"]
        if (j and rows[j - 1]["bar_close_ts"] != opened) or closed != opened + BAR:
            raise ValueError("D2_NONCONTIGUOUS_SOURCE_CALENDAR")
        if closed > end_ms:
            raise ValueError("D2_SOURCE_EXCEEDS_FROZEN_END")
        if any(not math.isfinite(float(row[k])) for k in ("open", "high", "low", "close", "volume")):
            raise ValueError("D2_NONFINITE_SOURCE")
        if j >= 239 and start_ms <= closed < end_ms and e20[j] > e50[j] and close[j - 1] <= e20[j - 1] and close[j] > e20[j]:
            raw_signals.append({"signal_index": j, "signal_ts": closed})
            scheduled[j + DELAY] = {"original_signal_index": j, "origin_half": directional_half(row), "decision_index": j + DELAY}

        def emit(kind, ref, ts=closed, **extra):
            reference_events.append({"kind": kind, "index": j, "ts": ts,
                                     "reference_signal_index": ref["reference_signal_index"],
                                     "virtual_reference_only": True, **extra})

        if active is not None and active["phase"] == "PENDING_ENTRY_NEXT_OPEN":
            active.update(phase="HELD", entry_ts=opened)
            emit("REFERENCE_ENTRY_NEXT_OPEN", active, opened, modeled_entry=active["model_selected"])
        elif active is not None and active["phase"] == "PENDING_EMA_EXIT_NEXT_OPEN":
            active.update(phase="RELEASED", release_index=j, release_ts=opened,
                          release_reason="EMA20_NOT_ABOVE_EMA50_NEXT_OPEN")
            emit("REFERENCE_RELEASE_EMA_NEXT_OPEN", active, opened,
                 trigger_index=active["pending_exit_signal_index"])
            last_exit_index, last_reference_origin = j, active["reference_signal_index"]
            active = None

        if active is not None:
            if j == active["reference_signal_index"] + HOLD:
                if closed < end_ms:
                    active.update(phase="RELEASED", release_index=j, release_ts=closed,
                                  release_reason="ORIGINAL_TIME_STOP_CLOSE")
                    emit("REFERENCE_RELEASE_TIME_STOP_CLOSE", active)
                    last_exit_index, last_reference_origin = j, active["reference_signal_index"]
                    active = None
                else:
                    active["strict_end_timeout_pending"] = True
                    emit("REFERENCE_STRICT_END_TIMEOUT_UNCLOSED", active)
            elif e20[j] <= e50[j]:
                active.update(phase="PENDING_EMA_EXIT_NEXT_OPEN", pending_exit_signal_index=j,
                              pending_exit_signal_ts=closed)
                emit("REFERENCE_EMA_INVALIDATION_CLOSE", active, ema20=e20[j], ema50=e50[j])

        event = scheduled.get(j)
        if event is None:
            continue
        event = deepcopy(event)
        event.update(decision_ts=closed, recheck_half=directional_half(row),
                     admission=False, reference_created=False, exclusion_reason=None)
        if closed >= end_ms:
            event["exclusion_reason"] = "NO_DELAYED_NEXT_OPEN_IN_CALENDAR"
        elif active is not None:
            event.update(exclusion_reason="REFERENCE_OPPORTUNITY_RESERVED",
                         blocking_reference_signal_index=active["reference_signal_index"])
            emit("REFERENCE_BLOCKED_FOLLOWUP_SIGNAL", active, blocked_signal_index=j,
                 reason=event["exclusion_reason"], entry_predicate=event["origin_half"] and event["recheck_half"])
        elif j <= last_exit_index:
            event.update(exclusion_reason="REFERENCE_EXIT_BAR_OWNERSHIP",
                         blocking_reference_signal_index=last_reference_origin)
            emit("REFERENCE_BLOCKED_FOLLOWUP_SIGNAL", {"reference_signal_index": last_reference_origin},
                 blocked_signal_index=j, reason=event["exclusion_reason"],
                 entry_predicate=event["origin_half"] and event["recheck_half"])
        else:
            selected = event["origin_half"] and event["recheck_half"]
            active = {"reference_signal_index": j, "reservation_ts": closed,
                      "entry_index": j + 1, "native_hold_bars": HOLD,
                      "phase": "PENDING_ENTRY_NEXT_OPEN", "model_selected": selected,
                      "release_index": None, "release_ts": None, "release_reason": None,
                      "pending_exit_signal_index": None, "pending_exit_signal_ts": None,
                      "strict_end_timeout_pending": False, "virtual_reference_only": True}
            references.append(active)
            emit("REFERENCE_RESERVED_AT_SIGNAL_CLOSE", active, model_selected=selected, entry_predicate=selected)
            event.update(reference_created=True, shifted_reference_signal_index=j)
            if not selected:
                event["exclusion_reason"] = "ORIGIN_HALF_FAILED" if not event["origin_half"] else "DELAYED_HALF_RECHECK_FAILED"
            elif j + 1 >= len(rows):
                event["exclusion_reason"] = "NO_DELAYED_NEXT_OPEN_IN_CALENDAR"
            else:
                event["admission"] = True  # Reference eligibility; FT decides actual occupancy.
                eligible[j] = True
                origins[j] = event["original_signal_index"]
        opportunities.append(event)
    return {"ema20": e20, "ema50": e50, "eligible": eligible, "origins": origins,
            "raw_signals": raw_signals, "opportunity_events": opportunities,
            "reference_opportunities": references, "reference_events": reference_events}


def new_position(origin, anchor, signal_low, entry_rate):
    return {"original_signal_index": origin, "decision_index": anchor,
            "exit_anchor_index": anchor, "entry_index": anchor + 1,
            "entry_price": entry_rate, "frozen_signal_low": signal_low,
            "low_exit_state": {"status": UNCHECKED}, "extension_allowed": False,
            "extension_decided": False, "final_exit_index": anchor + HOLD,
            "last_processed_index": anchor, "pending_reason": None}


def step_completed(position, row, index, ema20, ema50, end_ms):
    """Observe exactly one held close. Returns a requested exit, never a fill."""
    if index <= position["last_processed_index"]:
        return None, []
    if index != position["last_processed_index"] + 1:
        raise ValueError("D2_HELD_CALLBACK_GAP")
    position["last_processed_index"] = index
    closed = row["bar_close_ts"]
    trace = []
    if index == position["final_exit_index"]:
        if closed >= end_ms:
            trace.append({"kind": "STRICT_END_TIMEOUT_CENSORED", "index": index, "ts": closed})
            return None, trace
        native_kind = "RUNNER_FINAL_TIME_STOP_CLOSE" if position["extension_allowed"] else "ORIGINAL_TIME_STOP_CLOSE"
        trace.append({"kind": native_kind, "index": index, "ts": closed, "price": float(row["close"]),
                      "native_target_only": True, "ft_fill_semantics": "FOLLOWING_OPEN_NOT_NATIVE_CLOSE"})
        position["pending_reason"] = native_kind
        return native_kind, trace

    observed, low = float(row["close"]), position["frozen_signal_low"]
    ema_hit = ema20 <= ema50
    low_hit = observed < low
    state = position["low_exit_state"]
    if not ema_hit and state["status"] == UNCHECKED and low_hit:
        state = {"status": ALLOWED if observed < ema50 else SUPPRESSED,
                 "index": index, "ts": closed, "observed_close": observed,
                 "ema50": ema50, "signal_low": low}
        position["low_exit_state"] = state
        trace.append({"kind": "FIRST_LOW_BREACH_CONTEXT", **deepcopy(state)})
    active_low = low_hit and state["status"] == ALLOWED
    late_failure = state["status"] == SUPPRESSED and index > state["index"] and observed < low and observed < ema50
    runner_hit = position["extension_allowed"] and index >= position["exit_anchor_index"] + HOLD and observed <= ema20
    if not (ema_hit or active_low or runner_hit or late_failure):
        if index == position["exit_anchor_index"] + HOLD - 1:
            allowed = state["status"] != SUPPRESSED and observed > position["entry_price"] and observed > ema20 > ema50
            position.update(extension_decided=True, extension_allowed=allowed)
            if allowed:
                position["final_exit_index"] = position["exit_anchor_index"] + 2 * HOLD
            trace.append({"kind": "RUNNER_T_MINUS_ONE_DECISION", "index": index, "ts": closed,
                          "allowed": allowed, "observed_close": observed, "entry_price": position["entry_price"],
                          "ema20": ema20, "ema50": ema50, "m2_state_at_decision": state["status"]})
        return None, trace
    reason = ("EMA20_NOT_ABOVE_EMA50_NEXT_OPEN" if ema_hit else
              "CONTEXT_SIGNAL_LOW_INVALIDATION_NEXT_OPEN" if active_low else
              "RUNNER_EMA20_NEXT_OPEN" if runner_hit else
              "POST_SUPPRESSION_STRUCTURE_FAILURE_NEXT_OPEN")
    kind = ("TREND_INVALIDATION_CLOSE" if ema_hit else "CONTEXT_SIGNAL_LOW_INVALIDATION_CLOSE" if active_low else
            "RUNNER_CLOSE_NOT_ABOVE_EMA20" if runner_hit else "POST_SUPPRESSION_STRUCTURE_FAILURE_CLOSE")
    trace.append({"kind": kind, "index": index, "ts": closed, "observed_close": observed,
                  "ema20": ema20, "ema50": ema50, "signal_low": low,
                  "ema_condition": ema_hit, "low_condition": low_hit, "runner_condition": runner_hit,
                  "post_suppression_failure": late_failure})
    if closed >= end_ms:
        return None, trace
    position["pending_reason"] = reason
    return reason, trace


class D2Independent(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False
    startup_candle_count = 0  # Original fixed index 239, using full canonical prefix.
    process_only_new_candles = True
    minimal_roi = {}
    stoploss = -1.0  # FT-required sentinel; no positive-price protective SL.
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = False
    order_types = {"entry": "market", "exit": "market", "stoploss": "market", "stoploss_on_exchange": False}
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def __init__(self, config):
        super().__init__(config)
        self.audit = {"pairs": {}, "trace": [], "entries": [], "exits": [], "callback_errors": []}
        self._held = {}
        self._last_exit = {}
        self._start = int(config["zel_start_ms"])
        self._end = int(config["zel_end_ms"])

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        rows = []
        for j, row in enumerate(frame.to_dict("records")):
            opened = int(row["date"].timestamp() * 1000)
            rows.append({"bar_open_ts": opened, "bar_close_ts": opened + BAR,
                         **{k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}})
        built = prepare_causal(rows, self._start, self._end)
        frame["zel_index"] = range(len(frame))
        frame["zel_origin"] = built["origins"]
        frame["zel_eligible"] = built["eligible"]
        frame["zel_ema20"] = built["ema20"]
        frame["zel_ema50"] = built["ema50"]
        self.audit["pairs"][metadata["pair"]] = {k: v for k, v in built.items() if k not in ("ema20", "ema50", "eligible", "origins")}
        return frame

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = dataframe["zel_eligible"].astype(int)
        dataframe["enter_tag"] = [f"d2:{int(o)}:{int(j)}" if ok else None for o, j, ok in zip(dataframe["zel_origin"], dataframe["zel_index"], dataframe["zel_eligible"])]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def _latest(self, pair, current_time):
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        # The extra filter is an explicit guard even if a custom data provider
        # incorrectly exposes the active candle or its later suffix.
        cutoff = current_time - timedelta(milliseconds=BAR)
        visible = frame.loc[frame["date"] <= cutoff]
        return None if visible.empty else visible.iloc[-1]

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        stamp = int(current_time.timestamp() * 1000)
        return side == "long" and stamp < self._end and stamp > self._last_exit.get(pair, -1)

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        stamp = int(current_time.timestamp() * 1000)
        if order.ft_order_side == trade.entry_side:
            row = self._latest(pair, current_time)
            _, origin, anchor = trade.enter_tag.split(":")
            if row is None or int(row["zel_index"]) != int(anchor):
                raise ValueError("D2_ENTRY_FEATURE_CALLBACK_TIME_MISMATCH")
            self._held[trade.id] = new_position(int(origin), int(anchor), float(row["low"]), float(trade.open_rate))
            self.audit["entries"].append({"pair": pair, "trade_id": trade.id,
                                         "original_signal_index": int(origin), "decision_index": int(anchor),
                                         "ts": stamp, "price": float(trade.open_rate)})
        elif order.ft_order_side == trade.exit_side:
            self._last_exit[pair] = stamp
            self.audit["exits"].append({"pair": pair, "trade_id": trade.id, "ts": stamp,
                                       "price": float(order.safe_price), "exit_reason": trade.exit_reason})

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        try:
            position = self._held.get(trade.id)
            if position is None:
                raise ValueError("D2_HELD_STATE_NOT_INITIALIZED")
            row = self._latest(pair, current_time)
            if row is None or int(row["zel_index"]) < position["entry_index"]:
                return None
            observed = {"bar_close_ts": int(row["date"].timestamp() * 1000) + BAR,
                        **{k: float(row[k]) for k in ("open", "high", "low", "close")}}
            reason, events = step_completed(position, observed, int(row["zel_index"]), float(row["zel_ema20"]), float(row["zel_ema50"]), self._end)
            self.audit["trace"].extend({"pair": pair, "trade_id": trade.id,
                                       "original_signal_index": position["original_signal_index"],
                                       "decision_index": position["decision_index"], **ev} for ev in events)
            return reason
        except Exception as exc:
            self.audit["callback_errors"].append({"pair": pair, "trade_id": trade.id,
                                                  "type": type(exc).__name__, "message": str(exc)})
            raise
