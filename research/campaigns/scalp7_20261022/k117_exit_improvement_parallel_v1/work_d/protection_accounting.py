"""Exact protection-price algebra only; no candidate, stop setter or fill model.

All bps refer to the ORIGINAL entry notional, including realized partial PnL.
This module cannot establish tradability, intrabar ordering or future funding.
"""
from decimal import Decimal, InvalidOperation, localcontext

UNIT = "initial_entry_notional_trade_bps"


def decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("INVALID_NUMBER:" + field)
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("INVALID_NUMBER:" + field) from exc
    if not result.is_finite():
        raise ValueError("NONFINITE:" + field)
    return result


def _state(entry_price, side, remaining_fraction, realized_gross_bps,
           frozen_reference_cost_bps, extra_carry_bps, unit):
    if unit != UNIT:
        raise ValueError("INITIAL_ENTRY_NOTIONAL_BPS_REQUIRED")
    if isinstance(side, bool) or side not in (-1, 1):
        raise ValueError("INVALID_SIDE")
    entry, remaining, realized, reference, extra = [decimal(v, name) for v, name in (
        (entry_price, "entry_price"), (remaining_fraction, "remaining_fraction"),
        (realized_gross_bps, "realized_gross_bps"),
        (frozen_reference_cost_bps, "frozen_reference_cost_bps"), (extra_carry_bps, "extra_carry_bps"))]
    if entry <= 0 or not 0 <= remaining <= 1 or reference < 0 or extra < 0:
        raise ValueError("INVALID_PRICE_FRACTION_OR_COST")
    return entry, side, remaining, realized, reference, extra


def protection_at_price(*, entry_price, side, stop_price, remaining_fraction,
                        realized_gross_bps, frozen_reference_cost_bps, extra_carry_bps,
                        unit):
    """Evaluate an already supplied price; no execution or policy recommendation."""
    e, s, r, realized, reference, extra = _state(entry_price, side, remaining_fraction,
        realized_gross_bps, frozen_reference_cost_bps, extra_carry_bps, unit)
    stop = decimal(stop_price, "stop_price")
    if stop <= 0:
        raise ValueError("NONPOSITIVE_PRICE")
    with localcontext() as context:
        context.prec = 80
        terminal = r * s * (stop / e - 1) * 10000
        gross = realized + terminal
        return {"unit": UNIT, "realized_gross_bps": str(realized),
                "remaining_terminal_gross_bps": str(terminal), "total_gross_bps": str(gross),
                "frozen_reference_cost_bps": str(reference), "extra_carry_bps": str(extra),
                "net1x_bps": str(gross - reference - extra),
                "not_a_fill_or_guaranteed_floor": True, "candidate": False}


def inverse_floor_price(*, entry_price, side, target_net_bps, remaining_fraction,
                        realized_gross_bps, frozen_reference_cost_bps, extra_carry_bps,
                        unit):
    """Algebraic inverse, not a stop update. Caller supplies an existing target.

    Gap fills, availability, next-bar activation and monotonic stop constraints
    must be established elsewhere. No execution interface accepts cost2x here.
    """
    e, s, r, realized, reference, extra = _state(entry_price, side, remaining_fraction,
        realized_gross_bps, frozen_reference_cost_bps, extra_carry_bps, unit)
    target = decimal(target_net_bps, "target_net_bps")
    if r <= 0:
        raise ValueError("NO_REMAINING_POSITION")
    with localcontext() as context:
        context.prec = 80
        price = e * (1 + s * (target + reference + extra - realized) / (r * 10000))
        if price <= 0:
            raise ValueError("NONPOSITIVE_INVERSE_PRICE")
        return {"price": str(price), "unit": "quote_per_base_asset",
                "formula_only": True, "stop_update": None, "candidate": False,
                "execution_feasibility": "NOT_ESTABLISHED"}


def stress_after_outcome(gross_bps, reference_cost_bps, extra_carry_bps, *, multiplier):
    """Posthoc stress only; the multiplier is never an execution-stop input."""
    gross = decimal(gross_bps, "gross_bps")
    ref = decimal(reference_cost_bps, "reference_cost_bps")
    extra = decimal(extra_carry_bps, "extra_carry_bps")
    m = decimal(multiplier, "multiplier")
    if ref < 0 or extra < 0 or m < 0:
        raise ValueError("NEGATIVE_COST_OR_STRESS")
    with localcontext() as context:
        context.prec = 80
        return {"net_bps": str(gross - m * (ref + extra)),
                "classification": "POSTHOC_STRESS_NOT_EXECUTION_INPUT", "multiplier": str(m)}


def quote_amount(*, trade_bps, initial_quantity, quantity_unit, base_units_per_contract,
                 entry_price, quote_currency):
    """Map original-notional bps to money only when actual quantity is supplied."""
    quantity = decimal(initial_quantity, "initial_quantity")
    multiplier = decimal(base_units_per_contract, "base_units_per_contract")
    entry = decimal(entry_price, "entry_price")
    bps = decimal(trade_bps, "trade_bps")
    if quantity_unit not in ("BASE_ASSET", "CONTRACTS"):
        raise ValueError("EXPLICIT_QUANTITY_UNIT_REQUIRED")
    if quantity <= 0 or multiplier <= 0 or entry <= 0:
        raise ValueError("NONPOSITIVE_QUANTITY_PRICE_MULTIPLIER")
    if quantity_unit == "BASE_ASSET" and multiplier != 1:
        raise ValueError("BASE_ASSET_MULTIPLIER_MUST_BE_ONE")
    if not isinstance(quote_currency, str) or not quote_currency:
        raise ValueError("QUOTE_CURRENCY_REQUIRED")
    with localcontext() as context:
        context.prec = 80
        notional = quantity * multiplier * entry
        return {"initial_notional_quote": str(notional), "amount_quote": str(notional * bps / 10000),
                "quote_currency": quote_currency, "account_NAV_claim": False}
