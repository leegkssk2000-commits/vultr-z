"""One DEV Q0 continuation: advance its protective SL on later prepared UPs.

The preserved Q0 signal and single-position replay supply every original
entry, fallback exit and open mark. This adapter changes only a held position's
protective level, never generates signals, loads data, charges costs or selects
parameters. Fixed origins are independent diagnostic positions; full replay
retains Q0's chronological ownership and close/open phases.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from backend.research.rebuild import break_channel_structure_v1 as q0

INTERVAL = q0.INTERVAL
RULE_ID = "Q1_CONFIRMED_PREPARED_CHANNEL_LOWER_RATCHET_NEXT_OPEN"


def _replace_exit(rows, origin, index, price, stamp, reason, stop, *, intrabar):
    """Use the unchanged evaluator for only actually held completed bars."""
    held = index if intrabar else index - 1
    signal = origin["entry_signal_metadata"]
    result = q0.old.common.evaluate_development_events(
        rows, [signal["signal_index"]], split_start_ms=rows[0]["bar_open_ts"],
        split_end_ms=rows[-1]["bar_close_ts"] + INTERVAL,
        interval_ms=INTERVAL, hold_bars=held - signal["signal_index"])
    if len(result["trades"]) != 1 or result["exclusions"]:
        raise RuntimeError("Q1_SHARED_GEOMETRY_UNAVAILABLE")
    trade = dict(result["trades"][0])
    for field in ("entry_stop_price", "channel_anchor_ts", "channel_upper",
                  "channel_lower", "preparation", "holding_limit",
                  "initial_risk_design", "entry_signal_metadata"):
        trade[field] = deepcopy(origin[field])
    gross = (price / trade["entry_price"] - 1.0) * 10000.0
    trade.update(exit_index=index, exit_ts=stamp, exit_price=price,
                 gross_bps=gross, hold_ms=stamp - trade["entry_ts"],
                 mfe_bps=max(trade["mfe_bps"], gross, 0.0),
                 mae_bps=min(trade["mae_bps"], gross, 0.0),
                 exit_reason=reason,
                 exit_timestamp_semantics=("CLOSED_EXIT_BAR_UPPER_BOUND" if intrabar
                                           else "OBSERVED_4H_OPEN"),
                 excursion_semantics=("FULL_EXIT_BAR_BOUND_POSSIBLY_POST_STOP_DIAGNOSTIC_ONLY"
                                      if intrabar else "HELD_COMPLETED_BARS_AND_EXIT_OPEN_ONLY"),
                 intrabar_stop_timing_unknown=intrabar,
                 effective_exit_stop_price=stop, q1_rule=RULE_ID)
    return trade


def _ratchet_path(rows, origin, signals):
    """Causal scan; fallback outcomes never determine the exit condition.

    Read the original entry metadata, then process opens, intrabar protection
    and finally closed UP/DOWN signals in that order. Neither the fallback
    final profit nor its future excursion or exit price is an input feature.
    """
    initial = float(origin["entry_stop_price"])
    stop = initial
    pending_stop = pending_bear = None
    by_index = {}
    for signal in signals:
        by_index.setdefault(signal["signal_index"], []).append(signal)
    entry_index = origin["entry_index"]
    trace = [{"kind": "ENTRY_NEXT_OPEN", "index": entry_index,
              "ts": origin["entry_ts"], "price": origin["entry_price"],
              "signal_index": origin["signal_index"], "entry_stop_price": initial}]

    def record(kind, index, **values):
        trace.append({"kind": kind, "index": index,
                      "signal_index": origin["signal_index"], **values})

    def finish(index, price, stamp, reason, intrabar=False):
        trade = _replace_exit(rows, origin, index, price, stamp, reason,
                              stop, intrabar=intrabar)
        record(reason, index, ts=stamp, price=price,
               entry_stop_price=initial, effective_stop_price=stop)
        return trade, None, trace

    for index in range(entry_index, len(rows)):
        row = rows[index]
        stamp, price = row["bar_open_ts"], float(row["open"])
        if pending_stop is not None:
            new_stop, trigger = pending_stop
            if new_stop <= stop:
                raise RuntimeError("Q1_NON_INCREASING_PENDING_RATCHET")
            previous = stop
            stop = new_stop
            record("Q1_RATCHET_ACTIVATED_NEXT_OPEN", index, ts=stamp,
                   previous_stop_price=previous, effective_stop_price=stop,
                   trigger_signal_index=trigger["signal_index"],
                   trigger_signal_ts=trigger["signal_ts"])
            pending_stop = None
        if price <= stop:
            reason = ("Q1_RATCHET_STOP_GAP_OPEN" if stop > initial
                      else "PROTECTIVE_STOP_GAP_OPEN")
            return finish(index, price, stamp, reason)
        if pending_bear is not None:
            return finish(index, price, stamp, "BEARISH_CONFIRMED_NEXT_OPEN")
        if float(row["low"]) <= stop:
            reason = ("Q1_RATCHET_STOP_INTRABAR" if stop > initial
                      else "PROTECTIVE_STOP_INTRABAR")
            return finish(index, stop, row["bar_close_ts"], reason, True)
        current = by_index.get(index, [])
        for signal in current:
            if signal["direction"] == "DOWN":
                pending_bear = signal
                record("BEARISH_CLOSE_CONFIRMED", index, ts=signal["signal_ts"])
            elif signal["signal_ts"] > origin["entry_ts"]:
                if signal.get("preparation") is not True:
                    raise RuntimeError("Q1_REQUIRES_ORIGINAL_PREPARED_UP")
                proposed = float(signal["lower"])
                raised = proposed > stop
                record("Q1_HELD_PREPARED_UP_OBSERVED", index, ts=signal["signal_ts"],
                       proposed_stop_price=proposed, current_stop_price=stop,
                       update_scheduled=raised, trigger_signal_index=index)
                if raised:
                    pending_stop = (proposed, signal)
    # The original engine supplies the exact unfinished geometry. A closed
    # fallback here means the explicit scan lost an original exit: fail closed.
    if "mark_ts" not in origin:
        raise RuntimeError("Q1_ORIGINAL_EXIT_CHRONOLOGY_MISMATCH")
    opened = deepcopy(origin)
    opened.update(effective_mark_stop_price=stop, q1_rule=RULE_ID,
                  pending_exit_signal_ts=(pending_bear["signal_ts"] if pending_bear else None))
    record("TERMINAL_MARK", len(rows) - 1, ts=opened["mark_ts"],
           price=opened["mark_price"], effective_stop_price=stop)
    return None, opened, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enable_change=True,
           fixed_signal_indices=None):
    """Q1 full chronological replay or independent specified Q0 origins.

    At a signal close, a position stopped during that very bar is already
    flat. A position due to exit at the following open is still occupied.
    Hence signal_index < exit_index excludes, while equality can enter later.
    Fixed origins bypass only ownership between diagnostic positions; each
    preserves original entry eligibility and observes every original UP.
    """
    if type(enable_change) is not bool:
        raise RuntimeError("Q1_ENABLE_BOOL_REQUIRED")
    # Preserve authoritative bar, timestamp, signal and boundary validation.
    q0.replay(rows, bundle, eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
    usable = [r for r in rows if r["bar_close_ts"] <= eval_end_ms]
    signals = bundle["signals"]
    bullish = [s for s in signals if s["direction"] == "UP"]
    down = [s for s in signals if s["direction"] == "DOWN"]
    down_indices = {s["signal_index"] for s in down}
    fixed = fixed_signal_indices is not None
    if fixed:
        indices = list(fixed_signal_indices)
        if (any(type(i) is not int for i in indices) or len(set(indices)) != len(indices)
                or not set(indices) <= {s["signal_index"] for s in bullish}):
            raise RuntimeError("Q1_FIXED_ORIGIN_SET_INVALID")
        wanted = set(indices)
        bullish = [s for s in bullish if s["signal_index"] in wanted]
    trades, opened, events, trace = [], [], [], []
    counts = Counter()
    last_exit_index = -1
    terminal_occupied = False
    for signal in bullish:
        index = signal["signal_index"]
        event = {"direction": "UP", "signal_index": index,
                 "signal_ts": signal["signal_ts"], "admission": True,
                 "status": "PENDING", "exclusion_reason": None,
                 "features": deepcopy(signal)}
        if index in down_indices:
            event.update(status="EXCLUDED", exclusion_reason="OPPOSITE_SIGNAL_PRIORITY")
            counts["simultaneous_confirmation_conflicts"] += 1
        elif not fixed and (terminal_occupied or index < last_exit_index):
            event.update(status="EXCLUDED", exclusion_reason="SIGNAL_DURING_OPEN")
        else:
            one_signals = sorted(down + [signal], key=lambda s: (
                s["signal_ts"], 0 if s["direction"] == "DOWN" else 1))
            raw = q0.replay(rows, {"signals": one_signals},
                            eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
            if len(raw["events"]) != 1:
                raise RuntimeError("Q1_SINGLE_ORIGIN_EVENT_ACCOUNTING")
            event = deepcopy(raw["events"][0])
            paths = raw["trades"] + raw["open_positions"]
            if not paths:
                if event["status"] != "EXCLUDED":
                    raise RuntimeError("Q1_MISSING_ORIGIN_PATH")
                counts["entry_open_stop_cancellations"] += 1
                trace.extend(raw["trace"])
            else:
                if len(paths) != 1:
                    raise RuntimeError("Q1_SINGLE_ORIGIN_PATH_ACCOUNTING")
                if enable_change:
                    trade, observation, path_trace = _ratchet_path(usable, paths[0], signals)
                else:
                    trade = deepcopy(raw["trades"][0]) if raw["trades"] else None
                    observation = deepcopy(raw["open_positions"][0]) if raw["open_positions"] else None
                    path_trace = deepcopy(raw["trace"])
                trace.extend(path_trace)
                if trade is not None:
                    trades.append(trade)
                    event.update(status="COMPLETED", exclusion_reason=None)
                    event.pop("censor_reason", None)
                    last_exit_index = trade["exit_index"]
                    counts[trade["exit_reason"]] += 1
                else:
                    opened.append(observation)
                    event.update(status="CENSORED", exclusion_reason="COMMON_END_POSITION_OPEN",
                                 censor_reason="COMMON_END_POSITION_OPEN")
                    terminal_occupied = True
        events.append(event)
    if len(trades) + len(opened) + sum(e["status"] == "EXCLUDED" for e in events) != len(events):
        raise RuntimeError("Q1_OPPORTUNITY_ACCOUNTING_MISMATCH")
    return {"trades": trades, "open_positions": opened, "events": events,
            "trace": trace, "audit": {
                "rule": RULE_ID, "change_enabled": enable_change,
                "comparison_mode": "FIXED_Q0_ORIGINS" if fixed else "FULL_CHRONOLOGICAL",
                "up_confirmed": len(bullish), "down_confirmed": len(down),
                "completed": len(trades), "open": len(opened),
                "excluded": sum(e["status"] == "EXCLUDED" for e in events),
                "exit_and_cancel_counts": dict(sorted(counts.items())),
                "ratchet_activations": sum(t["kind"] == "Q1_RATCHET_ACTIVATED_NEXT_OPEN" for t in trace),
                "common_end_mark_ts": eval_end_ms,
                "same_symbol_max_positions": None if fixed else 1,
                "fixed_origins_independent_diagnostic_positions": fixed,
                "original_entry_and_initial_SL_preserved": True,
                "forced_terminal_liquidations": 0,
                "future_economic_rows": 0, "short_entries": 0}}
