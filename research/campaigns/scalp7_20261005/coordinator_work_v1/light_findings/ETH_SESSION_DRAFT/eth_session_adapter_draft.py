"""Isolated, unintegrated Issue1388 ETH session accounting draft.

Pure helpers: no files, network, claims, CLI, activation or market loading.
Direction follows the existing source-exact session decision helper. Execution
and fixed unit positions are INTERNAL_TRANSLATION, not source portfolio return
or rebalancing replication. Existing normalized round-trip cost is unchanged.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

HOUR = 3_600_000


class DraftError(ValueError):
    pass


def _finite(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise DraftError("INVALID_NUMBER")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DraftError("INVALID_NUMBER") from None
    if not math.isfinite(number) or (positive and number <= 0):
        raise DraftError("INVALID_NUMBER")
    return number


def _records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    previous = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("HOURLY_RECORD_REQUIRED")
        try:
            opened, closed, available = (row[k] for k in
                                        ("open_ts_ms", "close_ts_ms", "available_ts_ms"))
            segment = row["segment_id"]
            opening, closing = _finite(row["open"], positive=True), _finite(row["close"], positive=True)
        except KeyError:
            raise DraftError("HOURLY_FIELDS_REQUIRED") from None
        if (any(type(t) is not int for t in (opened, closed, available))
                or opened % HOUR or closed != opened + HOUR or available < closed
                or (type(segment) is not int and (not isinstance(segment, str) or not segment))
                or (previous is not None and opened <= previous)):
            raise DraftError("HOURLY_CLOCK_OR_SEGMENT_INVALID")
        clean.append({**row, "open": opening, "close": closing})
        previous = opened
    return clean


def unit_transition(current: int, desired: int, roundtrip_cost_bps: float) -> tuple[int, float]:
    if type(current) is not int or type(desired) is not int or current not in (-1, 0, 1) or desired not in (-1, 0, 1):
        raise DraftError("SIGNED_UNIT_TARGET_REQUIRED")
    quantity = abs(desired - current)
    return quantity, quantity * _finite(roundtrip_cost_bps, positive=True) / 2


def eth_session_targets(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expose desired signed units and dependency clocks, without execution.

    05:00 uses the previous completed day session's boundary closes; 17:00
    schedules long. Current boundary candle close/open never chooses direction.
    Segment/time gaps reset day-return inputs. Targets expire at next boundary.
    """
    records = _records(rows)
    output = []
    prior = day_start = prior_day = None
    for row in records:
        opened = row["open_ts_ms"]
        if prior is None or row["segment_id"] != prior["segment_id"] or opened != prior["close_ts_ms"]:
            day_start = prior_day = None
        hour = datetime.fromtimestamp(opened / 1000, timezone.utc).hour
        target = None
        available = opened
        dependencies = []
        if hour == 5:
            # Snapshot the last COMPLETED close, not this 05:00 candle's open.
            day_start = None if prior is None or opened != prior["close_ts_ms"] or row["segment_id"] != prior["segment_id"] else prior
            if prior_day is not None:
                value, available, dependencies = prior_day
                target = -1 if value > 0 else (1 if value < 0 else 0)
                available = max(opened, available)
        elif hour == 17:
            target = 1
            prior_day = None
            if day_start is not None and prior is not None:
                value = prior["close"] / day_start["close"] - 1.0
                prior_day = (value, max(prior["available_ts_ms"], day_start["available_ts_ms"]),
                             [day_start["close_ts_ms"], prior["close_ts_ms"]])
            day_start = None
        if target is not None:
            output.append({"boundary_ts_ms": opened, "available_ts_ms": available,
                           "expires_ts_ms": opened + 12 * HOUR, "desired_units": target,
                           "segment_id": row["segment_id"], "dependency_close_ts_ms": dependencies})
        prior = row
    return output


def funding_for_signed_exposure(exposure: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                                *, end_ms: int, closed: bool) -> tuple[float, int]:
    """Signed funding debit in entry-normalized bps, fixed one unit held.

    Strict interior preserves credits. A real entry/exit at the same settlement
    timestamp has uncertain ownership, so only adverse positive debit is taken.
    Same-side session boundaries are NOT entry/exit boundaries. END is excluded.
    The supplied archive loader/receipt must separately certify full coverage.
    """
    if not isinstance(exposure, Mapping):
        raise DraftError("EXPOSURE_MAPPING_REQUIRED")
    try:
        entry = exposure["entry_ts_ms"]
        exit_ = exposure["exit_ts_ms"] if closed else end_ms
        direction = exposure["signed_units"]
    except KeyError:
        raise DraftError("EXPOSURE_FIELDS_REQUIRED") from None
    if type(direction) is not int or direction not in (-1, 1):
        raise DraftError("SIGNED_UNIT_REQUIRED")
    if any(type(t) is not int for t in (entry, exit_, end_ms)) or not entry < exit_ or not entry < end_ms:
        raise DraftError("EXPOSURE_CLOCK_INVALID")
    basis = _finite(exposure["entry_price"], positive=True)
    total = 0.0
    count = 0
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DraftError("FUNDING_MAPPING_REQUIRED")
        stamp = row.get("fundingTime")
        if type(stamp) is not int or stamp in seen:
            raise DraftError("FUNDING_CLOCK_DUPLICATE_OR_INVALID")
        seen.add(stamp)
        rate = _finite(row.get("fundingRate"))
        mark = _finite(row.get("markPrice"), positive=True)
        if row.get("symbol", "ETH-USDT") != "ETH-USDT":
            raise DraftError("FUNDING_SYMBOL")
        if entry <= stamp <= exit_ and stamp < end_ms:
            debit = direction * rate * mark / basis * 10_000
            boundary = stamp == entry or (closed and stamp == exit_)
            if not boundary or debit > 0:
                total += debit
                count += 1
    return total, count


def replay_eth_sessions(rows: Sequence[Mapping[str, Any]], funding_rows: Sequence[Mapping[str, Any]],
                        *, start_ms: int, end_ms: int, roundtrip_cost_bps: float) -> dict[str, Any]:
    """Pure replay draft for artificial inputs; no campaign integration.

    Earliest observed hourly open >= max(boundary, dependency availability).
    No wait for CURRENT 05/17 candle close, no expired target fill, no END fill.
    Same-side boundaries maintain fixed quantity/entry identity and zero cost.
    An occupied gap quarantines the exact position/pending state and stops fills.
    """
    if any(type(t) is not int or t % HOUR for t in (start_ms, end_ms)) or start_ms >= end_ms:
        raise DraftError("FIXED_WINDOW_REQUIRED")
    one_way = _finite(roundtrip_cost_bps, positive=True) / 2
    records = _records(rows)
    # The native market loader proves this too; keep the draft independently
    # unable to accrue funding over a missing terminal price-source interval.
    if not any(r["open_ts_ms"] == start_ms for r in records) or not any(r["close_ts_ms"] == end_ms for r in records):
        raise DraftError("FIXED_START_END_SOURCE_COVERAGE_REQUIRED")
    targets = {x["boundary_ts_ms"]: x for x in eth_session_targets(records)}
    trades, orders, noops, missed = [], [], [], []
    position = pending = prior = quarantine = None
    for bar in records:
        stamp = bar["open_ts_ms"]
        if stamp >= end_ms:
            break
        gap = prior is not None and (stamp != prior["close_ts_ms"] or bar["segment_id"] != prior["segment_id"])
        if gap and (position is not None or pending is not None):
            quarantine = {"gap_ts_ms": stamp, "position": position, "pending": pending}
            break
        prior = bar
        if stamp < start_ms:
            continue
        if pending is not None and stamp >= pending["expires_ts_ms"]:
            missed.append({**pending, "reason": "SESSION_TARGET_EXPIRED_UNFILLED"})
            pending = None
        if stamp in targets:
            pending = targets[stamp].copy()
        if pending is None or stamp < pending["available_ts_ms"]:
            continue
        if stamp >= pending["expires_ts_ms"]:
            missed.append({**pending, "reason": "SESSION_TARGET_EXPIRED_UNFILLED"})
            pending = None
            continue
        desired = pending["desired_units"]
        current = position["signed_units"] if position is not None else 0
        quantity, transition_cost = unit_transition(current, desired, roundtrip_cost_bps)
        if quantity == 0:
            noops.append({**pending, "observed_open_ts_ms": stamp, "quantity": 0, "cost_bps": 0.0})
            pending = None
            continue
        orders.append({**pending, "execution_ts_ms": stamp, "execution_price": bar["open"],
                       "current_units": current, "desired_units": desired,
                       "quantity": quantity, "cost_bps": transition_cost})
        if position is not None:
            gross = current * (bar["open"] / position["entry_price"] - 1) * 10_000
            trade = {**position, "exit_ts_ms": stamp, "exit_price": bar["open"],
                     "exit_reason": "SESSION_SIGNED_UNIT_TRANSITION", "gross_bps": gross,
                     "cost_bps": 2 * one_way}
            funding, count = funding_for_signed_exposure(trade, funding_rows, end_ms=end_ms, closed=True)
            trade.update(funding_bps=funding, funding_settlements=count,
                         net_bps=gross - trade["cost_bps"] - funding)
            trades.append(trade)
            position = None
        if desired:
            position = {"symbol": "ETH-USDT", "side": "LONG" if desired > 0 else "SHORT",
                        "signed_units": desired, "entry_ts_ms": stamp, "entry_price": bar["open"],
                        "signal_boundary_ts_ms": pending["boundary_ts_ms"],
                        "signal_available_ts_ms": pending["available_ts_ms"], "entry_cost_bps": one_way}
        pending = None
    if pending is not None and quarantine is None and end_ms >= pending["expires_ts_ms"]:
        missed.append({**pending, "reason": "SESSION_TARGET_EXPIRED_UNFILLED"})
        pending = None
    if position is not None and quarantine is None:
        funding, count = funding_for_signed_exposure(position, funding_rows, end_ms=end_ms, closed=False)
        position = {**position, "funding_bps_to_end_exclusive": funding, "funding_settlements": count}
    paid_cost = sum(x["cost_bps"] for x in orders)
    closed_cost = sum(x["cost_bps"] for x in trades)
    open_cost = position["entry_cost_bps"] if position is not None else 0.0
    if not math.isclose(paid_cost, closed_cost + open_cost, abs_tol=1e-9):
        raise DraftError("TURNOVER_LEG_COST_RECONCILIATION")
    return {"classification": "INTERNAL_TRANSLATION_FIXED_UNIT_NOT_SOURCE_NAV_REPLICATION",
            "trades": trades, "orders": orders, "same_side_boundaries": noops, "expired_targets": missed,
            "open_position": position, "pending_target": pending, "gap_quarantine": quarantine,
            "turnover_units": sum(x["quantity"] for x in orders), "paid_trading_cost_bps": paid_cost,
            "closed_trading_cost_bps": closed_cost, "open_entry_cost_bps": open_cost,
            "unresolved_end": int(position is not None or pending is not None or quarantine is not None),
            "disposition": "BLOCKED_SOURCE_GAP" if quarantine else
                           ("BLOCKED_TERMINAL_UNRESOLVED" if position is not None or pending is not None else "DRAFT_ONLY_NO_VERDICT"),
            "account_nav": None, "funding_coverage_certified_by_helper": False}
