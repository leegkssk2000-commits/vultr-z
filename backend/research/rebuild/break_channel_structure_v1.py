"""Pure daily channel structure and chronological DEV execution adapter.

The source's CB1 price formulas are separated from fixed ZEL design priors:
frozen two-close confirmation, long/cash ownership, next-open fills and a
latched protective lower band. No data acquisition, costs, authority changes,
parameter search or persistence occurs here. The preserved common evaluator
validates source bars and supplies completed-bar trade geometry.
"""
from __future__ import annotations

from collections import Counter
import math

from backend.research.rebuild import top5_development_repair_v1 as old


INTERVAL = 14_400_000
DAY = 86_400_000
LOOKBACK_DAYS = 2
CONFIRMATION_DAYS = 2
CHANNEL_WIDTH_PERCENT = 0.5


def _validate_rows(rows):
    if not isinstance(rows, (list, tuple)) or not rows:
        raise RuntimeError("CHANNEL_ROWS_REQUIRED")
    if not isinstance(rows[0], dict) or not isinstance(rows[-1], dict):
        raise RuntimeError("CHANNEL_BAR_OBJECT_REQUIRED")
    old.common.evaluate_development_events(
        rows, [], split_start_ms=rows[0].get("bar_open_ts"),
        split_end_ms=rows[-1].get("bar_close_ts"), interval_ms=INTERVAL,
        hold_bars=len(rows) + 1)


def aggregate_daily(rows, *, split_end_ms=None):
    """Aggregate only six contiguous UTC 4h bars; retain source index lineage.

    A completed day closing exactly at the evaluation end is valid data and
    a valid terminal mark. Its closing signal is separately forbidden by
    generate_signals. Partial edge days are counted, never synthesized.
    """
    _validate_rows(rows)
    end = rows[-1]["bar_close_ts"] if split_end_ms is None else split_end_ms
    if type(end) is not int or end % INTERVAL:
        raise RuntimeError("CHANNEL_AGGREGATION_END_INVALID")
    groups = {}
    outside = 0
    for index, row in enumerate(rows):
        if row["bar_close_ts"] > end:
            outside += 1
            continue
        stamp = row["bar_open_ts"] // DAY * DAY
        groups.setdefault(stamp, []).append((index, row))
    daily, partial = [], []
    for stamp, items in groups.items():
        complete = (len(items) == 6 and items[0][1]["bar_open_ts"] == stamp
                    and items[-1][1]["bar_close_ts"] == stamp + DAY)
        if not complete:
            partial.append({"day_open_ts": stamp, "rows": len(items),
                            "source_indices": [i for i, _ in items]})
            continue
        bars = [r for _, r in items]
        daily.append({"bar_open_ts": stamp, "bar_close_ts": stamp + DAY,
                      "open": float(bars[0]["open"]),
                      "high": max(float(r["high"]) for r in bars),
                      "low": min(float(r["low"]) for r in bars),
                      "close": float(bars[-1]["close"]),
                      "volume": sum(float(r["volume"]) for r in bars),
                      "source_first_index": items[0][0],
                      "source_last_index": items[-1][0],
                      "constituent_count": 6})
    return {"daily": daily, "audit": {
        "input_4h_rows": len(rows), "complete_utc_days": len(daily),
        "aggregated_4h_rows": len(daily) * 6, "partial_days": partial,
        "partial_day_4h_rows": sum(p["rows"] for p in partial),
        "after_common_end_4h_rows": outside, "synthetic_rows": 0,
        "aggregation": "SIX_CONTIGUOUS_UTC_4H_BARS"}}


def channel(previous_closes):
    """Appendix CB1: prior close extrema, percentage width, U and D."""
    if len(previous_closes) != LOOKBACK_DAYS or any(
        isinstance(x, bool) or not isinstance(x, (int, float))
        or not math.isfinite(x) or x <= 0 for x in previous_closes
    ):
        raise RuntimeError("CHANNEL_PRIOR_CLOSES_INVALID")
    high, low = max(previous_closes), min(previous_closes)
    width = high / low - 1.0
    fraction = CHANNEL_WIDTH_PERCENT / 100.0
    return {"prior_high_close": float(high), "prior_low_close": float(low),
            "channel_width_fraction": width,
            "preparation": width <= fraction,
            "upper": low * (1.0 + fraction),
            "lower": high * (1.0 - fraction)}


def generate_signals(daily, *, eval_start_ms, eval_end_ms,
                     require_preparation=True):
    """Independent frozen-band up/down attempts, each requiring two closes.

    A failed or completed attempt cannot restart on that same day. Q-minus
    removes only the preparation requirement when beginning an up attempt.
    Neither variant applies preparation to a bearish exit attempt.
    """
    if type(require_preparation) is not bool:
        raise RuntimeError("CHANNEL_PREPARATION_BOOL_REQUIRED")
    if (type(eval_start_ms) is not int or type(eval_end_ms) is not int
            or eval_start_ms < 0 or eval_start_ms >= eval_end_ms
            or eval_start_ms % DAY or eval_end_ms % DAY):
        raise RuntimeError("CHANNEL_DAILY_EVALUATION_BOUNDS_INVALID")
    previous = None
    for row in daily:
        if (type(row.get("bar_open_ts")) is not int
                or row["bar_open_ts"] % DAY
                or row.get("bar_close_ts") != row["bar_open_ts"] + DAY
                or row.get("constituent_count") != 6):
            raise RuntimeError("CHANNEL_DAILY_BAR_INVALID")
        if previous is not None and row["bar_open_ts"] != previous + DAY:
            raise RuntimeError("CHANNEL_DAILY_GAP_DUPLICATE_OR_ORDER")
        previous = row["bar_open_ts"]
        channel([row.get("close"), row.get("close")])
    signals, trace = [], []
    active = {"UP": None, "DOWN": None}

    def record(kind, index, **extra):
        trace.append({"kind": kind, "daily_index": index,
                      "signal_index": daily[index]["source_last_index"],
                      "ts": daily[index]["bar_close_ts"], **extra})

    for i in range(LOOKBACK_DAYS, len(daily)):
        row = daily[i]
        if row["bar_close_ts"] >= eval_end_ms:
            break
        current = channel([r["close"] for r in daily[i - LOOKBACK_DAYS:i]])
        current.update(anchor_daily_index=i,
                       anchor_signal_index=row["source_last_index"],
                       anchor_ts=row["bar_close_ts"],
                       prior_start_ts=daily[i - LOOKBACK_DAYS]["bar_open_ts"],
                       prior_end_ts=daily[i - 1]["bar_close_ts"])
        close = float(row["close"])
        for direction in ("UP", "DOWN"):
            attempt = active[direction]
            if attempt is not None:
                beyond = (close > attempt["upper"] if direction == "UP"
                          else close < attempt["lower"])
                conflict = direction == "UP" and close < attempt["lower"]
                if not beyond or conflict:
                    record("ATTEMPT_CANCELLED", i, direction=direction,
                           reason="CROSSED_BAND_CONFLICT" if conflict else "CONFIRMATION_FAILED",
                           anchor_ts=attempt["anchor_ts"], close=close)
                    active[direction] = None
                    continue
                confirmed = dict(attempt, direction=direction,
                                 daily_index=i, signal_index=row["source_last_index"],
                                 signal_ts=row["bar_close_ts"],
                                 confirmation_days=CONFIRMATION_DAYS,
                                 confirmation_close=close)
                record("CONFIRMED", i, direction=direction,
                       anchor_ts=attempt["anchor_ts"], close=close)
                if eval_start_ms <= row["bar_close_ts"]:
                    signals.append(confirmed)
                active[direction] = None
                continue
            beyond = close > current["upper"] if direction == "UP" else close < current["lower"]
            if not beyond:
                continue
            if direction == "UP" and close < current["lower"]:
                record("UP_START_REJECTED", i, reason="CROSSED_BAND_CONFLICT", **current)
                continue
            if direction == "UP" and require_preparation and not current["preparation"]:
                record("UP_START_REJECTED", i, reason="PREPARATION_ABSENT", **current)
                continue
            active[direction] = current
            record("ATTEMPT_STARTED", i, direction=direction, close=close, **current)
    signals.sort(key=lambda s: (s["signal_ts"], 0 if s["direction"] == "DOWN" else 1))
    return {"signals": signals, "trace": trace, "audit": {
        "up_confirmed": sum(s["direction"] == "UP" for s in signals),
        "down_confirmed": sum(s["direction"] == "DOWN" for s in signals),
        "require_preparation": require_preparation,
        "pending_attempts_at_end": active,
        "trace_counts": dict(sorted(Counter(t["kind"] for t in trace).items())),
        "signal_close_at_end_allowed": False}}


def replay(rows, bundle, *, eval_start_ms, eval_end_ms):
    """Chronological 4h ownership, next-open execution and latched lower SL.

    At an open, an existing protective gap exit precedes a pending bearish
    exit. A new entry must open strictly above its latched SL. Intrabar stop
    timing is unknown: use that complete 4h bar's close as a conservative
    holding/funding upper bound. The close at common end can value or stop a
    position, but cannot originate a new signal; the open at end cannot fill.
    """
    _validate_rows(rows)
    if (type(eval_start_ms) is not int or type(eval_end_ms) is not int
            or eval_start_ms < rows[0]["bar_open_ts"]
            or eval_start_ms >= eval_end_ms
            or eval_start_ms % INTERVAL or eval_end_ms % INTERVAL
            or eval_end_ms > rows[-1]["bar_close_ts"]):
        raise RuntimeError("CHANNEL_REPLAY_BOUNDS_INVALID")
    usable = [r for r in rows if r["bar_close_ts"] <= eval_end_ms]
    if not usable or usable[-1]["bar_close_ts"] != eval_end_ms:
        raise RuntimeError("CHANNEL_COMMON_END_BAR_MISSING")
    signals = bundle.get("signals")
    if not isinstance(signals, (list, tuple)):
        raise RuntimeError("CHANNEL_SIGNAL_SEQUENCE_REQUIRED")
    by_index, seen = {}, set()
    previous_order = None
    for signal in signals:
        direction = signal.get("direction")
        index = signal.get("signal_index")
        stamp = signal.get("signal_ts")
        if (direction not in {"UP", "DOWN"} or type(index) is not int
                or not 0 <= index < len(usable)
                or stamp != usable[index]["bar_close_ts"]
                or stamp % DAY
                or not eval_start_ms <= stamp < eval_end_ms):
            raise RuntimeError("CHANNEL_SIGNAL_INVALID_OR_FUTURE")
        order = (stamp, 0 if direction == "DOWN" else 1)
        if (index, direction) in seen or (previous_order is not None and order < previous_order):
            raise RuntimeError("CHANNEL_SIGNAL_DUPLICATE_OR_ORDER")
        for field in ("lower", "upper"):
            value = signal.get(field)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise RuntimeError("CHANNEL_SIGNAL_BAND_INVALID")
        seen.add((index, direction)); previous_order = order
        by_index.setdefault(index, []).append(signal)
    trades, opened, events, trace = [], [], [], []
    position = pending_entry = pending_exit = None
    counts = Counter()

    def record(kind, index, **extra):
        trace.append({"kind": kind, "index": index, **extra})

    def geometry(pos, last_held):
        # The common function excludes close == split_end and requires 4h
        # aligned bounds. A one-interval envelope allows the actual common
        # end close, but usable contains no price after that common end.
        result = old.common.evaluate_development_events(
            usable, [pos["signal"]["signal_index"]],
            split_start_ms=usable[0]["bar_open_ts"],
            split_end_ms=eval_end_ms + INTERVAL, interval_ms=INTERVAL,
            hold_bars=last_held - pos["signal"]["signal_index"])
        if len(result["trades"]) != 1 or result["exclusions"]:
            raise RuntimeError("CHANNEL_SHARED_GEOMETRY_UNAVAILABLE")
        raw = dict(result["trades"][0])
        raw.update(entry_stop_price=pos["stop"],
                   channel_anchor_ts=pos["signal"].get("anchor_ts"),
                   channel_upper=pos["signal"]["upper"],
                   channel_lower=pos["signal"]["lower"],
                   preparation=pos["signal"].get("preparation"),
                   holding_limit=None, initial_risk_design="LATCHED_LOWER_CHANNEL_SL",
                   entry_signal_metadata=dict(pos["signal"]))
        return raw

    def close_position(pos, index, price, stamp, reason, *, intrabar=False):
        raw = geometry(pos, index if intrabar else index - 1)
        gross = (price / raw["entry_price"] - 1.0) * 10_000.0
        raw.update(exit_index=index, exit_ts=stamp, exit_price=price,
                   gross_bps=gross, hold_ms=stamp - raw["entry_ts"],
                   mfe_bps=max(raw["mfe_bps"], gross, 0.0),
                   mae_bps=min(raw["mae_bps"], gross, 0.0),
                   exit_reason=reason,
                   exit_timestamp_semantics=("CLOSED_EXIT_BAR_UPPER_BOUND" if intrabar else "OBSERVED_4H_OPEN"),
                   excursion_semantics=("FULL_EXIT_BAR_BOUND_POSSIBLY_POST_STOP_DIAGNOSTIC_ONLY" if intrabar else "HELD_COMPLETED_BARS_AND_EXIT_OPEN_ONLY"),
                   intrabar_stop_timing_unknown=intrabar)
        trades.append(raw)
        pos["event"].update(status="COMPLETED", exclusion_reason=None)
        counts[reason] += 1
        record(reason, index, ts=stamp, price=price,
               signal_index=raw["signal_index"], entry_stop_price=pos["stop"])

    for index, row in enumerate(usable):
        stamp, price = row["bar_open_ts"], float(row["open"])
        exited_at_open = False
        if position is not None:
            if price <= position["stop"]:
                close_position(position, index, price, stamp, "PROTECTIVE_STOP_GAP_OPEN")
                position = pending_exit = None; exited_at_open = True
            elif pending_exit is not None:
                close_position(position, index, price, stamp, "BEARISH_CONFIRMED_NEXT_OPEN")
                position = pending_exit = None; exited_at_open = True
        if pending_entry is not None:
            signal, event = pending_entry
            if position is not None or exited_at_open:
                event.update(status="EXCLUDED", exclusion_reason="SAME_OPEN_EXIT_OR_OCCUPANCY")
            elif price <= signal["lower"]:
                event.update(status="EXCLUDED", exclusion_reason="ENTRY_OPEN_NOT_ABOVE_PROTECTIVE_STOP")
                counts["entry_open_stop_cancellations"] += 1
            else:
                position = {"signal": signal, "event": event,
                            "entry_index": index, "stop": float(signal["lower"])}
                record("ENTRY_NEXT_OPEN", index, ts=stamp, price=price,
                       signal_index=signal["signal_index"], entry_stop_price=position["stop"])
            if event["status"] == "EXCLUDED":
                record("ENTRY_CANCELLED", index, ts=stamp,
                       signal_index=signal["signal_index"], reason=event["exclusion_reason"])
            pending_entry = None
        if position is not None and float(row["low"]) <= position["stop"]:
            close_position(position, index, position["stop"], row["bar_close_ts"],
                           "PROTECTIVE_STOP_INTRABAR", intrabar=True)
            position = pending_exit = None
        current = by_index.get(index, [])
        bearish = next((s for s in current if s["direction"] == "DOWN"), None)
        bullish = next((s for s in current if s["direction"] == "UP"), None)
        if bearish is not None:
            record("BEARISH_CLOSE_CONFIRMED", index, ts=bearish["signal_ts"],
                   occupied=position is not None, signal_index=index)
            if position is not None:
                pending_exit = bearish
        if bullish is not None:
            event = {"direction": "UP", "signal_index": index,
                     "signal_ts": bullish["signal_ts"], "admission": True,
                     "status": "PENDING", "exclusion_reason": None,
                     "features": dict(bullish)}
            if bearish is not None:
                event.update(status="EXCLUDED", exclusion_reason="OPPOSITE_SIGNAL_PRIORITY")
                counts["simultaneous_confirmation_conflicts"] += 1
            elif position is not None:
                event.update(status="EXCLUDED", exclusion_reason="SIGNAL_DURING_OPEN")
            else:
                pending_entry = (bullish, event)
            events.append(event)
            record("BULLISH_CLOSE_CONFIRMED", index, ts=bullish["signal_ts"],
                   status=event["status"], reason=event["exclusion_reason"], signal_index=index)
    if position is not None:
        raw = geometry(position, len(usable) - 1)
        raw["mark_index"] = raw.pop("exit_index")
        raw["mark_ts"] = raw.pop("exit_ts")
        raw["mark_price"] = raw.pop("exit_price")
        raw["gross_mark_bps"] = raw.pop("gross_bps")
        raw.update(status="CENSORED", terminal_liquidation=False,
                   pending_exit_signal_ts=(pending_exit["signal_ts"] if pending_exit else None),
                   excursion_semantics="COMPLETED_HELD_4H_BARS_TO_COMMON_END")
        opened.append(raw)
        position["event"].update(status="CENSORED", exclusion_reason="COMMON_END_POSITION_OPEN",
                                 censor_reason="COMMON_END_POSITION_OPEN")
        record("TERMINAL_MARK", len(usable) - 1, ts=raw["mark_ts"],
               price=raw["mark_price"], signal_index=raw["signal_index"])
    if pending_entry is not None or any(e["status"] == "PENDING" for e in events):
        raise RuntimeError("CHANNEL_UNRESOLVED_PENDING_ENTRY")
    if len(trades) + len(opened) + sum(e["status"] == "EXCLUDED" for e in events) != len(events):
        raise RuntimeError("CHANNEL_OPPORTUNITY_ACCOUNTING_MISMATCH")
    return {"trades": trades, "open_positions": opened,
            "events": events, "trace": trace, "audit": {
        "up_confirmed": sum(s["direction"] == "UP" for s in signals),
        "down_confirmed": sum(s["direction"] == "DOWN" for s in signals),
        "completed": len(trades), "open": len(opened),
        "excluded": sum(e["status"] == "EXCLUDED" for e in events),
        "exit_and_cancel_counts": dict(sorted(counts.items())),
        "common_end_mark_ts": eval_end_ms, "same_symbol_max_positions": 1,
        "forced_terminal_liquidations": 0,
        "future_economic_rows": 0, "short_entries": 0}}
