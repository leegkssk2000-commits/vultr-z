"""Hansen source-lifecycle execution translation for the common runner.

No loaders/network/claims/activation. Source indicators stay in the pinned common
hansen_source_decision_flags helper: this module binds their supplied decisions
and models fixed-unit long execution. It does not reproduce donor exchange/runtime config,
live fills, source profits or account NAV. Caller authenticates all input archives.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Mapping, Sequence

HOUR = 3_600_000
STOP_RATIO = 0.90
ROI_RATIO = 11.0
CANDIDATE_ID = "E_HANSEN_CANDLE_PATTERN_1H_V1"
_SIGNAL_CLOCK_FIELDS = ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")


class DraftError(ValueError):
    pass


def _thresholds(entry_price: float) -> tuple[float, float]:
    # Exact fixed decimal ratios; no invented tick or comparison tolerance.
    basis = Decimal(str(entry_price))
    return float(basis * Decimal("0.90")), float(basis * Decimal("11.0"))


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
    output = []
    prior = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("HOURLY_MAPPING_REQUIRED")
        try:
            opened, closed, received = (row[k] for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms"))
            segment = row["segment_id"]
            prices = {k: _number(row[k], positive=True) for k in ("open", "high", "low", "close")}
        except KeyError:
            raise DraftError("HOURLY_FIELDS_REQUIRED") from None
        if (any(type(t) is not int for t in (opened, closed, received)) or opened % HOUR
                or closed != opened + HOUR or received < closed
                or (type(segment) is not int and (not isinstance(segment, str) or not segment))
                or (prior is not None and opened <= prior)):
            raise DraftError("HOURLY_CLOCK_OR_SEGMENT")
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]) or prices["low"] > prices["high"]:
            raise DraftError("OHLC_ENVELOPE")
        output.append({**row, **prices})
        prior = opened
    return output


def bind_hansen_decisions(rows: Sequence[Mapping[str, Any]], entry_flags: Sequence[bool],
                         exit_flags: Sequence[bool]) -> list[dict[str, Any]]:
    """Bind source-native entry flags and strict source SMA6(hopen)>SMA6(hclose) exit flags once.

    The source SMA state depends on its full segment prefix. Bound receipt therefore covers
    every prior/current segment row, rather than assuming ordered delivery.
    This is a structural/clock binder, not verification of supplied signal values.
    """
    records = _records(rows)
    if len(entry_flags) != len(records) or len(exit_flags) != len(records):
        raise DraftError("DECISION_LENGTH")
    output = []
    prior = None
    prefix_receipt = 0
    for row, entry, exit_ in zip(records, entry_flags, exit_flags):
        if type(entry) is not bool or type(exit_) is not bool or (entry and exit_):
            raise DraftError("STRICT_SOURCE_DECISION_FLAGS")
        if prior is None or row["segment_id"] != prior["segment_id"] or row["open_ts_ms"] != prior["close_ts_ms"]:
            prefix_receipt = row["available_ts_ms"]
        else:
            prefix_receipt = max(prefix_receipt, row["available_ts_ms"])
        output.append({"signal_open_ts_ms": row["open_ts_ms"], "signal_close_ts_ms": row["close_ts_ms"],
                       "signal_available_ts_ms": prefix_receipt, "segment_id": row["segment_id"],
                       "entry": entry, "exit": exit_})
        prior = row
    return output


def _bound_decisions(records: list[dict[str, Any]], decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not all(isinstance(d, Mapping) for d in decisions):
        raise DraftError("DECISION_MAPPING")
    try:
        expected = bind_hansen_decisions(records, [d["entry"] for d in decisions], [d["exit"] for d in decisions])
    except KeyError:
        raise DraftError("DECISION_FIELDS") from None
    if list(decisions) != expected:
        raise DraftError("DECISION_SOURCE_OR_CLOCK_BINDING")
    return expected


def _funding(rows: Sequence[Mapping[str, Any]], symbol: str) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("FUNDING_MAPPING")
        stamp = row.get("fundingTime")
        if type(stamp) is not int or stamp in seen or row.get("symbol") != symbol:
            raise DraftError("FUNDING_CLOCK_DUPLICATE_OR_SYMBOL")
        seen.add(stamp)
        output.append({"fundingTime": stamp, "fundingRate": _number(row.get("fundingRate")),
                       "markPrice": _number(row.get("markPrice"), positive=True)})
    return sorted(output, key=lambda r: r["fundingTime"])


def _funding_debit(position: Mapping[str, Any], rows: list[dict[str, Any]], exit_ms: int,
                   end_ms: int, *, closed: bool) -> tuple[float, int]:
    total = 0.0
    count = 0
    for row in rows:
        stamp = row["fundingTime"]
        if position["entry_ts_ms"] <= stamp <= exit_ms and stamp < end_ms:
            debit = row["fundingRate"] * row["markPrice"] / position["entry_price"] * 10_000
            boundary = stamp == position["entry_ts_ms"] or (closed and stamp == exit_ms)
            if not boundary or debit > 0:
                total += debit
                count += 1
    return total, count


def replay_hansen(symbol: str, rows: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
                     funding_rows: Sequence[Mapping[str, Any]] | None, *, start_ms: int, end_ms: int,
                     roundtrip_cost_bps: float) -> dict[str, Any]:
    """Pure conservative source-lifecycle adapter with frozen source ROI1000%/SL10%.

    Earliest observed open after all decision dependencies are available. Known
    opening stop/ROI takes precedence over source exit, then normal-open intrabar
    ambiguity is stop-first. A late exit stays bound to its original position.
    Occupied source gaps preserve/quarantine exact state. No END order/liquidation;
    last-bar protective touch is retained as unresolved evidence, not an END fill.
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
    position = pending_entry = pending_exit = quarantine = terminal_touch = protective_quarantine = prior = None
    signal_count = occupied = pending_rejections = 0

    def close(stamp: int, price: float, reason: str, *, intrabar: bool = False) -> None:
        nonlocal position, pending_exit
        signal_clocks = ({key: pending_exit[key] for key in _SIGNAL_CLOCK_FIELDS}
                         if reason == "NEXT_AVAILABLE_OPEN_HANSEN_EXIT" else {})
        gross = (price / position["entry_price"] - 1) * 10_000
        trade = {**position, "exit_ts_ms": stamp, "exit_price": price, "exit_reason": reason,
                 "exit_time_kind": "MODELED_BAR_CLOSE_INTRABAR_TOUCH" if intrabar else "OBSERVED_OPEN",
                 "gross_bps": gross, "cost_bps": 2 * one_way,
                 **{"exit_" + key: value for key, value in signal_clocks.items()}}
        debit, count = (None, None) if funding is None else _funding_debit(position, funding, stamp, end_ms, closed=True)
        trade.update(funding_bps=debit, funding_settlements=count,
                     net_bps=None if debit is None else gross - 2 * one_way - debit)
        trades.append(trade)
        orders.append({"kind": "EXIT", "execution_ts_ms": stamp, "price": price, "quantity": 1,
                       "cost_bps": one_way, "entry_identity": position["entry_identity"], "reason": reason,
                       **signal_clocks})
        position = pending_exit = None

    for bar, decision in zip(records, bound):
        stamp = bar["open_ts_ms"]
        if stamp >= end_ms:
            break
        gap = prior is not None and (stamp != prior["close_ts_ms"] or bar["segment_id"] != prior["segment_id"])
        if gap and (position is not None or pending_entry is not None or pending_exit is not None):
            quarantine = {"gap_ts_ms": stamp, "position": position, "pending_entry": pending_entry, "pending_exit": pending_exit}
            break
        prior = bar
        if stamp < start_ms:
            continue
        if position is not None:
            stop, roi = _thresholds(position["entry_price"])
            if bar["open"] <= stop:
                close(stamp, bar["open"], "OPEN_STOP")
            elif bar["open"] >= roi:
                close(stamp, bar["open"], "OPEN_ROI")
            elif pending_exit is not None and pending_exit["signal_available_ts_ms"] <= stamp:
                if pending_exit["entry_identity"] != position["entry_identity"]:
                    raise DraftError("EXIT_POSITION_BINDING")
                close(stamp, bar["open"], "NEXT_AVAILABLE_OPEN_HANSEN_EXIT")
        if pending_entry is not None and position is None and pending_entry["signal_available_ts_ms"] <= stamp:
            identity = f"{symbol}:{stamp}:{pending_entry['signal_open_ts_ms']}"
            position = {"identity": CANDIDATE_ID, "entry_identity": identity, "symbol": symbol, "side": "LONG",
                        "entry_ts_ms": stamp, "entry_price": bar["open"], "entry_cost_bps": one_way,
                        **{k: pending_entry[k] for k in ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")}}
            orders.append({"kind": "ENTRY", "execution_ts_ms": stamp, "price": bar["open"], "quantity": 1,
                           "cost_bps": one_way, "entry_identity": identity,
                           **{key: pending_entry[key] for key in _SIGNAL_CLOCK_FIELDS}})
            pending_entry = None
        if position is not None:
            stop, roi = _thresholds(position["entry_price"])
            touch = "INTRABAR_STOP_FIRST" if bar["low"] <= stop else ("INTRABAR_ROI" if bar["high"] >= roi else None)
            if touch is not None:
                price = stop if touch == "INTRABAR_STOP_FIRST" else roi
                if bar["close_ts_ms"] == end_ms:
                    terminal_touch = {"bar_open_ts_ms": stamp, "bar_close_ts_ms": end_ms,
                                      "entry_identity": position["entry_identity"], "reason": touch, "threshold_price": price,
                                      "classification": "UNRESOLVED_TOUCH_NO_END_ORDER"}
                elif bar["available_ts_ms"] > bar["close_ts_ms"]:
                    # Standard SSOT delivery is modeled at close. A late touch
                    # receipt cannot prove that close-time execution/ownership.
                    # Preserve exact state rather than credit unproven funding.
                    protective_quarantine = {"bar_open_ts_ms": stamp, "bar_close_ts_ms": bar["close_ts_ms"],
                                             "available_ts_ms": bar["available_ts_ms"], "reason": touch,
                                             "threshold_price": price, "position": position,
                                             "pending_entry": pending_entry, "pending_exit": pending_exit}
                    break
                else:
                    close(bar["close_ts_ms"], price, touch, intrabar=True)
        # Signals are completed-bar facts. END-close cannot create a new order.
        if decision["signal_close_ts_ms"] < end_ms:
            if decision["entry"]:
                signal_count += 1
                if position is None and pending_entry is None:
                    pending_entry = decision.copy()
                elif position is not None:
                    occupied += 1
                else:
                    pending_rejections += 1
            if decision["exit"] and position is not None and pending_exit is None:
                pending_exit = {**decision, "entry_identity": position["entry_identity"]}
    if position is not None:
        if funding is None or quarantine is not None or terminal_touch is not None or protective_quarantine is not None:
            debit = count = None
        else:
            debit, count = _funding_debit(position, funding, end_ms, end_ms, closed=False)
        position = {**position, "funding_bps_to_end_exclusive": debit, "funding_settlements": count}
    paid_fee = sum(o["cost_bps"] for o in orders)
    closed_fee = sum(t["cost_bps"] for t in trades)
    open_fee = position["entry_cost_bps"] if position is not None else 0.0
    if not math.isclose(paid_fee, closed_fee + open_fee, abs_tol=1e-9):
        raise DraftError("PAID_FEE_RECONCILIATION")
    unresolved = int(position is not None or pending_entry is not None or pending_exit is not None or quarantine is not None or protective_quarantine is not None)
    disposition = "BLOCKED_SOURCE_GAP" if quarantine is not None else (
        "BLOCKED_PROTECTIVE_TOUCH_CLOCK_UNRESOLVED" if protective_quarantine is not None else (
        "BLOCKED_TERMINAL_UNRESOLVED" if unresolved else ("BLOCKED_MISSING_FUNDING" if funding is None else "DRAFT_ONLY_NO_VERDICT")))
    return {"classification": "INTERNAL_CONSERVATIVE_CLASS_DEFAULT_ADAPTER_NOT_DONOR_CONFIG_REPRODUCTION",
            "candidate_id": CANDIDATE_ID, "period_ms": [start_ms, end_ms], "symbol": symbol,
            "frozen_roi_ratio": ROI_RATIO, "frozen_stop_ratio": STOP_RATIO,
            "trades": trades, "orders": orders, "open_position": position,
            "pending_entry": pending_entry, "pending_exit": pending_exit, "gap_quarantine": quarantine,
            "terminal_protective_touch": terminal_touch, "protective_touch_quarantine": protective_quarantine,
            "signals": signal_count, "occupied_rejections": occupied,
            "pending_entry_rejections": pending_rejections, "unresolved_end": unresolved,
            "paid_trading_cost_bps": paid_fee, "closed_trading_cost_bps": closed_fee, "open_entry_cost_bps": open_fee,
            "disposition": disposition, "economic_disposition": "NOT_EVALUATED_NO_THRESHOLD_ADDED",
            "source_signal_values_certified_by_helper": False, "funding_coverage_certified_by_helper": False,
            "source_profits_reproduced": False, "account_nav": None,
            "gap_risk_priority": "KNOWN_OPEN_STOP_THEN_OPEN_ROI_THEN_HANSEN_EXIT_THEN_INTRABAR_STOP_FIRST"}


