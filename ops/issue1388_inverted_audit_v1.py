"""Independent saved-ledger certificates for the frozen 24-hour translation.

No market loading, claims, orders or lifecycle replay. Source flags may be
recomputed; saved fills are certified against causal observed-open intervals.
This certifies the disclosed ZEL translation, not source profits or live fills.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import pandas as pd

from ops.issue1388_inverted_hammer_v1 import inverted_hammer_census_flags

HOUR = 3_600_000
HOLD = 24 * HOUR
CANDIDATE_ID = "R_MOSER_INVERTED_HAMMER_1H_V1"
CLOCKS = ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")


class AuditError(ValueError):
    """Saved evidence cannot be independently certified."""


def _finite(value: Any, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise AuditError("IH_AUDIT_NUMERIC_INPUT")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AuditError("IH_AUDIT_NUMERIC_INPUT") from None
    if not math.isfinite(number) or positive and number <= 0:
        raise AuditError("IH_AUDIT_NUMERIC_INPUT")
    return number


def _source(rows: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(rows)
    try:
        flags, ready = inverted_hammer_census_flags(frame)
    except (ValueError, TypeError, KeyError) as exc:
        raise AuditError("IH_AUDIT_SOURCE_INPUT") from exc
    if len(rows) != len(decisions):
        raise AuditError("IH_AUDIT_DECISION_LENGTH")
    run_start = 0
    for index, (row, decision, flag) in enumerate(zip(rows, decisions, flags.tolist())):
        if index == 0 or row["segment_id"] != rows[index - 1]["segment_id"] or row["open_ts_ms"] != rows[index - 1]["close_ts_ms"]:
            run_start = index
        received = max(r["available_ts_ms"] for r in rows[max(run_start, index - 149):index + 1])
        if not isinstance(decision, Mapping) or type(decision.get("entry")) is not bool:
            raise AuditError("IH_AUDIT_SOURCE_FLAG")
        if decision["entry"] != flag:
            raise AuditError("IH_AUDIT_SOURCE_FLAG")
        if (decision.get("signal_open_ts_ms") != row["open_ts_ms"]
                or decision.get("signal_close_ts_ms") != row["close_ts_ms"]
                or decision.get("signal_available_ts_ms") != received
                or decision.get("segment_id") != row["segment_id"]):
            raise AuditError("IH_AUDIT_SOURCE_CLOCK")
    return [dict(d) for d in decisions]


def _signed_funding(symbol: str, funding: Sequence[Mapping[str, Any]] | None,
                    entry: int, end: int, price: float, window_end: int,
                    closed: bool) -> tuple[float | None, int | None]:
    if funding is None:
        return None, None
    stamps = set()
    debit, count = 0.0, 0
    for row in sorted(funding, key=lambda r: r["fundingTime"]):
        stamp = row.get("fundingTime")
        if type(stamp) is not int or stamp in stamps or row.get("symbol") != symbol:
            raise AuditError("IH_AUDIT_FUNDING_IDENTITY")
        stamps.add(stamp)
        amount = _finite(row.get("fundingRate")) * _finite(row.get("markPrice"), True) / price * 10_000
        if entry <= stamp <= end and stamp < window_end:
            # Unknown exact-boundary settlement membership: adverse debit only.
            if stamp != entry and (not closed or stamp != end) or amount > 0:
                debit += amount
                count += 1
    return debit, count


def _equal(actual: Any, expected: Any, name: str) -> None:
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9):
            raise AuditError("IH_AUDIT_" + name)
    elif isinstance(expected, dict):
        if not isinstance(actual, Mapping) or set(actual) != set(expected):
            raise AuditError("IH_AUDIT_" + name)
        for key, value in expected.items():
            _equal(actual[key], value, name + "_" + key.upper())
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AuditError("IH_AUDIT_" + name)
        for value, target in zip(actual, expected):
            _equal(value, target, name)
    elif type(actual) is not type(expected) or actual != expected:
        raise AuditError("IH_AUDIT_" + name)


def audit_inverted_symbol(symbol: str, rows: Sequence[Mapping[str, Any]],
                           decisions: Sequence[Mapping[str, Any]],
                           funding_rows: Sequence[Mapping[str, Any]] | None, *,
                           start_ms: int, end_ms: int, roundtrip_cost_bps: float,
                           saved: Mapping[str, Any]) -> dict[str, Any]:
    """Certify a saved ledger by independently partitioning admissible intervals.

    Each flat interval selects its first source signal. A certificate enumerates
    every observed open from that signal through its earliest eligible fill and
    first timer-due open, rejecting any intervening gap. Thus dropped trades,
    shifted entries/exits and coordinated outer-hash changes remain detectable.
    The source flag helper is reused, never the order/lifecycle replay function.
    Funding archive *coverage* and source/input archive hashes remain the
    authenticated common caller's responsibility; None stays unknown.
    """
    if not isinstance(symbol, str) or not symbol or any(type(t) is not int or t % HOUR for t in (start_ms, end_ms)) or start_ms >= end_ms:
        raise AuditError("IH_AUDIT_WINDOW_SYMBOL")
    source = _source(rows, decisions)
    if not any(r["open_ts_ms"] == start_ms for r in rows) or not any(r["close_ts_ms"] == end_ms for r in rows):
        raise AuditError("IH_AUDIT_SOURCE_COVERAGE")
    fee = _finite(roundtrip_cost_bps, True) / 2
    for row in rows:
        for key in ("open", "high", "low", "close"):
            _finite(row[key], True)
    indices = [i for i, d in enumerate(source) if d["entry"] and start_ms <= rows[i]["open_ts_ms"] < end_ms and d["signal_close_ts_ms"] < end_ms]
    opens = [i for i, r in enumerate(rows) if start_ms <= r["open_ts_ms"] < end_ms]
    gaps = {i for i in range(1, len(rows)) if rows[i]["open_ts_ms"] != rows[i - 1]["close_ts_ms"] or rows[i]["segment_id"] != rows[i - 1]["segment_id"]}
    orders, trades, certificates = [], [], []
    cursor, signal_count, occupied, rejected_pending = 0, 0, 0, 0
    position = pending = quarantine = None
    while True:
        signal_index = next((i for i in indices if i >= cursor), None)
        if signal_index is None:
            break
        decision = source[signal_index]
        signal_count += 1
        fill_index = next((i for i in opens if i > signal_index and rows[i]["open_ts_ms"] >= decision["signal_available_ts_ms"]), None)
        first_gap = next((i for i in sorted(gaps) if i > signal_index and rows[i]["open_ts_ms"] < end_ms and (fill_index is None or i <= fill_index)), None)
        pending_stop = first_gap if first_gap is not None else fill_index
        waiting = [i for i in indices if i > signal_index and (pending_stop is None or i < pending_stop)]
        rejected_pending += len(waiting)
        signal_count += len(waiting)
        if first_gap is not None or fill_index is None:
            pending = decision.copy()
            if first_gap is not None:
                quarantine = {"gap_ts_ms": rows[first_gap]["open_ts_ms"], "position": None, "pending_entry": pending}
            certificates.append({"signal_index": signal_index, "first_fill_index": None, "first_gap_index": first_gap})
            break
        bar = rows[fill_index]
        stamp, price = bar["open_ts_ms"], float(bar["open"])
        identity = f"{symbol}:{stamp}:{decision['signal_open_ts_ms']}"
        position = {"identity": CANDIDATE_ID, "entry_identity": identity, "symbol": symbol, "side": "LONG",
                    "entry_ts_ms": stamp, "entry_price": price, "entry_cost_bps": fee,
                    "exit_due_ts_ms": stamp + HOLD, **{k: decision[k] for k in CLOCKS}}
        orders.append({"kind": "ENTRY", "execution_ts_ms": stamp, "price": price, "quantity": 1,
                       "cost_bps": fee, "entry_identity": identity, **{k: decision[k] for k in CLOCKS}})
        due_index = next((i for i in opens if i > fill_index and rows[i]["open_ts_ms"] >= stamp + HOLD), None)
        first_gap = next((i for i in sorted(gaps) if i > fill_index and rows[i]["open_ts_ms"] < end_ms and (due_index is None or i <= due_index)), None)
        occupied_stop = first_gap if first_gap is not None else due_index
        blocked_signals = [i for i in indices if i >= fill_index and (occupied_stop is None or i < occupied_stop)]
        occupied += len(blocked_signals)
        signal_count += len(blocked_signals)
        certificates.append({"signal_index": signal_index, "first_fill_index": fill_index,
                             "first_due_index": due_index if first_gap is None else None, "first_gap_index": first_gap})
        if first_gap is not None:
            quarantine = {"gap_ts_ms": rows[first_gap]["open_ts_ms"], "position": position.copy(), "pending_entry": None}
            break
        if due_index is None:
            break
        exit_bar = rows[due_index]
        exit_stamp, exit_price = exit_bar["open_ts_ms"], float(exit_bar["open"])
        gross = (exit_price / price - 1) * 10_000
        debit, settlements = _signed_funding(symbol, funding_rows, stamp, exit_stamp, price, end_ms, True)
        trades.append({**position, "exit_ts_ms": exit_stamp, "exit_price": exit_price,
                       "exit_reason": "NEXT_AVAILABLE_OPEN_FIXED24H", "exit_time_kind": "OBSERVED_OPEN",
                       "gross_bps": gross, "cost_bps": 2 * fee, "funding_bps": debit,
                       "funding_settlements": settlements, "net_bps": None if debit is None else gross - 2 * fee - debit})
        orders.append({"kind": "EXIT", "execution_ts_ms": exit_stamp, "price": exit_price, "quantity": 1,
                       "cost_bps": fee, "entry_identity": identity, "exit_due_ts_ms": stamp + HOLD,
                       "reason": "NEXT_AVAILABLE_OPEN_FIXED24H"})
        position = None
        cursor = due_index
    if position is not None:
        debit, settlements = ((None, None) if quarantine is not None else
                              _signed_funding(symbol, funding_rows, position["entry_ts_ms"], end_ms,
                                              position["entry_price"], end_ms, False))
        position = {**position, "funding_bps_to_end_exclusive": debit, "funding_settlements": settlements}
    unresolved = int(position is not None or pending is not None or quarantine is not None)
    disposition = ("BLOCKED_SOURCE_GAP" if quarantine is not None else "BLOCKED_TERMINAL_UNRESOLVED" if unresolved
                   else "BLOCKED_MISSING_FUNDING" if funding_rows is None else "DRAFT_ONLY_NO_VERDICT")
    paid = sum(order["cost_bps"] for order in orders)
    expected = {"classification": "INTERNAL_CAUSAL_NEXT_OPEN_FIXED24H_NOT_PAPER_RETURN_REPRODUCTION",
                "candidate_id": CANDIDATE_ID, "period_ms": [start_ms, end_ms], "symbol": symbol,
                "fixed_hold_ms": HOLD, "trades": trades, "orders": orders, "open_position": position,
                "pending_entry": pending, "pending_exit": None, "gap_quarantine": quarantine,
                "signals": signal_count, "occupied_rejections": occupied, "pending_entry_rejections": rejected_pending,
                "unresolved_end": unresolved, "paid_trading_cost_bps": paid,
                "closed_trading_cost_bps": sum(t["cost_bps"] for t in trades),
                "open_entry_cost_bps": fee if position is not None else 0.0,
                "disposition": disposition, "economic_disposition": "NOT_EVALUATED_NO_THRESHOLD_ADDED",
                "source_signal_values_certified_by_helper": False, "funding_coverage_certified_by_helper": False,
                "source_profits_reproduced": False, "account_nav": None}
    _equal(saved, expected, "SAVED_LEDGER")
    return {"classification": "INDEPENDENT_SOURCE_AND_CAUSAL_INTERVAL_CERTIFICATE",
            "candidate_id": CANDIDATE_ID, "symbol": symbol, "source_flags_recomputed": True,
            "lifecycle_replay_called": False, "certificates": certificates, "closed_trades": len(trades),
            "signals": signal_count, "paid_trading_cost_bps": paid, "unresolved_end": unresolved,
            "funding_archive_coverage_certified": False, "source_profits_reproduced": False}


# Keep the descriptive name available to the standalone artificial fixtures.
audit_inverted_hammer = audit_inverted_symbol
