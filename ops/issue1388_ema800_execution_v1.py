"""EMA800 pure conservative lifecycle. Reuses common clock/funding primitives.

Source MIT Paul Csapak EMA800 / crossbelow0.99 / stoploss-0.15 unchanged.
Explicit INTERNAL translation of official Freqtrade2021.5 absent-config defaults;
ROI rate10.0 is1000% (gross ratio11). Not author's config/profits/feeROI engine.
Trailing uses only received completed prior highs; no current-high-before-low.
No loaders, orders to exchanges, approvals, claims or activation in this module.
"""
from __future__ import annotations
from decimal import Decimal
import math
from typing import Any, Mapping, Sequence
from ops.issue1388_bband_rsi_v1 import (HOUR, DraftError, _number, _records,
    _bound_decisions, _funding, _funding_debit, _SIGNAL_CLOCK_FIELDS)

STOP_RATIO = 0.85
ROI_RATIO = 11.0
CANDIDATE_ID = "E_FT_EMA800_PRICE_THRESHOLD_1H_V1"

def _stop(high: float) -> float:
    return float(Decimal(str(high)) * Decimal("0.85"))

def _roi(entry: float) -> float:
    return float(Decimal(str(entry)) * Decimal("11"))

def replay_ema800(symbol: str, rows: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
                     funding_rows: Sequence[Mapping[str, Any]] | None, *, start_ms: int, end_ms: int,
                     roundtrip_cost_bps: float) -> dict[str, Any]:
    """Pure conservative class-default adapter with frozen ROI1000%/SL15% trailing.

    Earliest observed open after all decision dependencies are available. Known
    opening stop/ROI takes precedence over EMA exit, then normal-open intrabar
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
    stop_price = None
    received_highs = []
    signal_count = occupied = pending_rejections = 0

    def close(stamp: int, price: float, reason: str, *, intrabar: bool = False) -> None:
        nonlocal position, pending_exit
        signal_clocks = ({key: pending_exit[key] for key in _SIGNAL_CLOCK_FIELDS}
                         if reason == "NEXT_AVAILABLE_OPEN_EMA_EXIT" else {})
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
            # Only completed highs received before this open may raise the stop.
            for receipt, high in received_highs:
                if receipt <= stamp:
                    stop_price = max(stop_price, _stop(high))
            received_highs = [(receipt, high) for receipt, high in received_highs if receipt > stamp]
            stop, roi = (stop_price, _roi(position["entry_price"]))
            if bar["open"] <= stop:
                close(stamp, bar["open"], "OPEN_STOP")
            elif bar["open"] >= roi:
                close(stamp, bar["open"], "OPEN_ROI")
            elif pending_exit is not None and pending_exit["signal_available_ts_ms"] <= stamp:
                if pending_exit["entry_identity"] != position["entry_identity"]:
                    raise DraftError("EXIT_POSITION_BINDING")
                close(stamp, bar["open"], "NEXT_AVAILABLE_OPEN_EMA_EXIT")
        if pending_entry is not None and position is None and pending_entry["signal_available_ts_ms"] <= stamp:
            identity = f"{symbol}:{stamp}:{pending_entry['signal_open_ts_ms']}"
            position = {"identity": CANDIDATE_ID, "entry_identity": identity, "symbol": symbol, "side": "LONG",
                        "entry_ts_ms": stamp, "entry_price": bar["open"], "entry_cost_bps": one_way,
                        **{k: pending_entry[k] for k in ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")}}
            stop_price = _stop(bar["open"])
            received_highs = []
            orders.append({"kind": "ENTRY", "execution_ts_ms": stamp, "price": bar["open"], "quantity": 1,
                           "cost_bps": one_way, "entry_identity": identity,
                           **{key: pending_entry[key] for key in _SIGNAL_CLOCK_FIELDS}})
            pending_entry = None
        if position is not None:
            stop, roi = (stop_price, _roi(position["entry_price"]))
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
        if position is not None:
            received_highs.append((bar["available_ts_ms"], bar["high"]))
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
            "trailing_update_policy": "PRIOR_COMPLETED_RECEIVED_HIGH_ONLY",
            "open_stop_price": stop_price if position is not None else None,
            "trades": trades, "orders": orders, "open_position": position,
            "pending_entry": pending_entry, "pending_exit": pending_exit, "gap_quarantine": quarantine,
            "terminal_protective_touch": terminal_touch, "protective_touch_quarantine": protective_quarantine,
            "signals": signal_count, "occupied_rejections": occupied,
            "pending_entry_rejections": pending_rejections, "unresolved_end": unresolved,
            "paid_trading_cost_bps": paid_fee, "closed_trading_cost_bps": closed_fee, "open_entry_cost_bps": open_fee,
            "disposition": disposition, "economic_disposition": "NOT_EVALUATED_NO_THRESHOLD_ADDED",
            "source_signal_values_certified_by_helper": False, "funding_coverage_certified_by_helper": False,
            "source_profits_reproduced": False, "account_nav": None,
            "gap_risk_priority": "KNOWN_OPEN_STOP_THEN_OPEN_ROI_THEN_EMA_EXIT_THEN_INTRABAR_STOP_FIRST"}
