"""One frozen DEV exit hook on the preserved Q0 chronological executor.

The entry UP's upper channel is immutable. After actual entry, the first
completed 4h close at or below it schedules an exit at the next available
original 4h open. Original gap protection and pending bearish exits precede
the new order. This module has no data loading, costs, parameters or writes.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from backend.research.rebuild import break_channel_structure_v1 as q0

INTERVAL = q0.INTERVAL
RULE_ID = "Q0_ENTRY_CHANNEL_LOSS_EXIT_DEV_V1"
EXIT_REASON = "ENTRY_CHANNEL_LOSS_NEXT_OPEN"


def _exit_geometry(rows, origin, index, price, stamp, reason, *, intrabar=False):
    """Ask the unchanged common evaluator for the actually held geometry."""
    held = index if intrabar else index - 1
    signal = origin["entry_signal_metadata"]
    result = q0.old.common.evaluate_development_events(
        rows, [signal["signal_index"]], split_start_ms=rows[0]["bar_open_ts"],
        split_end_ms=rows[-1]["bar_close_ts"] + INTERVAL,
        interval_ms=INTERVAL, hold_bars=held - signal["signal_index"])
    if len(result["trades"]) != 1 or result["exclusions"]:
        raise RuntimeError("PARALLEL_Q0_SHARED_GEOMETRY_UNAVAILABLE")
    trade = dict(result["trades"][0])
    for field in ("entry_stop_price", "channel_anchor_ts", "channel_upper",
                  "channel_lower", "preparation", "holding_limit",
                  "initial_risk_design", "entry_signal_metadata"):
        trade[field] = deepcopy(origin[field])
    gross = (price / trade["entry_price"] - 1.0) * 10000.0
    trade.update(
        exit_index=index, exit_ts=stamp, exit_price=price, gross_bps=gross,
        hold_ms=stamp - trade["entry_ts"],
        mfe_bps=max(trade["mfe_bps"], gross, 0.0),
        mae_bps=min(trade["mae_bps"], gross, 0.0), exit_reason=reason,
        exit_timestamp_semantics=("CLOSED_EXIT_BAR_UPPER_BOUND" if intrabar
                                  else "OBSERVED_4H_OPEN"),
        excursion_semantics=("FULL_EXIT_BAR_BOUND_POSSIBLY_POST_STOP_DIAGNOSTIC_ONLY"
                             if intrabar else "HELD_COMPLETED_BARS_AND_EXIT_OPEN_ONLY"),
        intrabar_stop_timing_unknown=intrabar, development_exit_rule=RULE_ID)
    return trade


def _held_path(rows, origin, down_by_index):
    """Causal open / protective touch / completed close phases for one entry.

    The unchanged Q0 executor supplies entry eligibility and fallback geometry.
    Its future profit, excursions and final exit are never condition inputs.
    The scan independently applies original protection and DOWN signals.
    """
    signal = origin["entry_signal_metadata"]
    upper, stop = float(signal["upper"]), float(origin["entry_stop_price"])
    pending_down = pending_channel = None
    trace = []

    def record(kind, index, **values):
        trace.append({"kind": kind, "index": index,
                      "signal_index": origin["signal_index"], **values})

    def finish(index, price, stamp, reason, intrabar=False):
        trade = _exit_geometry(rows, origin, index, price, stamp, reason,
                               intrabar=intrabar)
        trade["entry_channel_exit_trigger"] = deepcopy(pending_channel)
        record(reason, index, ts=stamp, price=price,
               entry_stop_price=stop, frozen_entry_channel_upper=upper,
               trigger=deepcopy(pending_channel))
        return trade, None, trace

    record("ENTRY_NEXT_OPEN", origin["entry_index"], ts=origin["entry_ts"],
           price=origin["entry_price"], entry_stop_price=stop,
           frozen_entry_channel_upper=upper)
    for index in range(origin["entry_index"], len(rows)):
        row = rows[index]
        stamp, price = row["bar_open_ts"], float(row["open"])
        # Entry eligibility already ensures the original entry open > SL.
        # For later opens the original gap SL precedes either pending exit.
        if price <= stop:
            return finish(index, price, stamp, "PROTECTIVE_STOP_GAP_OPEN")
        if pending_down is not None:
            return finish(index, price, stamp, "BEARISH_CONFIRMED_NEXT_OPEN")
        if pending_channel is not None:
            return finish(index, price, stamp, EXIT_REASON)
        if float(row["low"]) <= stop:
            return finish(index, stop, row["bar_close_ts"],
                          "PROTECTIVE_STOP_INTRABAR", True)
        pending_down = down_by_index.get(index)
        if pending_down is not None:
            record("BEARISH_CLOSE_CONFIRMED", index, ts=pending_down["signal_ts"])
        observed = {"index": index, "ts": row["bar_close_ts"],
                    "close": float(row["close"]),
                    "frozen_entry_channel_upper": upper,
                    "condition_met": float(row["close"]) <= upper,
                    "original_bearish_exit_pending": pending_down is not None}
        record("ENTRY_CHANNEL_CLOSE_OBSERVED", index,
               **{k: v for k, v in observed.items() if k != "index"})
        if observed["condition_met"]:
            pending_channel = observed
            record("ENTRY_CHANNEL_LOSS_CLOSE_TRIGGER", index,
                   ts=row["bar_close_ts"], close=float(row["close"]),
                   frozen_entry_channel_upper=upper,
                   original_bearish_exit_pending=pending_down is not None)
    if "mark_ts" not in origin:
        raise RuntimeError("PARALLEL_Q0_ORIGINAL_EXIT_CHRONOLOGY_MISMATCH")
    opened = deepcopy(origin)
    opened.update(
        development_exit_rule=RULE_ID,
        pending_entry_channel_exit=deepcopy(pending_channel),
        pending_exit_signal_ts=(pending_down["signal_ts"] if pending_down else
                                pending_channel["ts"] if pending_channel else None),
        pending_exit_reason=("BEARISH_CONFIRMED_NEXT_OPEN" if pending_down else
                             EXIT_REASON if pending_channel else None))
    record("TERMINAL_MARK", len(rows) - 1, ts=opened["mark_ts"],
           price=opened["mark_price"], frozen_entry_channel_upper=upper,
           pending_exit_reason=opened["pending_exit_reason"])
    return None, opened, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enable_change=True,
           fixed_signal_indices=None):
    """Reuse Q0 eligibility with either original origins or full ownership.

    Disabled full replay returns Q0's complete result exactly. Fixed origins
    must be entries admitted by that parent, and bypass only ownership between
    those diagnostic positions. Full replay never revives an earlier blocked
    signal; a close while the next-open exit is pending remains occupied.
    """
    if type(enable_change) is not bool:
        raise RuntimeError("PARALLEL_Q0_ENABLE_BOOL_REQUIRED")
    parent = q0.replay(rows, bundle, eval_start_ms=eval_start_ms,
                       eval_end_ms=eval_end_ms)
    fixed = fixed_signal_indices is not None
    if not enable_change and not fixed:
        return parent
    usable = [r for r in rows if r["bar_close_ts"] <= eval_end_ms]
    signals = bundle["signals"]
    bullish = [s for s in signals if s["direction"] == "UP"]
    down = [s for s in signals if s["direction"] == "DOWN"]
    down_by_index = {s["signal_index"]: s for s in down}
    if fixed:
        indices = list(fixed_signal_indices)
        admitted = {t["signal_index"] for t in parent["trades"] + parent["open_positions"]}
        if (any(type(i) is not int for i in indices) or len(set(indices)) != len(indices)
                or not set(indices) <= admitted):
            raise RuntimeError("PARALLEL_Q0_FIXED_PARENT_ORIGIN_SET_INVALID")
        bullish = [s for s in bullish if s["signal_index"] in set(indices)]
    trades, opened, events, trace = [], [], [], []
    counts = Counter()
    last_exit_index, terminal_occupied = -1, False
    for signal in bullish:
        index = signal["signal_index"]
        event = {"direction": "UP", "signal_index": index,
                 "signal_ts": signal["signal_ts"], "admission": True,
                 "status": "PENDING", "exclusion_reason": None,
                 "features": deepcopy(signal)}
        if index in down_by_index:
            event.update(status="EXCLUDED", exclusion_reason="OPPOSITE_SIGNAL_PRIORITY")
            counts["simultaneous_confirmation_conflicts"] += 1
        elif not fixed and (terminal_occupied or index < last_exit_index):
            event.update(status="EXCLUDED", exclusion_reason="SIGNAL_DURING_OPEN")
        else:
            one = sorted(down + [signal], key=lambda s: (
                s["signal_ts"], 0 if s["direction"] == "DOWN" else 1))
            original = q0.replay(usable, {"signals": one},
                                 eval_start_ms=eval_start_ms, eval_end_ms=eval_end_ms)
            if len(original["events"]) != 1:
                raise RuntimeError("PARALLEL_Q0_SINGLE_ORIGIN_EVENT_ACCOUNTING")
            event = deepcopy(original["events"][0])
            paths = original["trades"] + original["open_positions"]
            if not paths:
                if event["status"] != "EXCLUDED":
                    raise RuntimeError("PARALLEL_Q0_MISSING_ORIGIN_PATH")
                counts["entry_open_stop_cancellations"] += 1
                trace.extend(original["trace"])
            else:
                if len(paths) != 1:
                    raise RuntimeError("PARALLEL_Q0_SINGLE_ORIGIN_PATH_ACCOUNTING")
                if enable_change:
                    trade, observation, path_trace = _held_path(
                        usable, paths[0], down_by_index)
                else:
                    trade = deepcopy(original["trades"][0]) if original["trades"] else None
                    observation = (deepcopy(original["open_positions"][0])
                                   if original["open_positions"] else None)
                    path_trace = deepcopy(original["trace"])
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
        raise RuntimeError("PARALLEL_Q0_OPPORTUNITY_ACCOUNTING_MISMATCH")
    trace.sort(key=lambda t: (t.get("ts", 0), t["index"], t.get("signal_index", -1)))
    return {"trades": trades, "open_positions": opened, "events": events,
            "trace": trace, "audit": {
                "rule": RULE_ID, "change_enabled": enable_change,
                "comparison_mode": "FIXED_PARENT_ENTRIES" if fixed else "FULL_CHRONOLOGICAL",
                "up_confirmed": len(bullish), "original_up_confirmed": parent["audit"]["up_confirmed"],
                "down_confirmed": len(down), "completed": len(trades), "open": len(opened),
                "excluded": sum(e["status"] == "EXCLUDED" for e in events),
                "exit_and_cancel_counts": dict(sorted(counts.items())),
                "channel_loss_triggers": sum(t["kind"] == "ENTRY_CHANNEL_LOSS_CLOSE_TRIGGER" for t in trace),
                "pending_channel_exits_at_end": sum(o.get("pending_entry_channel_exit") is not None for o in opened),
                "common_end_mark_ts": eval_end_ms,
                "same_symbol_max_positions": None if fixed else 1,
                "fixed_origins_independent_diagnostic_positions": fixed,
                "original_entry_and_initial_SL_preserved": True,
                "frozen_entry_upper_never_updated": True,
                "forced_terminal_liquidations": 0,
                "future_economic_rows": 0, "short_entries": 0}}
