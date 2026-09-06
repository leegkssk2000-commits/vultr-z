"""Long-only DEV direction-exit policy around the preserved shared evaluator.

This is a ZEL research variation, not the original strategy's full replay.
Inputs must already be isolated DEV bars and causal confirmed flip indices.
No data access, indicator calculation, costs, authority or persistence occurs
here. Fixed-origin mode is an overlapping diagnostic, never a portfolio.
"""
from __future__ import annotations

from bisect import bisect_left

from backend.research.rebuild import top5_development_repair_v1 as old


def replay_direction(rows, bull_signals, bear_signals, *, split_start_ms,
                     split_end_ms, interval_ms=14_400_000, fixed_origins=False):
    """Enter next open; first later bearish close exits next observed open.

    Signal/mark bars must have close < split_end_ms. A scheduled exit needs
    only an observed open < split_end_ms: final bar open may fill an exit,
    while its later high/low/close remain unavailable. An unavailable next
    open leaves a pending exit and mark at the last usable close, never a
    terminal liquidation.
    In full mode a bull signal at an exit bar's *close* may reserve next open,
    because the previous position closed earlier at that bar's open.
    """
    if type(fixed_origins) is not bool:
        raise RuntimeError("DIRECTION_FIXED_ORIGINS_BOOL_REQUIRED")
    shared = dict(split_start_ms=split_start_ms, split_end_ms=split_end_ms,
                  interval_ms=interval_ms, side="long")
    # An impossible hold invokes all preserved row/signal checks without
    # calculating any extra economic observation or comparison candidate.
    validation_hold = len(rows) + 1 if isinstance(rows, (list, tuple)) else 1
    for signals in (bull_signals, bear_signals):
        old.common.evaluate_development_events(
            rows, signals, hold_bars=validation_hold, **shared)
    if set(bull_signals) & set(bear_signals):
        raise RuntimeError("DIRECTION_CONTRADICTORY_FLIP")

    last_usable = len(rows) - 1
    while last_usable >= 0 and rows[last_usable]["bar_close_ts"] >= split_end_ms:
        last_usable -= 1
    usable_bears = [i for i in bear_signals if i <= last_usable]
    trades, opened, events, trace = [], [], [], []
    occupied_until_index = -1
    indefinitely_occupied = False

    def record(kind, index, timestamp, origin, **extra):
        trace.append({"kind": kind, "index": index, "ts": timestamp,
                      "signal_index": origin,
                      "signal_ts": rows[origin]["bar_close_ts"], **extra})

    def raw_geometry(origin, last_held):
        result = old.common.evaluate_development_events(
            rows, [origin], hold_bars=last_held - origin, **shared)
        if len(result["trades"]) != 1 or result["exclusions"]:
            raise RuntimeError("DIRECTION_SHARED_GEOMETRY_UNAVAILABLE")
        return dict(result["trades"][0])

    for origin in bull_signals:
        event = {"signal_index": origin,
                 "signal_ts": rows[origin]["bar_close_ts"],
                 "admission": True,
                 "fixed_origin_diagnostic": fixed_origins}
        entry_index = origin + 1
        if entry_index > last_usable:
            event.update(status="EXCLUDED", exclusion_reason="ENTRY_OUTSIDE_USABLE_BARS")
            events.append(event)
            record("EXCLUDED", origin, event["signal_ts"], origin,
                   reason=event["exclusion_reason"])
            continue
        if not fixed_origins and (indefinitely_occupied or origin < occupied_until_index):
            event.update(status="EXCLUDED", exclusion_reason="SIGNAL_DURING_OPEN")
            events.append(event)
            record("EXCLUDED", origin, event["signal_ts"], origin,
                   reason=event["exclusion_reason"])
            continue

        record("SIGNAL_ACCEPTED", origin, event["signal_ts"], origin)
        record("ENTRY_NEXT_OPEN", entry_index, rows[entry_index]["bar_open_ts"],
               origin, price=float(rows[entry_index]["open"]), side="long")
        bear_offset = bisect_left(usable_bears, entry_index)
        bear = usable_bears[bear_offset] if bear_offset < len(usable_bears) else None
        exit_index = bear + 1 if bear is not None else None
        if bear is not None:
            record("EXIT_SIGNAL", bear, rows[bear]["bar_close_ts"], origin)
        if (exit_index is not None and exit_index < len(rows)
                and rows[exit_index]["bar_open_ts"] < split_end_ms):
            raw = raw_geometry(origin, exit_index - 1)
            # The evaluator prices the last held bar's close. The policy
            # executes at next open, including any price gap at that point;
            # its later high/low/close must never affect this closed trade.
            price = float(rows[exit_index]["open"])
            gross = (price / raw["entry_price"] - 1.0) * 10_000.0
            raw.update(exit_index=exit_index,
                       exit_ts=rows[exit_index]["bar_open_ts"],
                       exit_price=price, gross_bps=gross,
                       mfe_bps=max(raw["mfe_bps"], gross, 0.0),
                       mae_bps=min(raw["mae_bps"], gross, 0.0),
                       exit_signal_index=bear,
                       exit_signal_ts=rows[bear]["bar_close_ts"],
                       exit_reason="OPPOSITE_CONFIRMED_FLIP_NEXT_OPEN",
                       fixed_origin_diagnostic=fixed_origins)
            raw["hold_ms"] = raw["exit_ts"] - raw["entry_ts"]
            trades.append(raw)
            occupied_until_index = exit_index
            event.update(status="COMPLETED", exclusion_reason=None)
            record("EXIT_NEXT_OPEN", exit_index, raw["exit_ts"], origin,
                   price=price, side="long")
        else:
            raw = raw_geometry(origin, last_usable)
            for name in ("exit_reason", "exit_signal_index", "exit_signal_ts"):
                raw.pop(name, None)
            raw["mark_index"] = raw.pop("exit_index")
            raw["mark_ts"] = raw.pop("exit_ts")
            raw["mark_price"] = raw.pop("exit_price")
            raw["gross_mark_bps"] = raw.pop("gross_bps")
            raw.update(status="CENSORED", terminal_liquidation=False,
                       fixed_origin_diagnostic=fixed_origins,
                       pending_exit_signal_index=bear,
                       pending_exit_signal_ts=(rows[bear]["bar_close_ts"]
                                               if bear is not None else None))
            opened.append(raw)
            indefinitely_occupied = True
            event.update(status="CENSORED", exclusion_reason=None,
                         censor_reason="SPLIT_END_POSITION_OPEN")
            record("TERMINAL_MARK", last_usable, raw["mark_ts"], origin,
                   price=raw["mark_price"], pending_exit=bool(bear is not None))
        events.append(event)

    # Timestamps may coincide at adjacent close/open. Close-observed signals
    # precede their scheduled next-open execution in that case.
    priority = {"EXIT_SIGNAL": 0, "SIGNAL_ACCEPTED": 1, "EXIT_NEXT_OPEN": 2,
                "ENTRY_NEXT_OPEN": 3, "EXCLUDED": 4, "TERMINAL_MARK": 5}
    trace.sort(key=lambda x: (x["ts"], priority[x["kind"]], x["signal_index"]))
    return {"trades": trades, "open_positions": opened,
            "events": events, "trace": trace}
