"""Explicit product/evidence boundaries around preserved Exact25 components.

These adapters authenticate supplied bytes and enforce declared semantics; they
do not certify a provider's historical metadata or execute a market strategy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from backend.research.rebuild.scalp7_exact25_capital_v1 import value_spot_fill_ledger
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    RECEIPT_ONLY,
    DetailExecutionAdapter,
)
from backend.research.rebuild.scalp7_exact25_session_v1 import turtle_filled_units

SCHEMA = "g4.exact25.product_contracts.v1"
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def _stamp(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("INVALID_TIMESTAMP:" + name)
    return value


def _positive(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        out = Decimal(str(value))
    except Exception as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not out.is_finite() or out <= 0:
        raise ValueError("INVALID_NUMBER:" + name)
    return out


def bind_price_grid(
    receipt_bytes: bytes,
    *,
    expected_sha256: str,
    symbol: str,
    venue: str,
    product: str,
    at_ts_ms: int,
    evidence_class: str,
) -> dict[str, Any]:
    """Anti/Soup ticks mean a price increment, not prints or trade tape.

    A current contract cannot silently supply an old point-in-time grid. A
    synthetic receipt remains synthetic even when its bytes match its digest.
    """
    stamp = _stamp(at_ts_ms, "at_ts_ms")
    if hashlib.sha256(receipt_bytes).hexdigest() != expected_sha256:
        raise ValueError("PRICE_GRID_RECEIPT_HASH_MISMATCH")
    if evidence_class not in {"OBSERVED_METADATA", "SYNTHETIC_FIXTURE"}:
        raise ValueError("EXPLICIT_METADATA_EVIDENCE_CLASS_REQUIRED")
    row = json.loads(receipt_bytes)
    if not isinstance(row, dict) or row.get("kind") != "PRICE_GRID":
        raise ValueError("PRICE_GRID_NOT_TRADE_TAPE_REQUIRED")
    if (
        not symbol
        or not venue
        or not product
        or (row.get("symbol"), row.get("venue"), row.get("product"))
        != (symbol, venue, product)
    ):
        raise ValueError("PRICE_GRID_PRODUCT_BINDING_MISMATCH")
    if row.get("evidence_class") != evidence_class:
        raise ValueError("PRICE_GRID_EVIDENCE_CLASS_MISMATCH")
    start = _stamp(row.get("valid_from_ms"), "valid_from_ms")
    end = _stamp(row.get("valid_to_ms"), "valid_to_ms")
    known = _stamp(row.get("available_ts_ms"), "available_ts_ms")
    if not start <= stamp < end or known > stamp:
        raise ValueError("HISTORICAL_PRICE_GRID_NOT_AVAILABLE_OR_VALID")
    if not isinstance(row.get("source_ref"), str) or not row["source_ref"].strip():
        raise ValueError("PRICE_GRID_SOURCE_REQUIRED")
    tick = _positive(row.get("price_increment"), "price_increment")
    return {
        "schema": SCHEMA,
        "kind": "PRICE_GRID",
        "tick_size": str(tick),
        "symbol": symbol,
        "venue": venue,
        "product": product,
        "available_ts_ms": known,
        "valid_from_ms": start,
        "valid_to_ms": end,
        "source_ref": row["source_ref"],
        "source_receipt_sha256": expected_sha256,
        "evidence_class": evidence_class,
        "provider_authenticity_independently_verified": False,
        "trade_tape_available": False,
        "economic_credit": False,
        "authority": dict(AUTHORITY),
    }


def fvg_receipt_adapter(
    order: Mapping[str, Any], *, fee_rate: Any
) -> DetailExecutionAdapter:
    """Resting FVG limits require explicit execution receipts; touch is no fill."""
    if order.get("order_kind") != "LIMIT":
        raise ValueError("FVG_RESTING_LIMIT_REQUIRED")
    if order.get("timing_basis") != "OBSERVED_ORDER":
        raise ValueError("FVG_OBSERVED_ORDER_BINDING_REQUIRED")
    return DetailExecutionAdapter(order, fill_model=RECEIPT_ONLY, fee_rate=fee_rate)


def turtle_daily_filled_units(
    fills: list[dict[str, Any]],
    *,
    n: Any,
    side: int,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve DAILY N/channel references and actual filled-unit state.

    This closes the input boundary, not a pyramiding or portfolio order caller.
    System1's virtual-winner ledger remains a separate unresolved requirement.
    """
    if reference.get("source_unit") != "TRADING_DAY":
        raise ValueError("TURTLE_NATIVE_DAILY_REQUIRED")
    if reference.get("system") != "SYSTEM2_55_20":
        raise ValueError("TURTLE_SYSTEM1_VIRTUAL_WINNER_LEDGER_REQUIRED")
    known = _stamp(reference.get("available_ts_ms"), "reference_available_ts_ms")
    if (
        not reference.get("source_ref")
        or reference.get("entry_days") != 55
        or (reference.get("exit_days") != 20)
    ):
        raise ValueError("TURTLE_DAILY_CHANNEL_CONTRACT_REQUIRED")
    if not fills or known > _stamp(fills[0].get("fill_ts_ms"), "first_fill_ts_ms"):
        raise ValueError("TURTLE_DAILY_REFERENCE_NOT_CAUSAL")
    evidence = set()
    last_known = -1
    for fill in fills:
        stamp = _stamp(fill.get("fill_ts_ms"), "fill_ts_ms")
        available = _stamp(fill.get("available_ts_ms"), "fill_available_ts_ms")
        if available < max(stamp, last_known) or not fill.get("source_ref"):
            raise ValueError("TURTLE_FILL_SOURCE_OR_AVAILABILITY_REQUIRED")
        basis = fill.get("execution_evidence")
        if basis not in {"OBSERVED_FILL", "DECLARED_MODEL_FILL"}:
            raise ValueError("TURTLE_EXPLICIT_FILL_EVIDENCE_REQUIRED")
        evidence.add(basis)
        if len(evidence) > 1:
            raise ValueError("TURTLE_MIXED_FILL_EVIDENCE")
        last_known = available
    parsed_n = _positive(n, "N")
    if parsed_n != _positive(reference.get("N"), "reference_N"):
        raise ValueError("TURTLE_N_REFERENCE_MISMATCH")
    if isinstance(side, bool):
        raise ValueError("INVALID_SIDE")
    state = turtle_filled_units(fills, float(parsed_n), side)
    return {
        **state,
        "schema": SCHEMA,
        "reference_source_ref": reference["source_ref"],
        "native_timeframe": "DAILY",
        "execution_evidence": sorted(evidence),
        "state_available_ts_ms": last_known,
        "provider_authenticity_independently_verified": False,
        "full_strategy_caller_complete": False,
        "economic_credit": False,
        "authority": dict(AUTHORITY),
    }


def value_native_spot_ledger(
    fills: list[dict[str, Any]],
    *,
    product_contract: Mapping[str, Any],
    symbol: str,
    initial_cash_usdt: Any,
    initial_qty_base: Any,
    initial_avg_entry: Any,
    final_price: dict[str, Any],
) -> dict[str, Any]:
    """A perpetual price/position cannot replace finite native spot inventory."""
    if product_contract.get("market_type") != "SPOT" or (
        product_contract.get("symbol") != symbol
    ):
        raise ValueError("NATIVE_SPOT_PRODUCT_REQUIRED")
    if product_contract.get("quote_currency") != "USDT" or (
        product_contract.get("external_cash_flows") != "NONE"
    ):
        raise ValueError("SPOT_QUOTE_OR_EXTERNAL_FLOW_UNSUPPORTED")
    if not product_contract.get("source_ref"):
        raise ValueError("SPOT_PRODUCT_SOURCE_REQUIRED")
    venue, product = product_contract.get("venue"), product_contract.get("product")
    if not isinstance(venue, str) or not venue or product != "SPOT":
        raise ValueError("SPOT_VENUE_AND_PRODUCT_REQUIRED")
    for row in [*fills, final_price]:
        if (row.get("venue"), row.get("product"), row.get("market_type")) != (
            venue,
            product,
            "SPOT",
        ):
            raise ValueError("SPOT_FILL_OR_PRICE_PRODUCT_MISMATCH")
    known = _stamp(product_contract.get("available_ts_ms"), "product_available_ts_ms")
    if any(_stamp(fill.get("fill_ts_ms"), "fill_ts_ms") < known for fill in fills):
        raise ValueError("SPOT_PRODUCT_NOT_CAUSALLY_AVAILABLE")
    if final_price.get("market_type") != "SPOT":
        raise ValueError("PERPETUAL_PRICE_CANNOT_VALUE_NATIVE_SPOT")
    if known > _stamp(final_price.get("available_ts_ms"), "valuation_available_ts_ms"):
        raise ValueError("SPOT_PRODUCT_NOT_AVAILABLE_AT_VALUATION")
    result = value_spot_fill_ledger(
        fills,
        initial_cash_usdt=initial_cash_usdt,
        initial_qty_base=initial_qty_base,
        initial_avg_entry=initial_avg_entry,
        symbol=symbol,
        final_price=final_price,
    )
    return {
        **result,
        "schema": SCHEMA,
        "market_type": "SPOT",
        "product_source_ref": product_contract["source_ref"],
        "DGT_order_reset_caller_complete": False,
    }
