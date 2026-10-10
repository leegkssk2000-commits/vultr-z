"""Pure causal execution adapter for the frozen Monday-drift BTC rule.

The source rule observes the completed 1h close at Monday 00:00 UTC, holds
long/cash, and observes the completed 1h close at Tuesday 00:00 UTC to exit.
Orders are an internal translation: earliest next available open, taker cost,
no stop/target, and no terminal forced close.  This module has no I/O, claims,
network, market loading, or order authority.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

HOUR = 3_600_000
CANDIDATE_ID = "R_FORVEN_MONDAY_DRIFT_BTC_1H_V1"


class DraftError(ValueError):
    pass


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise DraftError("INVALID_NUMBER")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise DraftError("INVALID_NUMBER") from None
    if not math.isfinite(result) or (positive and result <= 0):
        raise DraftError("INVALID_NUMBER")
    return result


def _records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    previous: int | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("HOURLY_MAPPING_REQUIRED")
        try:
            opened, closed, available = (row[k] for k in
                                         ("open_ts_ms", "close_ts_ms", "available_ts_ms"))
            segment = row["segment_id"]
            opening = _number(row["open"], positive=True)
        except KeyError:
            raise DraftError("HOURLY_FIELDS_REQUIRED") from None
        if (any(type(value) is not int for value in (opened, closed, available))
                or opened % HOUR or closed != opened + HOUR or available < closed
                or (type(segment) is not int and (not isinstance(segment, str) or not segment))
                or (previous is not None and opened <= previous)):
            raise DraftError("HOURLY_CLOCK_OR_SEGMENT_INVALID")
        output.append({**row, "open": opening})
        previous = opened
    return output


def monday_tuesday_decisions(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return completed-close decisions with prefix receipt availability."""
    records = _records(rows)
    output: list[dict[str, Any]] = []
    prior = None
    prefix_available = 0
    for row in records:
        if (prior is None or row["segment_id"] != prior["segment_id"]
                or row["open_ts_ms"] != prior["close_ts_ms"]):
            prefix_available = row["available_ts_ms"]
        else:
            prefix_available = max(prefix_available, row["available_ts_ms"])
        closed = datetime.fromtimestamp(row["close_ts_ms"] / 1000, timezone.utc)
        if closed.hour == 0 and closed.minute == 0 and closed.second == 0 and closed.weekday() in (0, 1):
            output.append({
                "kind": "ENTRY" if closed.weekday() == 0 else "EXIT",
                "signal_open_ts_ms": row["open_ts_ms"],
                "signal_close_ts_ms": row["close_ts_ms"],
                "signal_available_ts_ms": prefix_available,
                "segment_id": row["segment_id"],
            })
        prior = row
    return output


def funding_debit(position: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                  *, exit_ms: int, end_ms: int, closed: bool) -> tuple[float, int]:
    """Long funding debit in entry-normalized bps with adverse boundaries."""
    entry = position.get("entry_ts_ms")
    if type(entry) is not int or type(exit_ms) is not int or type(end_ms) is not int or not entry < exit_ms <= end_ms:
        raise DraftError("FUNDING_EXPOSURE_CLOCK_INVALID")
    basis = _number(position.get("entry_price"), positive=True)
    total = 0.0
    count = 0
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("FUNDING_MAPPING_REQUIRED")
        stamp = row.get("fundingTime")
        if type(stamp) is not int or stamp in seen or row.get("symbol") != "BTC-USDT":
            raise DraftError("FUNDING_CLOCK_DUPLICATE_OR_SYMBOL")
        seen.add(stamp)
        rate = _number(row.get("fundingRate"))
        mark = _number(row.get("markPrice"), positive=True)
        if entry <= stamp <= exit_ms and stamp < end_ms:
            debit = rate * mark / basis * 10_000
            boundary = stamp == entry or (closed and stamp == exit_ms)
            if not boundary or debit > 0:
                total += debit
                count += 1
    return total, count


def replay_monday_drift(rows: Sequence[Mapping[str, Any]], funding_rows: Sequence[Mapping[str, Any]],
                        *, start_ms: int, end_ms: int, roundtrip_cost_bps: float) -> dict[str, Any]:
    """Causal fixed-24h replay with gap quarantine and no END liquidation."""
    if any(type(value) is not int or value % HOUR for value in (start_ms, end_ms)) or start_ms >= end_ms:
        raise DraftError("FIXED_WINDOW_REQUIRED")
    one_way = _number(roundtrip_cost_bps, positive=True) / 2
    records = _records(rows)
    if not any(row["open_ts_ms"] == start_ms for row in records) or not any(row["close_ts_ms"] == end_ms for row in records):
        raise DraftError("FIXED_START_END_SOURCE_COVERAGE_REQUIRED")
    decisions = {row["signal_open_ts_ms"]: row for row in monday_tuesday_decisions(records)}
    trades: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []
    position = pending_entry = pending_exit = quarantine = prior = None
    signals = occupied = 0

    for bar in records:
        opened = bar["open_ts_ms"]
        if opened >= end_ms:
            break
        gap = prior is not None and (opened != prior["close_ts_ms"] or bar["segment_id"] != prior["segment_id"])
        if gap and (position is not None or pending_entry is not None or pending_exit is not None):
            quarantine = {"gap_ts_ms": opened, "position": position,
                          "pending_entry": pending_entry, "pending_exit": pending_exit}
            break
        prior = bar
        if opened < start_ms:
            decision = decisions.get(opened)
            if (decision is not None and decision["kind"] == "ENTRY"
                    and start_ms <= decision["signal_close_ts_ms"] < end_ms):
                signals += 1
                pending_entry = {**decision, "expires_ts_ms": decision["signal_close_ts_ms"] + 24 * HOUR}
            continue

        if pending_exit is not None and opened >= pending_exit["signal_available_ts_ms"]:
            if position is None or pending_exit["entry_identity"] != position["entry_identity"]:
                raise DraftError("EXIT_POSITION_BINDING")
            gross = (bar["open"] / position["entry_price"] - 1) * 10_000
            trade = {**position, "exit_ts_ms": opened, "exit_price": bar["open"],
                     "exit_reason": "NEXT_AVAILABLE_OPEN_TUESDAY_00_UTC",
                     "exit_signal_open_ts_ms": pending_exit["signal_open_ts_ms"],
                     "exit_signal_close_ts_ms": pending_exit["signal_close_ts_ms"],
                     "exit_signal_available_ts_ms": pending_exit["signal_available_ts_ms"],
                     "gross_bps": gross, "cost_bps": 2 * one_way}
            debit, count = funding_debit(position, funding_rows, exit_ms=opened, end_ms=end_ms, closed=True)
            trade.update(funding_bps=debit, funding_settlements=count,
                         net_bps=gross - 2 * one_way - debit)
            trades.append(trade)
            orders.append({"kind": "EXIT", "execution_ts_ms": opened, "price": bar["open"],
                           "quantity": 1, "cost_bps": one_way,
                           "entry_identity": position["entry_identity"],
                           **pending_exit})
            position = pending_exit = None

        if pending_entry is not None:
            if opened >= pending_entry["expires_ts_ms"]:
                missed.append({**pending_entry, "reason": "MONDAY_ENTRY_EXPIRED_AT_TUESDAY_DECISION"})
                pending_entry = None
            elif opened >= pending_entry["signal_available_ts_ms"]:
                identity = f"BTC-USDT:{opened}:{pending_entry['signal_open_ts_ms']}"
                position = {"identity": CANDIDATE_ID, "entry_identity": identity,
                            "symbol": "BTC-USDT", "side": "LONG",
                            "entry_ts_ms": opened, "entry_price": bar["open"],
                            "entry_cost_bps": one_way,
                            "signal_open_ts_ms": pending_entry["signal_open_ts_ms"],
                            "signal_close_ts_ms": pending_entry["signal_close_ts_ms"],
                            "signal_available_ts_ms": pending_entry["signal_available_ts_ms"]}
                orders.append({"kind": "ENTRY", "execution_ts_ms": opened, "price": bar["open"],
                               "quantity": 1, "cost_bps": one_way,
                               "entry_identity": identity, **pending_entry})
                pending_entry = None

        decision = decisions.get(opened)
        if decision is None or decision["signal_close_ts_ms"] >= end_ms:
            continue
        if decision["kind"] == "ENTRY":
            signals += 1
            if position is None and pending_entry is None and pending_exit is None:
                pending_entry = {**decision, "expires_ts_ms": decision["signal_close_ts_ms"] + 24 * HOUR}
            else:
                occupied += 1
        elif position is not None:
            pending_exit = {**decision, "entry_identity": position["entry_identity"]}
        elif pending_entry is not None:
            missed.append({**pending_entry, "reason": "MONDAY_ENTRY_UNFILLED_BEFORE_TUESDAY_DECISION"})
            pending_entry = None

    if position is not None and quarantine is None:
        debit, count = funding_debit(position, funding_rows, exit_ms=end_ms, end_ms=end_ms, closed=False)
        position = {**position, "funding_bps_to_end_exclusive": debit, "funding_settlements": count}
    paid = sum(float(order["cost_bps"]) for order in orders)
    unresolved = int(position is not None or pending_entry is not None or pending_exit is not None or quarantine is not None)
    return {
        "schema": "zel.issue1388.monday_drift_accounting.v1",
        "candidate_id": CANDIDATE_ID,
        "signals": signals,
        "occupied_rejections": occupied,
        "missed_entries": missed,
        "orders": orders,
        "trades": trades,
        "open_position": position,
        "pending_entry": pending_entry,
        "pending_exit": pending_exit,
        "gap_quarantine": quarantine,
        "unresolved_end": unresolved,
        "paid_trading_cost_bps": paid,
        "closed_trading_cost_bps": sum(float(trade["cost_bps"]) for trade in trades),
        "open_entry_cost_bps": 0.0 if position is None else one_way,
        "disposition": ("BLOCKED_SOURCE_GAP" if quarantine is not None else
                        "BLOCKED_TERMINAL_UNRESOLVED" if unresolved else "COMPLETE"),
    }
