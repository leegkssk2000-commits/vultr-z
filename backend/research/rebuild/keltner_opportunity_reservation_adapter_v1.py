"""Causal D opportunity reservation on the frozen N entry and D exit.

The reference clock consumes one completed source bar at a time. It never calls
the batch path evaluator and carries neither prices for fills nor money. Only
after this clock has finished deciding admission does the frozen D evaluator
value the selected actual M positions. No historical trade list is an input.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from backend.research.rebuild import keltner_cumulative_entry_adapter_v1 as n

previous = n.previous
BAR, HOLD, LANE = previous.BAR, previous.HOLD, previous.LANE
RULE_ID = "KELTNER_D_CAUSAL_OPPORTUNITY_RESERVATION_DEV_V1"
REFERENCE_VETO_REASON = "REFERENCE_OPPORTUNITY_RESERVED"
EXIT_BAR_VETO_REASON = "REFERENCE_EXIT_BAR_OWNERSHIP"
SCHEMA = "KELTNER_D_REFERENCE_CLOCK_V1"


def build_bundle(rows, parent_spec, *, eval_start_ms, eval_end_ms):
    return n.build_bundle(rows, parent_spec, eval_start_ms=eval_start_ms,
                          eval_end_ms=eval_end_ms)


def initial_clock(*, eval_start_ms, eval_end_ms):
    if (type(eval_start_ms) is not int or type(eval_end_ms) is not int
            or eval_start_ms >= eval_end_ms or eval_start_ms % BAR
            or eval_end_ms % BAR):
        raise RuntimeError("KELTNER_REFERENCE_CALENDAR_INVALID")
    return {"schema": SCHEMA, "eval_start_ms": eval_start_ms,
            "eval_end_ms": eval_end_ms, "last_index": -1,
            "last_close_ts": None, "processed_input_sha256": [],
            "active_opportunity_offset": None, "last_exit_index": -1,
            "last_released_reference_signal_index": None,
            "reference_opportunities": [], "reference_events": [],
            "opportunity_events": [], "admitted_signal_indices": [],
            "modeled_entry_signal_indices": []}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _bar_input(row, index, ema20, ema50, signal, start, end):
    """Validate and select only clock inputs, never economic outcome fields."""
    if type(index) is not int or index < 0:
        raise RuntimeError("KELTNER_REFERENCE_INDEX_INVALID")
    opened, closed = row.get("bar_open_ts"), row.get("bar_close_ts")
    if (type(opened) is not int or type(closed) is not int or opened % BAR
            or closed != opened + BAR or closed > end):
        raise RuntimeError("KELTNER_REFERENCE_TIMESTAMP_INVALID_OR_FUTURE")
    # Shared whole-input validation is also used by causal_clock; direct stream
    # callers receive the same no-missing/nonfinite/invalid-OHLC guarantee here.
    values = {key: row.get(key) for key in ("open", "high", "low", "close", "volume")}
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values.values()):
        raise RuntimeError("KELTNER_REFERENCE_PRICE_MISSING_OR_NONFINITE")
    if (any(values[key] <= 0 for key in ("open", "high", "low", "close"))
            or values["volume"] < 0
            or not values["low"] <= min(values["open"], values["close"])
            or not max(values["open"], values["close"]) <= values["high"]):
        raise RuntimeError("KELTNER_REFERENCE_OHLC_INVALID")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 0 for v in (ema20, ema50)):
        raise RuntimeError("KELTNER_REFERENCE_FEATURE_MISSING_OR_NONFINITE")
    if signal is not None and (set(signal) != {"signal_index", "signal_ts"}
            or signal["signal_index"] != index or type(signal["signal_index"]) is not int
            or signal["signal_ts"] != closed
            or not start <= closed < end):
        raise RuntimeError("KELTNER_REFERENCE_SIGNAL_INVALID_OR_FUTURE")
    return {"index": index, "bar_open_ts": opened, "bar_close_ts": closed,
            **values, "ema20": ema20, "ema50": ema50,
            "signal": deepcopy(signal)}


def _emit(state, kind, index, ts, reference_signal_index, **extra):
    event = {"kind": kind, "index": index, "ts": ts,
             "reference_signal_index": reference_signal_index,
             "virtual_reference_only": True, **extra}
    state["reference_events"].append(event)


def advance_clock(state, row, *, index, ema20, ema50, signal=None):
    """Apply one completed bar, in place, and return whether it was new.

    A checkpoint contains all prior decisions and the input fingerprints. An
    identical already-applied bar is an idempotent no-op; a changed duplicate,
    skipped source index, timestamp gap, or changed calendar is rejected. The
    direct API takes only this row and its already-computed causal EMA values.
    """
    if state.get("schema") != SCHEMA:
        raise RuntimeError("KELTNER_REFERENCE_CHECKPOINT_SCHEMA")
    start, end = state["eval_start_ms"], state["eval_end_ms"]
    value = _bar_input(row, index, ema20, ema50, signal, start, end)
    digest = _hash(value)
    if index <= state["last_index"]:
        if state["processed_input_sha256"][index] != digest:
            raise RuntimeError("KELTNER_REFERENCE_REPROCESSED_INPUT_CHANGED")
        return False
    if index != state["last_index"] + 1:
        raise RuntimeError("KELTNER_REFERENCE_INDEX_GAP_OR_ORDER")
    if state["last_close_ts"] is None:
        if row["bar_open_ts"] > start:
            raise RuntimeError("KELTNER_REFERENCE_INPUT_COVERAGE")
    elif row["bar_open_ts"] != state["last_close_ts"]:
        raise RuntimeError("KELTNER_REFERENCE_GAP_DUPLICATE_OR_ORDER")

    # All validation precedes mutation. Entry/open and a previously observed
    # EMA exit/open happen before this bar's close becomes available.
    offset = state["active_opportunity_offset"]
    active = None if offset is None else state["reference_opportunities"][offset]
    if active is not None and active["phase"] == "PENDING_ENTRY_NEXT_OPEN":
        if index != active["entry_index"] or row["bar_open_ts"] >= end:
            raise RuntimeError("KELTNER_REFERENCE_PENDING_ENTRY_CLOCK")
        active.update(phase="HELD", entry_ts=row["bar_open_ts"])
        _emit(state, "REFERENCE_ENTRY_NEXT_OPEN", index, row["bar_open_ts"],
              active["reference_signal_index"], modeled_entry=active["model_selected"])
        if active["model_selected"]:
            state["modeled_entry_signal_indices"].append(active["reference_signal_index"])
    elif active is not None and active["phase"] == "PENDING_EMA_EXIT_NEXT_OPEN":
        if (index != active["pending_exit_signal_index"] + 1
                or row["bar_open_ts"] >= end):
            raise RuntimeError("KELTNER_REFERENCE_PENDING_EXIT_CLOCK")
        active.update(phase="RELEASED", release_index=index,
                      release_ts=row["bar_open_ts"],
                      release_reason="EMA20_NOT_ABOVE_EMA50_NEXT_OPEN")
        _emit(state, "REFERENCE_RELEASE_EMA_NEXT_OPEN", index, row["bar_open_ts"],
              active["reference_signal_index"],
              trigger_index=active["pending_exit_signal_index"])
        state["last_exit_index"] = index
        state["last_released_reference_signal_index"] = active["reference_signal_index"]
        state["active_opportunity_offset"] = None
        active = None

    if active is not None:
        native_exit = active["reference_signal_index"] + HOLD
        # This is the original known twelve-bar timeout, never an inferred
        # future EMA release time. Timeout at this close precedes a new trigger.
        if index == native_exit:
            if row["bar_close_ts"] < end:
                active.update(phase="RELEASED", release_index=index,
                              release_ts=row["bar_close_ts"],
                              release_reason="ORIGINAL_TIME_STOP_CLOSE")
                _emit(state, "REFERENCE_RELEASE_TIME_STOP_CLOSE", index,
                      row["bar_close_ts"], active["reference_signal_index"])
                state["last_exit_index"] = index
                state["last_released_reference_signal_index"] = active["reference_signal_index"]
                state["active_opportunity_offset"] = None
                active = None
            else:
                active["strict_end_timeout_pending"] = True
                _emit(state, "REFERENCE_STRICT_END_TIMEOUT_UNCLOSED", index,
                      row["bar_close_ts"], active["reference_signal_index"])
        elif ema20 <= ema50:
            active.update(phase="PENDING_EMA_EXIT_NEXT_OPEN",
                          pending_exit_signal_index=index,
                          pending_exit_signal_ts=row["bar_close_ts"])
            _emit(state, "REFERENCE_EMA_INVALIDATION_CLOSE", index,
                  row["bar_close_ts"], active["reference_signal_index"],
                  ema20=ema20, ema50=ema50)

    if signal is not None:
        observation = n.entry_observation(row)
        event = dict(signal, admission=False, status="EXCLUDED", exclusion_reason=None,
                     entry_observation=observation, reference_eligible=False,
                     reservation_created=False)
        if active is not None:
            event.update(exclusion_reason=REFERENCE_VETO_REASON,
                         blocking_reference_signal_index=active["reference_signal_index"],
                         blocking_reference_model_selected=active["model_selected"])
        elif index <= state["last_exit_index"]:
            event.update(exclusion_reason=EXIT_BAR_VETO_REASON,
                         blocking_reference_signal_index=state["last_released_reference_signal_index"])
        else:
            selected = observation[n.FEATURE]
            opportunity = {"reference_signal_index": index,
                           "reservation_ts": row["bar_close_ts"],
                           "entry_index": index + 1,
                           "native_hold_bars": HOLD,
                           "phase": "PENDING_ENTRY_NEXT_OPEN",
                           "model_selected": selected,
                           "release_index": None, "release_ts": None,
                           "release_reason": None,
                           "pending_exit_signal_index": None,
                           "pending_exit_signal_ts": None,
                           "strict_end_timeout_pending": False,
                           "virtual_reference_only": True}
            state["active_opportunity_offset"] = len(state["reference_opportunities"])
            state["reference_opportunities"].append(opportunity)
            _emit(state, "REFERENCE_RESERVED_AT_SIGNAL_CLOSE", index,
                  row["bar_close_ts"], index, model_selected=selected,
                  entry_predicate=observation[n.FEATURE])
            event.update(reference_eligible=True, reservation_created=True,
                         reference_signal_index=index)
            if selected:
                state["admitted_signal_indices"].append(index)
                event.update(admission=True, status="PENDING", exclusion_reason=None)
            else:
                event["exclusion_reason"] = n.VETO_REASON
        state["opportunity_events"].append(event)
        if event["exclusion_reason"] in (REFERENCE_VETO_REASON, EXIT_BAR_VETO_REASON):
            _emit(state, "REFERENCE_BLOCKED_FOLLOWUP_SIGNAL", index,
                  row["bar_close_ts"], event["blocking_reference_signal_index"],
                  blocked_signal_index=index, reason=event["exclusion_reason"],
                  entry_predicate=observation[n.FEATURE])

    state["last_index"] = index
    state["last_close_ts"] = row["bar_close_ts"]
    state["processed_input_sha256"].append(digest)
    return True


def causal_clock(rows, bundle, *, eval_start_ms, eval_end_ms,
                 checkpoint=None, stop_after_index=None):
    """Chronological admission only; no fill, path, costs or economic result.

    ``stop_after_index`` supports a synthetic interrupted run under the already
    fixed evaluation calendar. Reapplying the prefix to its JSON checkpoint is
    safe and resumes without duplicate reservations or modeled entries.
    """
    # Reuse the exact frozen row/feature/signal validation without evaluating a
    # single path. This call does not decide reference or actual admission.
    previous.replay(rows, bundle, eval_start_ms=eval_start_ms,
                    eval_end_ms=eval_end_ms, enable_change=True,
                    fixed_signal_indices=[])
    if (stop_after_index is not None and (type(stop_after_index) is not int
            or not 0 <= stop_after_index < len(rows))):
        raise RuntimeError("KELTNER_REFERENCE_STOP_INDEX_INVALID")
    state = (initial_clock(eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
             if checkpoint is None else deepcopy(checkpoint))
    if (state.get("schema") != SCHEMA or state.get("eval_start_ms") != eval_start_ms
            or state.get("eval_end_ms") != eval_end_ms
            or state.get("last_index", -1) >= len(rows)):
        raise RuntimeError("KELTNER_REFERENCE_CHECKPOINT_CALENDAR_OR_LENGTH")
    signals = {s["signal_index"]: s for s in bundle["signals"]}
    last = len(rows) - 1 if stop_after_index is None else stop_after_index
    for index in range(last + 1):
        advance_clock(state, rows[index], index=index,
                      ema20=bundle["ema20"][index], ema50=bundle["ema50"][index],
                      signal=signals.get(index))
    return state


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enabled=True,
           reference_checkpoint=None):
    """Full M replay; disabled mode is byte-equivalent raw N, including tail."""
    if type(enabled) is not bool:
        raise RuntimeError("KELTNER_REFERENCE_ENABLE_BOOL_REQUIRED")
    if not enabled:
        if reference_checkpoint is not None:
            raise RuntimeError("KELTNER_REFERENCE_DISABLED_CHECKPOINT_FORBIDDEN")
        return n.replay(rows, bundle, eval_start_ms=eval_start_ms,
                        eval_end_ms=eval_end_ms, enabled=True)
    clock = causal_clock(rows, bundle, eval_start_ms=eval_start_ms,
                         eval_end_ms=eval_end_ms, checkpoint=reference_checkpoint)
    selected = set(clock["admitted_signal_indices"])
    if clock["admitted_signal_indices"] != clock["modeled_entry_signal_indices"]:
        raise RuntimeError("KELTNER_REFERENCE_UNEXECUTED_ALLOWED_ENTRY")
    # No value from this batch evaluator can change the clock above. Its only
    # job is frozen D fills/held geometry/terminal marks for causal M admission.
    selected_bundle = dict(bundle, signals=[s for s in bundle["signals"]
                                           if s["signal_index"] in selected])
    result = previous.replay(rows, selected_bundle, eval_start_ms=eval_start_ms,
                             eval_end_ms=eval_end_ms, enable_change=True)
    executed = {e["signal_index"]: e for e in result["events"]}
    if any(e["status"] == "EXCLUDED" for e in executed.values()):
        raise RuntimeError("KELTNER_REFERENCE_CAUSAL_ADMISSION_PATH_DISAGREEMENT")
    events = deepcopy(clock["opportunity_events"])
    for event in events:
        if event["signal_index"] in selected:
            event.update(executed[event["signal_index"]])
    result["events"] = events
    result["reference_events"] = deepcopy(clock["reference_events"])
    result["reference_opportunities"] = deepcopy(clock["reference_opportunities"])
    # An inert resumable checkpoint is diagnostic state, never an economic
    # position, fee, funding, quantity or exposure input to the shared account.
    result["reference_checkpoint"] = clock
    result["audit"].update(
        rule=RULE_ID, comparison_type="ENTRY_FILTER",
        change_axis="CAUSAL_D_OPPORTUNITY_RESERVATION", occupancy_change=True,
        comparison_mode="FULL_CHRONOLOGICAL_CAUSAL_REFERENCE",
        reservation_enabled=True, entry_rule=n.RULE_ID, exit_rule=previous.RULE_ID,
        original_signal_count=len(bundle["signals"]), raw_signals=len(events),
        original_signal_denominator_preserved=True,
        reference_reservation_count=len(clock["reference_opportunities"]),
        reference_rejected_reservation_count=sum(not r["model_selected"]
                                               for r in clock["reference_opportunities"]),
        reference_released_count=sum(r["phase"] == "RELEASED"
                                     for r in clock["reference_opportunities"]),
        reference_open_count=int(clock["active_opportunity_offset"] is not None),
        modeled_entry_count=len(clock["modeled_entry_signal_indices"]),
        raw_below_half_signal_count=sum(not e["entry_observation"][n.FEATURE] for e in events),
        entry_veto_count=sum(e["exclusion_reason"] == n.VETO_REASON for e in events),
        reference_occupancy_exclusion_count=sum(e["exclusion_reason"] == REFERENCE_VETO_REASON
                                              for e in events),
        reference_exit_bar_exclusion_count=sum(e["exclusion_reason"] == EXIT_BAR_VETO_REASON
                                             for e in events),
        excluded=sum(e["status"] == "EXCLUDED" for e in events),
        reference_virtual_quantity=0, reference_virtual_notional=0,
        reference_virtual_trade_count=0, reference_virtual_fee_bps=0,
        reference_virtual_funding_bps=0, reference_virtual_exposure_ms=0,
        historical_trade_or_exit_inputs=False, reference_reads_batch_path=False,
        independent_symbol_state=True, resumable_idempotent_reference=True,
        original_entry_predicate_unchanged=True, original_exit_rule_unchanged=True)
    if len(result["trades"]) + len(result["open_positions"]) + result["audit"]["excluded"] != len(events):
        raise RuntimeError("KELTNER_REFERENCE_OPPORTUNITY_ACCOUNTING")
    return result
