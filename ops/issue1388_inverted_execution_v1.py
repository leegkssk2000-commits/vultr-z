"""Pure fixed-24h lifecycle for the frozen Inverted Hammer translation.

This is a research next-open model, not the paper's same-close return or a
certification of live fills. No loading, claims, network, orders or thresholds.
The caller authenticates source flags, funding coverage and input identity.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping, Sequence

from ops.issue1388_bband_rsi_v1 import DraftError, HOUR, _funding, _funding_debit, _number, _records
from ops.issue1388_inverted_hammer_v1 import RULE_HISTORY_BARS

CANDIDATE_ID = "R_MOSER_INVERTED_HAMMER_1H_V1"
HOLD_MS = 24 * HOUR
_SIGNAL_CLOCK_FIELDS = ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")


def bind_inverted_decisions(rows: Sequence[Mapping[str, Any]], entry_flags: Sequence[bool]) -> list[dict[str, Any]]:
    """Bind supplied flags to all 150 contiguous source dependency receipts.

    This verifies clock/history binding, not the supplied morphological value.
    The existing frozen source helper computes that value. A true flag without
    its required history is invalid; warmup flags must be False.
    """
    records = _records(rows)
    if len(entry_flags) != len(records):
        raise DraftError("DECISION_LENGTH")
    history: deque[dict[str, Any]] = deque(maxlen=RULE_HISTORY_BARS)
    prior = None
    output = []
    for row, entry in zip(records, entry_flags):
        if type(entry) is not bool:
            raise DraftError("STRICT_SOURCE_DECISION_FLAGS")
        if prior is None or row["segment_id"] != prior["segment_id"] or row["open_ts_ms"] != prior["close_ts_ms"]:
            history.clear()
        history.append(row)
        if entry and len(history) != RULE_HISTORY_BARS:
            raise DraftError("SOURCE_WARMUP_REQUIRED")
        known = max(r["available_ts_ms"] for r in history)
        # Source helper requires all dependencies by this signal receipt.
        if entry and known > row["available_ts_ms"]:
            raise DraftError("SOURCE_DEPENDENCY_UNAVAILABLE")
        output.append({"signal_open_ts_ms": row["open_ts_ms"], "signal_close_ts_ms": row["close_ts_ms"],
                       "signal_available_ts_ms": known, "segment_id": row["segment_id"], "entry": entry})
        prior = row
    return output


def _bound_decisions(records: list[dict[str, Any]], decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not all(isinstance(d, Mapping) for d in decisions):
        raise DraftError("DECISION_MAPPING")
    try:
        expected = bind_inverted_decisions(records, [d["entry"] for d in decisions])
    except KeyError:
        raise DraftError("DECISION_FIELDS") from None
    if list(decisions) != expected:
        raise DraftError("DECISION_SOURCE_OR_CLOCK_BINDING")
    return expected


def replay_inverted_hammer(symbol: str, rows: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
                           funding_rows: Sequence[Mapping[str, Any]] | None, *, start_ms: int, end_ms: int,
                           roundtrip_cost_bps: float) -> dict[str, Any]:
    """One long unit/symbol; causal next open; due open entry+24h.

    An open price is the common runner's modeled executable observed open, not
    the future completed candle receipt. Entry waits for all signal receipts;
    the deterministic timer exit needs no current/future candle indicator.
    A missing bar or changed segment while pending/occupied quarantines exact
    state before using the later open. No END fill, SL/TP or intrabar execution.
    Signed funding uses the existing conservative boundary convention. Missing
    coverage is caller-certified; None is unknown, never an assumed zero.
    """
    if not isinstance(symbol, str) or not symbol:
        raise DraftError("SYMBOL_REQUIRED")
    if any(type(t) is not int or t % HOUR for t in (start_ms, end_ms)) or start_ms >= end_ms:
        raise DraftError("FIXED_WINDOW")
    one_way = _number(roundtrip_cost_bps, positive=True) / 2
    records = _records(rows)
    bound = _bound_decisions(records, decisions)
    if not any(r["open_ts_ms"] == start_ms for r in records) or not any(r["close_ts_ms"] == end_ms for r in records):
        raise DraftError("FIXED_START_END_SOURCE_COVERAGE")
    funding = None if funding_rows is None else _funding(funding_rows, symbol)
    trades, orders = [], []
    position = pending_entry = quarantine = prior = None
    signal_count = occupied = pending_rejections = 0
    for bar, decision in zip(records, bound):
        stamp = bar["open_ts_ms"]
        if stamp >= end_ms:
            break
        gap = prior is not None and (stamp != prior["close_ts_ms"] or bar["segment_id"] != prior["segment_id"])
        if gap and (position is not None or pending_entry is not None):
            quarantine = {"gap_ts_ms": stamp, "position": position, "pending_entry": pending_entry}
            break
        prior = bar
        if stamp < start_ms:
            continue
        if position is not None and stamp >= position["exit_due_ts_ms"]:
            gross = (bar["open"] / position["entry_price"] - 1) * 10_000
            debit, count = (None, None) if funding is None else _funding_debit(position, funding, stamp, end_ms, closed=True)
            trades.append({**position, "exit_ts_ms": stamp, "exit_price": bar["open"],
                           "exit_reason": "NEXT_AVAILABLE_OPEN_FIXED24H", "exit_time_kind": "OBSERVED_OPEN",
                           "gross_bps": gross, "cost_bps": 2 * one_way, "funding_bps": debit,
                           "funding_settlements": count, "net_bps": None if debit is None else gross - 2 * one_way - debit})
            orders.append({"kind": "EXIT", "execution_ts_ms": stamp, "price": bar["open"], "quantity": 1,
                           "cost_bps": one_way, "entry_identity": position["entry_identity"],
                           "exit_due_ts_ms": position["exit_due_ts_ms"], "reason": "NEXT_AVAILABLE_OPEN_FIXED24H"})
            position = None
        if pending_entry is not None and position is None and pending_entry["signal_available_ts_ms"] <= stamp:
            identity = f"{symbol}:{stamp}:{pending_entry['signal_open_ts_ms']}"
            position = {"identity": CANDIDATE_ID, "entry_identity": identity, "symbol": symbol, "side": "LONG",
                        "entry_ts_ms": stamp, "entry_price": bar["open"], "entry_cost_bps": one_way,
                        "exit_due_ts_ms": stamp + HOLD_MS,
                        **{key: pending_entry[key] for key in _SIGNAL_CLOCK_FIELDS}}
            orders.append({"kind": "ENTRY", "execution_ts_ms": stamp, "price": bar["open"], "quantity": 1,
                           "cost_bps": one_way, "entry_identity": identity,
                           **{key: pending_entry[key] for key in _SIGNAL_CLOCK_FIELDS}})
            pending_entry = None
        # Source signal belongs to completed bar; END-close cannot make orders.
        if decision["signal_close_ts_ms"] < end_ms and decision["entry"]:
            signal_count += 1
            if position is None and pending_entry is None:
                pending_entry = decision.copy()
            elif position is not None:
                occupied += 1
            else:
                pending_rejections += 1
    if position is not None:
        debit, count = ((None, None) if funding is None or quarantine is not None else
                        _funding_debit(position, funding, end_ms, end_ms, closed=False))
        position = {**position, "funding_bps_to_end_exclusive": debit, "funding_settlements": count}
    paid = sum(o["cost_bps"] for o in orders)
    closed = sum(t["cost_bps"] for t in trades)
    open_cost = position["entry_cost_bps"] if position is not None else 0.0
    if not math.isclose(paid, closed + open_cost, abs_tol=1e-9):
        raise DraftError("PAID_FEE_RECONCILIATION")
    unresolved = int(position is not None or pending_entry is not None or quarantine is not None)
    disposition = ("BLOCKED_SOURCE_GAP" if quarantine is not None else "BLOCKED_TERMINAL_UNRESOLVED" if unresolved
                   else "BLOCKED_MISSING_FUNDING" if funding is None else "DRAFT_ONLY_NO_VERDICT")
    return {"classification": "INTERNAL_CAUSAL_NEXT_OPEN_FIXED24H_NOT_PAPER_RETURN_REPRODUCTION",
            "candidate_id": CANDIDATE_ID, "period_ms": [start_ms, end_ms], "symbol": symbol,
            "fixed_hold_ms": HOLD_MS, "trades": trades, "orders": orders, "open_position": position,
            "pending_entry": pending_entry, "pending_exit": None, "gap_quarantine": quarantine,
            "signals": signal_count, "occupied_rejections": occupied, "pending_entry_rejections": pending_rejections,
            "unresolved_end": unresolved, "paid_trading_cost_bps": paid, "closed_trading_cost_bps": closed,
            "open_entry_cost_bps": open_cost, "disposition": disposition,
            "economic_disposition": "NOT_EVALUATED_NO_THRESHOLD_ADDED",
            "source_signal_values_certified_by_helper": False, "funding_coverage_certified_by_helper": False,
            "source_profits_reproduced": False, "account_nav": None}
