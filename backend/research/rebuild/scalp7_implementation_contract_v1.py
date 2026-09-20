"""Additive research preflight helpers; never submits orders or awards economic credit.

Existing frozen Scalp7 execution/metrics modules are intentionally unchanged.
Entry-bar results are model witnesses, NOT observed fills or complete replays.
Valuation requires synchronized snapshots and no external capital flows.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

SCHEMA = "zel.scalp7.implementation_contract.v1"
RULE_ORIGINS = {"SOURCE_DIRECT", "EXISTING_FROZEN", "DECLARED_HYPOTHESIS"}
PRICE_BASES = {"MARK_PRICE", "LAST_PRICE"}
ENTRY_KINDS = {"NEXT_OPEN", "STOP_MARKET", "LIMIT"}
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return number


def _finite_float(value: Decimal, name: str) -> float:
    """Reject Decimal values that cannot be represented as finite JSON numbers."""
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("NONFINITE_OUTPUT:" + name) from exc
    if not math.isfinite(result):
        raise ValueError("NONFINITE_OUTPUT:" + name)
    return result


def _timestamp(value: Any, name: str) -> int:
    number = _decimal(value, name)
    if number < 0 or number != number.to_integral_value():
        raise ValueError("INVALID_TIMESTAMP:" + name)
    return int(number)


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("MISSING_TEXT:" + key)
    return value


def validate_rules(rules: Sequence[Mapping[str, Any]]) -> str:
    """Validate per-rule provenance, not source truth or strategy profitability."""
    if not rules:
        raise ValueError("RULES_REQUIRED")
    names: set[str] = set()
    for rule in rules:
        key = _required_text(rule, "rule_id")
        if key in names:
            raise ValueError("DUPLICATE_RULE:" + key)
        names.add(key)
        origin = _required_text(rule, "origin")
        if origin not in RULE_ORIGINS:
            raise ValueError("UNKNOWN_RULE_ORIGIN:" + key)
        for field in ("expression", "unit", "version"):
            _required_text(rule, field)
        if origin == "SOURCE_DIRECT":
            for field in ("source_id", "source_locator", "source_mode"):
                _required_text(rule, field)
        elif origin == "EXISTING_FROZEN":
            _required_text(rule, "code_path")
            _required_text(rule, "code_sha")
        else:
            _required_text(rule, "hypothesis_id")
            _required_text(rule, "rationale")
            if rule.get("exact_source_reproduction"):
                raise ValueError("HYPOTHESIS_IS_NOT_EXACT_SOURCE:" + key)
    payload = json.dumps(
        list(rules),
        sort_keys=True,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def inspect_entry_bar(
    order: Mapping[str, Any], bar: Mapping[str, Any]
) -> dict[str, Any]:
    """Classify one execution bar without fabricating intrabar order or queue data.

    Caller must supply a previously authorized order, enforce contiguous data,
    and process successive witnesses; this function is not a strategy runner.
    LIMIT touch never creates a fill. STOP witnesses retain interval precision.
    """
    for key in ("identity", "symbol", "rule_digest", "timing_basis"):
        _required_text(order, key)
    if order["timing_basis"] not in {"HISTORICAL_MODEL", "OBSERVED_ORDER"}:
        raise ValueError("INVALID_TIMING_BASIS")
    tf = _timestamp(order.get("decision_tf_min"), "decision_tf_min")
    if tf not in (15, 30):
        raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    kind = order.get("order_kind")
    if kind not in ENTRY_KINDS:
        raise ValueError("INVALID_ORDER_KIND")
    side = order.get("side")
    if isinstance(side, bool) or side not in (-1, 1):
        raise ValueError("INVALID_SIDE")
    _decimal(order.get("qty_base"), "qty_base", positive=True)
    available = _timestamp(
        order.get("feature_available_ts_ms"), "feature_available_ts_ms"
    )
    submitted = _timestamp(order.get("order_submit_ts_ms"), "order_submit_ts_ms")
    active = _timestamp(order.get("order_active_ts_ms"), "order_active_ts_ms")
    expires = _timestamp(order.get("expires_ts_ms"), "expires_ts_ms")
    if not available <= submitted <= active < expires:
        raise ValueError("ORDER_CLOCK_NOT_CAUSAL")
    if bar.get("symbol") != order["symbol"]:
        raise ValueError("SYMBOL_MISMATCH")
    _required_text(bar, "segment_id")
    opened = _timestamp(bar.get("open_ts_ms"), "open_ts_ms")
    closed = _timestamp(bar.get("close_ts_ms"), "close_ts_ms")
    known = _timestamp(bar.get("available_ts_ms"), "available_ts_ms")
    if not opened < closed <= known or closed - opened >= tf * 60000:
        raise ValueError("DETAIL_BAR_TIME_INVALID")
    o, h, low, c = [
        _decimal(bar.get(k), k, positive=True) for k in ("open", "high", "low", "close")
    ]
    if not low <= min(o, c) <= max(o, c) <= h:
        raise ValueError("OHLC_GEOMETRY_INVALID")
    trigger = (
        None
        if kind == "NEXT_OPEN"
        else _decimal(order.get("trigger_price"), "trigger_price", positive=True)
    )
    stop = _decimal(order.get("protective_stop"), "protective_stop", positive=True)
    if trigger is not None and side * (trigger - stop) <= 0:
        raise ValueError("PLANNED_STOP_INVALID")
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "identity": order["identity"],
        "order_kind": kind,
        "status": "WAIT",
        "fill_ts_ms": None,
        "candidate_price": None,
        "event_interval_ms": None,
        "witness_available_ts_ms": known,
        "economic_credit": False,
        "execution_evidence": "OHLC_MODEL_WITNESS_NOT_OBSERVED_FILL",
        "authority": dict(AUTHORITY),
    }
    if closed <= active:
        return result
    if opened >= expires:
        return {**result, "status": "EXPIRED"}
    if opened < active:
        return {**result, "status": "UNRESOLVED_ACTIVE_INSIDE_BAR"}
    if kind == "NEXT_OPEN":
        if opened != active:
            return {**result, "status": "MISSED_ACTIVATION_OPEN"}
        if side * (o - stop) <= 0:
            return {**result, "status": "ENTRY_INVALIDATES_STOP"}
        return {
            **result,
            "status": "MODEL_OPEN_CANDIDATE",
            "candidate_price": _finite_float(o, "candidate_price"),
            "event_interval_ms": [opened, opened],
        }
    if trigger is None:
        raise ValueError("TRIGGER_REQUIRED_FOR_CONDITIONAL_ORDER")
    if kind == "LIMIT":
        if expires < closed:
            return {**result, "status": "UNRESOLVED_EXPIRY_INSIDE_BAR"}
        touched = low <= trigger if side == 1 else h >= trigger
        return {**result, "status": "LIMIT_TOUCH_UNCONFIRMED" if touched else "WAIT"}
    gap_cross = o >= trigger if side == 1 else o <= trigger
    if gap_cross:
        return {
            **result,
            "status": "MODEL_STOP_OPEN_CANDIDATE",
            "candidate_price": _finite_float(o, "candidate_price"),
            "event_interval_ms": [opened, opened],
        }
    if expires < closed:
        return {**result, "status": "UNRESOLVED_EXPIRY_INSIDE_BAR"}
    crossed = h >= trigger if side == 1 else low <= trigger
    if not crossed:
        return result
    stop_crossed = low <= stop if side == 1 else h >= stop
    if stop_crossed:
        return {
            **result,
            "status": "UNRESOLVED_ENTRY_STOP_ORDER",
            "event_interval_ms": [opened, closed],
        }
    return {
        **result,
        "status": "MODEL_STOP_INTERVAL_CANDIDATE",
        "candidate_price": _finite_float(trigger, "candidate_price"),
        "event_interval_ms": [opened, closed],
    }


def value_account_snapshots(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    initial_cash_usdt: Any,
    start_ts_ms: Any,
    price_basis: str,
) -> dict[str, Any]:
    """Value linear USDT-M residual positions; costs/funding are cumulative.

    qty_base is actual underlying size, including any earlier leverage choice.
    No margin-ROI multiplication. Same-time marks are required. MARK and LAST
    never mix. Missing marks produce no result, rather than a fabricated curve.
    This is sampled account equity, not liquidation simulation or intrabar DD.
    External cash flows require unitization and are deliberately unsupported.
    """
    initial = _decimal(initial_cash_usdt, "initial_cash_usdt", positive=True)
    start = _timestamp(start_ts_ms, "start_ts_ms")
    if price_basis not in PRICE_BASES:
        raise ValueError("UNSUPPORTED_PRICE_BASIS")
    if not snapshots:
        raise ValueError("ACCOUNT_SNAPSHOTS_REQUIRED")
    peak, max_dd = initial, Decimal(0)
    last_ts = start - 1
    last_fee = Decimal(0)
    curve = []
    for snap in snapshots:
        stamp = _timestamp(snap.get("ts_ms"), "ts_ms")
        if stamp < start or stamp <= last_ts:
            raise ValueError("SNAPSHOT_NOT_STRICTLY_CHRONOLOGICAL")
        if _decimal(snap.get("external_flow_usdt", 0), "external_flow_usdt") != 0:
            raise ValueError("EXTERNAL_FLOW_REQUIRES_UNITIZATION")
        realized = _decimal(
            snap.get("realized_gross_cum_usdt"), "realized_gross_cum_usdt"
        )
        fees = _decimal(snap.get("fees_cum_usdt"), "fees_cum_usdt")
        funding = _decimal(
            snap.get("funding_received_cum_usdt"), "funding_received_cum_usdt"
        )
        if fees < last_fee:
            raise ValueError("FEES_NOT_NONNEGATIVE_CUMULATIVE")
        positions = snap.get("positions")
        marks = snap.get("prices")
        if not isinstance(positions, list) or not isinstance(marks, Mapping):
            raise ValueError("ACCOUNT_STATE_REQUIRED")
        unrealized = Decimal(0)
        ids: set[str] = set()
        for position in positions:
            episode = _required_text(position, "position_episode_id")
            if episode in ids:
                raise ValueError("DUPLICATE_POSITION_EPISODE")
            ids.add(episode)
            symbol = _required_text(position, "symbol")
            side = position.get("side")
            if isinstance(side, bool) or side not in (-1, 1):
                raise ValueError("INVALID_SIDE")
            qty = _decimal(
                position.get("remaining_qty_base"), "remaining_qty_base", positive=True
            )
            entry = _decimal(
                position.get("avg_entry_price"), "avg_entry_price", positive=True
            )
            if "leverage" in position:
                raise ValueError("USE_ACTUAL_QTY_NOT_LEVERAGE_MULTIPLIER")
            if symbol not in marks:
                raise ValueError("PRICE_MISSING:" + symbol)
            quote = marks[symbol]
            if quote.get("price_basis") != price_basis:
                raise ValueError("PRICE_BASIS_MISMATCH")
            if _timestamp(quote.get("ts_ms"), "price_ts_ms") != stamp:
                raise ValueError("UNSYNCHRONIZED_PRICES")
            _required_text(quote, "source_ref")
            mark = _decimal(quote.get("price"), "price", positive=True)
            unrealized += side * qty * (mark - entry)
        cash = initial + realized - fees + funding
        equity = cash + unrealized
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)
        curve.append(
            {
                "ts_ms": stamp,
                "cash_usdt": _finite_float(cash, "cash_usdt"),
                "unrealized_usdt": _finite_float(unrealized, "unrealized_usdt"),
                "equity_usdt": _finite_float(equity, "equity_usdt"),
                "peak_equity_usdt": _finite_float(peak, "peak_equity_usdt"),
                "drawdown_pct": _finite_float(dd * 100, "drawdown_pct"),
            }
        )
        last_ts, last_fee = stamp, fees
    return {
        "schema": SCHEMA,
        "price_basis": price_basis,
        "initial_cash_usdt": _finite_float(initial, "initial_cash_usdt"),
        "curve": curve,
        "max_drawdown_pct": _finite_float(max_dd * 100, "max_drawdown_pct"),
        "sampling": "SYNCHRONIZED_SNAPSHOTS_NOT_INTRABAR_MAXIMUM",
        "external_flow_policy": "NO_EXTERNAL_FLOW_SUPPORTED",
        "liquidation_simulated": False,
        "authority": dict(AUTHORITY),
    }
