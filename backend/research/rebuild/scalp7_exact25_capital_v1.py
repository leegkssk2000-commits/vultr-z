"""Original-25 capital components; no composite or DGT strategy certification."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from backend.research.rebuild.scalp7_implementation_contract_v1 import validate_rules

IDS = ("alpha_combo", "grid_rebalance")
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def _number(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        out = Decimal(str(value))
    except Exception as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not out.is_finite() or (positive and out <= 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return out


def _float(value: Decimal) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("OUTPUT_NOT_FINITE")
    return out


def _stamp(value: Any) -> int:
    out = _number(value, "timestamp")
    if out < 0 or out != out.to_integral_value():
        raise ValueError("INVALID_TIMESTAMP")
    return int(out)


def catalog() -> dict[str, dict[str, Any]]:
    return {
        "alpha_combo": {
            "mode_id": "FIXED_COMPONENT_ALLOCATION_ACCOUNTING_V1",
            "classification": "DECLARED_CAPITAL_COMPONENT_NOT_SOURCE_STRATEGY",
            "source_ids": ["S310", "S311", "R06"],
            "complete_strategy": False,
            "gaps": [
                "component economic validation",
                "approved composition policy",
                "caller-supplied weight freeze and source bytes not independently verified",
            ],
        },
        "grid_rebalance": {
            "mode_id": "FINITE_SPOT_FILL_INVENTORY_ACCOUNTING_V1",
            "classification": "SPOT_ACCOUNTING_COMPONENT_NOT_DGT_REPRODUCTION",
            "source_ids": ["R21", "V2_DGT_RUNNER", "V2_DGT_LOGIC"],
            "complete_strategy": False,
            "gaps": [
                "native DGT caller mismatch",
                "grid reset/fill path",
                "spot/perp incompatibility",
            ],
        },
    }


def rules(strategy_id: str) -> list[dict[str, Any]]:
    if strategy_id not in IDS:
        raise ValueError("UNKNOWN_EXACT25_CAPITAL_ID")
    expression = (
        "Fixed ex-ante weights apply only to currently valid component signals; unused risk stays cash."
        if strategy_id == "alpha_combo"
        else "Buy deducts qty*actual_fill+fee from finite cash; sell cannot exceed actual spot inventory."
    )
    return [
        {
            "rule_id": strategy_id + ".capital.v1",
            "origin": "DECLARED_HYPOTHESIS",
            "expression": expression,
            "unit": "fraction of explicitly supplied risk budget / actual base qty / USDT",
            "version": "1",
            "hypothesis_id": strategy_id + ".ACCOUNTING_COMPONENT_ONLY_V1",
            "rationale": "Executable accounting invariants; source review does not determine a profitable complete strategy.",
            "exact_source_reproduction": False,
        }
    ]


def allocate_existing_signals(
    signals: list[dict[str, Any]],
    *,
    weights: dict[str, Any],
    decision_ts_ms: int,
    available_risk_fraction: Any,
) -> dict[str, Any]:
    """Apply frozen component weights without choosing winners or inventing signals."""
    decision = _stamp(decision_ts_ms)
    budget = _number(available_risk_fraction, "available_risk_fraction")
    if not 0 <= budget <= 1 or not weights:
        raise ValueError("EXPLICIT_FINITE_RISK_BUDGET_REQUIRED")
    parsed = {key: _number(value, "weight") for key, value in weights.items()}
    if (
        any(not key or value < 0 for key, value in parsed.items())
        or sum(parsed.values()) > 1
    ):
        raise ValueError("WEIGHTS_NOT_FIXED_UNIT_BUDGET")
    allocations, seen, used = [], set(), Decimal(0)
    for signal in signals:
        key = signal.get("component_id")
        if key not in parsed or key in seen:
            raise ValueError("DUPLICATE_OR_UNBOUND_COMPONENT")
        seen.add(key)
        for field in ("signal_id", "symbol", "producer_code_sha256", "rule_digest"):
            if not isinstance(signal.get(field), str) or not signal[field]:
                raise ValueError("COMPONENT_PROVENANCE_REQUIRED:" + field)
        if any(
            field in signal
            for field in ("future_pnl", "winner_rank", "realized_future_return")
        ):
            raise ValueError("OUTCOME_BASED_ALLOCATION_FORBIDDEN")
        available = _stamp(signal.get("available_ts_ms"))
        expires = _stamp(signal.get("valid_until_ts_ms"))
        if expires <= available:
            raise ValueError("INVALID_SIGNAL_VALIDITY_INTERVAL")
        if available > decision or expires <= decision:
            continue
        fraction = budget * parsed[key]
        if not fraction:
            continue
        used += fraction
        allocations.append(
            {
                "component_id": key,
                "signal_id": signal["signal_id"],
                "symbol": signal["symbol"],
                "decision_ts_ms": decision,
                "signal_available_ts_ms": available,
                "signal_valid_until_ts_ms": expires,
                "risk_fraction": _float(fraction),
                "producer_code_sha256": signal["producer_code_sha256"],
                "rule_digest": signal["rule_digest"],
            }
        )
    return {
        "allocations": allocations,
        "cash_risk_fraction": _float(budget - used),
        "fixed_weights": {key: _float(value) for key, value in parsed.items()},
        "forced_replacement": False,
        "economic_credit": False,
        "composition_authorized": False,
        "weight_freeze_status": "CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED",
        "signal_provenance_status": "IDENTIFIERS_PRESENT_SOURCE_BYTES_NOT_CHECKED",
        "authority": dict(AUTHORITY),
    }


def value_spot_fill_ledger(
    fills: list[dict[str, Any]],
    *,
    initial_cash_usdt: Any,
    initial_qty_base: Any,
    initial_avg_entry: Any,
    symbol: str,
    final_price: dict[str, Any],
) -> dict[str, Any]:
    """Consume explicit fill receipts; OHLC touches cannot create spot fills."""
    cash = _number(initial_cash_usdt, "initial_cash", positive=True)
    qty = _number(initial_qty_base, "initial_qty")
    avg = _number(initial_avg_entry, "initial_avg")
    if qty < 0 or (qty > 0 and avg <= 0) or (qty == 0 and avg != 0):
        raise ValueError("INITIAL_INVENTORY_COST_REQUIRED")
    initial_cost = cash + qty * avg
    seen: set[str] = set()
    last_ts, max_known, fees, realized = -1, -1, Decimal(0), Decimal(0)
    rows = []
    evidence: set[str] = set()
    for fill in fills:
        fill_id = fill.get("fill_id")
        if not isinstance(fill_id, str) or not fill_id or fill_id in seen:
            raise ValueError("DUPLICATE_OR_MISSING_FILL_ID")
        seen.add(fill_id)
        stamp = _stamp(fill.get("fill_ts_ms"))
        known = _stamp(fill.get("available_ts_ms"))
        if stamp < last_ts or known < stamp or fill.get("symbol") != symbol:
            raise ValueError("FILL_CLOCK_OR_SYMBOL_INVALID")
        basis = fill.get("execution_evidence")
        if basis not in {"OBSERVED_FILL", "DECLARED_MODEL_FILL"} or not fill.get(
            "source_ref"
        ):
            raise ValueError("EXPLICIT_FILL_RECEIPT_REQUIRED")
        evidence.add(basis)
        if len(evidence) > 1:
            raise ValueError("MIXED_MODEL_AND_OBSERVED_LEDGER")
        if "leverage" in fill or fill.get("fee_currency") != "USDT":
            raise ValueError("SPOT_ACCOUNTING_UNIT_MISMATCH")
        size = _number(fill.get("qty_base"), "qty_base", positive=True)
        price = _number(fill.get("price"), "price", positive=True)
        fee = _number(fill.get("fee_usdt"), "fee")
        if fee < 0:
            raise ValueError("NEGATIVE_FEE_UNSUPPORTED")
        if fill.get("side") == "BUY":
            required = size * price + fee
            if required > cash:
                raise ValueError("INSUFFICIENT_FINITE_CASH")
            avg = (qty * avg + size * price) / (qty + size)
            qty += size
            cash -= required
        elif fill.get("side") == "SELL":
            if size > qty:
                raise ValueError("SPOT_INVENTORY_EXCEEDED")
            proceeds_after_fee = cash + size * price - fee
            if proceeds_after_fee < 0:
                raise ValueError("INSUFFICIENT_FINITE_CASH_FOR_SELL_FEE")
            realized += size * (price - avg)
            cash = proceeds_after_fee
            qty -= size
            if not qty:
                avg = Decimal(0)
        else:
            raise ValueError("INVALID_SPOT_FILL_SIDE")
        fees += fee
        last_ts = stamp
        max_known = max(max_known, known)
        rows.append(
            {
                "fill_id": fill_id,
                "ts_ms": stamp,
                "available_ts_ms": known,
                "source_ref": fill["source_ref"],
                "execution_evidence": basis,
                "cash_usdt": _float(cash),
                "qty_base": _float(qty),
                "avg_entry_price": _float(avg),
            }
        )
    mark_ts = _stamp(final_price.get("ts_ms"))
    valuation_available = _stamp(final_price.get("available_ts_ms"))
    if valuation_available < max(mark_ts, max_known):
        raise ValueError("VALUATION_BEFORE_ALL_INPUTS_AVAILABLE")
    if mark_ts < last_ts or final_price.get("symbol") != symbol:
        raise ValueError("FINAL_SPOT_PRICE_CLOCK_OR_SYMBOL")
    if final_price.get("price_basis") != "LAST_PRICE" or not final_price.get(
        "source_ref"
    ):
        raise ValueError("EXPLICIT_SPOT_LAST_PRICE_REQUIRED")
    price = _number(final_price.get("price"), "price", positive=True)
    unrealized = qty * (price - avg)
    equity = cash + qty * price
    if equity - initial_cost != realized + unrealized - fees:
        if abs((equity - initial_cost) - (realized + unrealized - fees)) > Decimal(
            "1e-20"
        ):
            raise ValueError("SPOT_LEDGER_RECONCILIATION_FAILURE")
    return {
        "cash_usdt": _float(cash),
        "remaining_qty_base": _float(qty),
        "avg_entry_price": _float(avg),
        "realized_gross_usdt": _float(realized),
        "unrealized_usdt": _float(unrealized),
        "fees_usdt": _float(fees),
        "equity_usdt": _float(equity),
        "net_usdt": _float(equity - initial_cost),
        "net_basis": "INITIAL_INVENTORY_AVERAGE_COST_NOT_INITIAL_MARK_NAV",
        "valuation_available_ts_ms": valuation_available,
        "valuation_price_ts_ms": mark_ts,
        "valuation_source_ref": final_price["source_ref"],
        "fill_count": len(fills),
        "trade_episode_T": None,
        "state_trace": rows,
        "price_basis": "LAST_PRICE",
        "execution_evidence": sorted(evidence),
        "full_DGT_reproduction": False,
        "source_strategy_economic_credit": False,
        "external_flow_policy": "UNSUPPORTED",
        "authority": dict(AUTHORITY),
    }


def evaluate(
    strategy_id: str, frames: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    """Capital roles consume bound signals or actual fill ledgers, not OHLC fill guesses."""
    if config.get("timeframe_min") not in (15, 30):
        raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    if strategy_id not in IDS:
        raise ValueError("UNKNOWN_EXACT25_CAPITAL_ID")
    del frames
    definition = catalog()[strategy_id]
    rule_rows = rules(strategy_id)
    digest = validate_rules(rule_rows)
    if strategy_id == "alpha_combo":
        component = allocate_existing_signals(
            config["component_signals"],
            weights=config["weights"],
            decision_ts_ms=config["decision_ts_ms"],
            available_risk_fraction=config["available_risk_fraction"],
        )
    else:
        component = value_spot_fill_ledger(
            config["fill_receipts"],
            initial_cash_usdt=config["initial_cash_usdt"],
            initial_qty_base=config["initial_qty_base"],
            initial_avg_entry=config["initial_avg_entry"],
            symbol=config["symbol"],
            final_price=config["final_price"],
        )
    component["component_digest"] = hashlib.sha256(
        json.dumps(component, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return {
        "strategy_id": strategy_id,
        "mode_id": definition["mode_id"],
        "events": [],
        "intents": [],
        "components": [component],
        "rules": rule_rows,
        "rule_digest": digest,
        "limitations": definition["gaps"],
        "complete_strategy": False,
        "authority": dict(AUTHORITY),
    }
