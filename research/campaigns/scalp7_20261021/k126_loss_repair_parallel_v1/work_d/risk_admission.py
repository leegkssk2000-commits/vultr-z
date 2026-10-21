"""Offline common-budget admission calculation; disabled by default, no execution.

Caller supplies an authoritative exposure snapshot INCLUDING pending reservations.
The returned allocations must be atomically accepted/reconciled by the economic
owner; calling this pure function neither reserves funds nor submits an order.
No K126 risk limit, quantity, cooldown, loss threshold or account NAV is inferred.
All amounts use one bound quote currency. BASE_ASSET and linear CONTRACTS are
supported explicitly; inverse contracts and trade-bps-as-money are unsupported.
The cost reserve must be known at the decision time. A final saved trade's cost,
including future holding/carry charges, is not an admissible reserve input.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
import hashlib
import json
import re

SCHEMA = "zel.work_d.k126.admission.v1"
ZERO = Decimal("0")
ONE = Decimal("1")


class InputError(ValueError):
    """Missing, unbound, unavailable or dimensionally incompatible input."""


def _need(obj, name, path):
    if not isinstance(obj, dict) or name not in obj or obj[name] is None:
        raise InputError(path + "." + name + ":REQUIRED_INPUT")
    return obj[name]


def _text(obj, name, path):
    value = _need(obj, name, path)
    if not isinstance(value, str) or not value.strip():
        raise InputError(path + "." + name + ":NONEMPTY_STRING_REQUIRED")
    return value


def _integer(value, path):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputError(path + ":NONNEGATIVE_INTEGER_REQUIRED")
    return value


def _number(value, path, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise InputError(path + ":FINITE_DECIMAL_REQUIRED")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise InputError(path + ":FINITE_DECIMAL_REQUIRED") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise InputError(path + ":NONNEGATIVE_FINITE_DECIMAL_REQUIRED")
    return number


def _signed_number(value, path):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise InputError(path + ":FINITE_DECIMAL_REQUIRED")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise InputError(path + ":FINITE_DECIMAL_REQUIRED") from exc
    if not number.is_finite():
        raise InputError(path + ":FINITE_DECIMAL_REQUIRED")
    return number


def _decimal_text(value):
    return format(value, "f")


def _receipt_digest(receipt):
    content = {k: v for k, v in receipt.items() if k != "output_receipt_sha256"}
    try:
        raw = json.dumps(content, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("RESTART_RECEIPT_INTEGRITY_INVALID_JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _seal_receipt(receipt):
    return {**receipt, "output_receipt_sha256": _receipt_digest(receipt)}


def _timestamp(obj, name, path, decision=None, max_age=None):
    value = _integer(_need(obj, name, path), path + "." + name)
    if decision is not None and value > decision:
        raise InputError(path + "." + name + ":NOT_YET_AVAILABLE")
    if decision is not None and max_age is not None and decision - value > max_age:
        raise InputError(path + "." + name + ":STALE_BY_SUPPLIED_CONTRACT")
    return value


def _side(item, path):
    value = _need(item, "side", path)
    if isinstance(value, bool) or not isinstance(value, int) or value not in (-1, 1):
        raise InputError(path + ".side:EXPECTED_INTEGER_PLUS_OR_MINUS_ONE")
    return value


def _items(batch, name):
    value = _need(batch, name, "batch")
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise InputError("batch." + name + ":LIST_OF_OBJECTS_REQUIRED")
    return value


def _unit(item, path, currency):
    if _text(item, "quote_currency", path) != currency:
        raise InputError(path + ".quote_currency:UNIT_MISMATCH")
    unit = _text(item, "quantity_unit", path)
    multiple = _number(_need(item, "base_units_per_contract", path),
                       path + ".base_units_per_contract", positive=True)
    if unit not in ("BASE_ASSET", "CONTRACTS"):
        raise InputError(path + ".quantity_unit:UNSUPPORTED_LINEAR_QUANTITY_UNIT")
    if unit == "BASE_ASSET" and multiple != ONE:
        raise InputError(path + ".base_units_per_contract:BASE_ASSET_REQUIRES_ONE")
    return multiple


def _risk(item, path, currency, now, max_age, *, proposal):
    side = _side(item, path)
    multiplier = _unit(item, path, currency)
    price_field = "entry_price" if proposal else "mark_price"
    price_clock = "entry_available_ts_ms" if proposal else "mark_available_ts_ms"
    price = _number(_need(item, price_field, path), path + "." + price_field,
                    positive=True)
    _timestamp(item, price_clock, path, now, max_age)
    # The base fields are the ORIGINAL entry stop, not a future/latest-stop dump.
    stop = _number(_need(item, "stop_price", path), path + ".stop_price", positive=True)
    base_available = _timestamp(item, "stop_available_ts_ms", path, now)
    base_effective = _timestamp(item, "stop_effective_ts_ms", path, now)
    stop_records = [(base_available, base_effective, stop)]
    updates = item.get("stop_updates", [])
    if not isinstance(updates, list):
        raise InputError(path + ".stop_updates:LIST_REQUIRED")
    if proposal and updates:
        raise InputError(path + ".stop_updates:NEW_ENTRY_USES_INITIAL_STOP_ONLY")
    for index, update in enumerate(updates):
        p = path + ".stop_updates[" + str(index) + "]"
        available = _timestamp(update, "available_ts_ms", p)
        effective = _timestamp(update, "effective_ts_ms", p)
        value = _number(_need(update, "stop_price", p), p + ".stop_price", positive=True)
        # An ambiguous same-time update cannot release risk for this admission.
        if available < now and effective <= now:
            stop_records.append((available, effective, value))
    latest = max((a, e) for a, e, _ in stop_records)
    values = {v for a, e, v in stop_records if (a, e) == latest}
    if len(values) != 1:
        raise InputError(path + ".stop_updates:AMBIGUOUS_SAME_TIME_STOP")
    stop = values.pop()
    distance = Decimal(side) * (price - stop)
    if distance <= 0:
        raise InputError(path + ".stop_price:AT_OR_THROUGH_STOP_REQUIRES_FILL_RECONCILIATION")
    reserve = _number(_need(item, "cost_reserve_quote_per_base_unit", path),
                      path + ".cost_reserve_quote_per_base_unit")
    _timestamp(item, "cost_available_ts_ms", path, now)
    return (distance + reserve) * multiplier, stop


def _contract(contract, now):
    if not isinstance(contract, dict):
        raise InputError("contract:REQUIRED_INPUT")
    status = _text(contract, "binding_status", "contract")
    if status not in ("BOUND", "SYNTHETIC_ONLY"):
        raise InputError("contract.binding_status:REQUIRED_INPUT_BOUND_CONTRACT")
    ref = _text(contract, "source_ref", "contract")
    digest = _text(contract, "source_sha256", "contract")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InputError("contract.source_sha256:SHA256_REQUIRED")
    if status == "BOUND" and not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise InputError("contract.source_ref:IMMUTABLE_COMMIT_REQUIRED")
    if status == "SYNTHETIC_ONLY" and not ref.startswith("fixture://"):
        raise InputError("contract.source_ref:SYNTHETIC_FIXTURE_LABEL_REQUIRED")
    if _text(contract, "risk_unit", "contract") != "quote_currency_stop_distance_plus_reserve":
        raise InputError("contract.risk_unit:UNSUPPORTED_RISK_UNIT")
    if _text(contract, "quantity_contract", "contract") != "EXPLICIT_REQUESTED_QUANTITY":
        raise InputError("contract.quantity_contract:EXPLICIT_REQUESTED_QUANTITY_REQUIRED")
    if _text(contract, "same_time_policy", "contract") != "STRICTLY_EARLIER_KNOWN_OUTCOMES":
        raise InputError("contract.same_time_policy:UNSUPPORTED_ORDERING")
    currency = _text(contract, "quote_currency", "contract")
    _timestamp(contract, "available_ts_ms", "contract", now)
    age = _integer(_need(contract, "max_mark_age_ms", "contract"), "contract.max_mark_age_ms")
    total = _number(_need(contract, "total_risk_limit_quote", "contract"),
                    "contract.total_risk_limit_quote")
    directions = _need(contract, "directional_risk_limit_quote", "contract")
    if not isinstance(directions, dict) or set(directions) != {"1", "-1"}:
        raise InputError("contract.directional_risk_limit_quote:BOTH_DIRECTIONS_REQUIRED")
    sides = {k: _number(v, "contract.directional_risk_limit_quote." + k)
             for k, v in directions.items()}
    return status, currency, age, total, sides


def _known_outcomes(items, now, currency):
    known, batches, seen = [], {}, set()
    excluded = 0
    for i, item in enumerate(items):
        path = "outcomes[" + str(i) + "]"
        identity = _text(item, "position_id", path)
        if identity in seen:
            raise InputError(path + ".position_id:DUPLICATE_OUTCOME")
        seen.add(identity)
        available = _timestamp(item, "outcome_available_ts_ms", path)
        if available >= now:
            excluded += 1
            continue
        symbol = _text(item, "symbol", path)
        side = _side(item, path)
        setup = _text(item, "setup_id", path)
        if _text(item, "quote_currency", path) != currency:
            raise InputError(path + ".quote_currency:UNIT_MISMATCH")
        value = _signed_number(_need(item, "net_quote", path), path + ".net_quote")
        known.append((identity, symbol, side, setup, available, value))
        batches.setdefault(available, []).append((identity, value))
    audit = {
        "known_outcome_count": len(known),
        "known_loss_count": sum(v < 0 for _, _, _, _, _, v in known),
        "known_win_count": sum(v > 0 for _, _, _, _, _, v in known),
        "known_net_quote": _decimal_text(sum((v for _, _, _, _, _, v in known), ZERO)),
        "excluded_not_yet_known_outcome_count": excluded,
        "known_outcome_batches": [
            {"available_ts_ms": ts, "position_ids": sorted(k for k, _ in values),
             "loss_count": sum(v < 0 for _, v in values),
             "win_count": sum(v > 0 for _, v in values),
             "net_quote": _decimal_text(sum((v for _, v in values), ZERO))}
            for ts, values in sorted(batches.items())],
    }
    return known, audit


def _calculate(batch, contract):
    now = _timestamp(batch, "decision_ts_ms", "batch")
    status, currency, age, limit, side_limits = _contract(contract, now)
    if _need(batch, "simultaneous_batch_complete", "batch") is not True:
        raise InputError("batch.simultaneous_batch_complete:COMPLETE_BATCH_REQUIRED")
    _text(batch, "exposure_snapshot_id", "batch")
    _timestamp(batch, "exposure_available_ts_ms", "batch", now, age)
    positions, proposals, outcomes = (_items(batch, name) for name in ("positions", "proposals", "outcomes"))
    known, audit = _known_outcomes(outcomes, now, currency)
    existing = {"1": ZERO, "-1": ZERO}
    existing_ids, active_setups = set(), set()
    for i, item in enumerate(positions):
        path = "positions[" + str(i) + "]"
        identity = _text(item, "position_id", path)
        if identity in existing_ids:
            raise InputError(path + ".position_id:DUPLICATE_EXPOSURE")
        if any(k == identity for k, _, _, _, _, _ in known):
            raise InputError(path + ".position_id:KNOWN_CLOSED_STILL_IN_EXPOSURE")
        existing_ids.add(identity)
        symbol, side, setup = _text(item, "symbol", path), _side(item, path), _text(item, "setup_id", path)
        active_setups.add((symbol, side, setup))
        quantity = _number(_need(item, "quantity", path), path + ".quantity", positive=True)
        unit_risk, _ = _risk(item, path, currency, now, age, proposal=False)
        existing[str(side)] += quantity * unit_risk
    total_existing = sum(existing.values(), ZERO)
    available = max(ZERO, limit - total_existing)
    side_available = {s: max(ZERO, side_limits[s] - existing[s]) for s in existing}
    demand = {"1": ZERO, "-1": ZERO}
    requests, request_ids, proposal_setups = [], set(), set()
    for i, item in enumerate(proposals):
        path = "proposals[" + str(i) + "]"
        identity = _text(item, "request_id", path)
        if identity in request_ids or identity in existing_ids:
            raise InputError(path + ".request_id:DUPLICATE_REQUEST_OR_EXPOSURE")
        request_ids.add(identity)
        symbol, side, setup = _text(item, "symbol", path), _side(item, path), _text(item, "setup_id", path)
        setup_key = (symbol, side, setup)
        if setup_key in proposal_setups:
            raise InputError(path + ".setup_id:DUPLICATE_SAME_SETUP_PROPOSALS")
        proposal_setups.add(setup_key)
        permitted = _need(item, "reentry_authorized", path)
        if not isinstance(permitted, bool):
            raise InputError(path + ".reentry_authorized:EXPLICIT_BOOLEAN_REQUIRED")
        quantity = _number(_need(item, "requested_quantity", path), path + ".requested_quantity", positive=True)
        step = _number(_need(item, "quantity_step", path), path + ".quantity_step", positive=True)
        minimum = _number(_need(item, "minimum_quantity", path), path + ".minimum_quantity")
        unit_risk, stop = _risk(item, path, currency, now, age, proposal=True)
        prior_setup = [k for k, sy, sd, se, _, _ in known if (sy, sd, se) == setup_key]
        reasons = []
        if setup_key in active_setups:
            reasons.append("SETUP_ALREADY_OPEN_OR_RESERVED")
        if prior_setup and not permitted:
            reasons.append("SAME_SETUP_REENTRY_NOT_AUTHORIZED")
        risk = quantity * unit_risk
        if not reasons:
            demand[str(side)] += risk
        requests.append((identity, quantity, step, minimum, unit_risk, stop, str(side), reasons, sorted(prior_setup)))
    total_demand = sum(demand.values(), ZERO)
    # One simultaneous batch, one global factor and per-side factors. No FIFO,
    # symbol priority, outcome ranking or redistribution of rounded dust.
    global_factor = min(ONE, available / total_demand) if total_demand else ONE
    factors = {s: min(global_factor, side_available[s] / demand[s]) if demand[s] else global_factor for s in demand}
    allocations = []
    for identity, quantity, step, minimum, unit_risk, stop, side, reasons, prior_setup in requests:
        approved = ZERO if reasons else (quantity * factors[side] / step).to_integral_value(rounding=ROUND_FLOOR) * step
        if approved < minimum:
            approved = ZERO
            reasons = reasons + ["BELOW_MINIMUM_QUANTITY_AFTER_SHARED_BUDGET"]
        if approved == 0 and not reasons:
            reasons = ["NO_SHARED_RISK_BUDGET_OR_QUANTITY_STEP"]
        allocations.append({"request_id": identity, "requested_quantity": _decimal_text(quantity),
            "admitted_quantity": _decimal_text(approved), "reserved_risk_quote": _decimal_text(approved * unit_risk),
            "risk_per_quantity_unit_quote": _decimal_text(unit_risk), "stop_used": _decimal_text(stop),
            "side": int(side), "shared_scale": _decimal_text(factors[side]),
            "admission": "ADMIT" if approved > 0 else "BLOCK", "reasons": reasons,
            "known_same_setup_previous_position_ids": prior_setup})
    # Sorting is presentation only; each quantity was calculated simultaneously.
    allocations.sort(key=lambda r: r["request_id"])
    used = {s: sum((Decimal(a["reserved_risk_quote"]) for a in allocations if str(a["side"]) == s), ZERO) for s in demand}
    if sum(used.values(), ZERO) > available or any(used[s] > side_available[s] for s in used):
        raise InputError("allocation:NUMERIC_BUDGET_INVARIANT_FAILED")
    audit.update({"quote_currency": currency, "existing_risk_quote": _decimal_text(total_existing),
        "existing_directional_risk_quote": {s: _decimal_text(v) for s, v in existing.items()},
        "total_available_risk_quote": _decimal_text(available),
        "directional_available_risk_quote": {s: _decimal_text(v) for s, v in side_available.items()},
        "requested_eligible_risk_quote": _decimal_text(total_demand),
        "new_reserved_risk_quote": _decimal_text(sum(used.values(), ZERO)),
        "risk_limit_already_exceeded": total_existing > limit or any(existing[s] > side_limits[s] for s in existing),
        "realized_pnl_changes_budget": False,
        "stop_updates_at_same_time_cannot_release_risk": True,
        "future_outcome_labels_used_for_allocation": False,
        "quantity_rounding": "DOWN_NO_REASSIGNMENT_OF_DUST",
        "requires_atomic_owner_reservation_and_full_chronology": True})
    return {"status": "SYNTHETIC_ONLY" if status == "SYNTHETIC_ONLY" else "READY",
            "action": "hold", "allocations": allocations, "required_inputs": [], "audit": audit}


def evaluate_batch(batch, contract=None, *, enabled=False, receipt=None):
    """Return a calculation receipt; receipt enables restart-safe identical replay.

    A different payload under an already processed batch_id is a hard conflict.
    This function makes no execution claim: action remains hold even when an
    allocation is computable. The owner must atomically commit the entire batch.
    """
    if not isinstance(batch, dict):
        raise ValueError("BATCH_OBJECT_REQUIRED")
    batch_id = batch.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("BATCH_ID_REQUIRED")
    try:
        raw = json.dumps({"batch": batch, "contract": contract, "enabled": enabled},
                         sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("JSON_FINITE_INPUT_REQUIRED") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if receipt is not None:
        if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
            raise ValueError("RESTART_RECEIPT_SCHEMA_REQUIRED")
        if receipt.get("output_receipt_sha256") != _receipt_digest(receipt):
            raise ValueError("RESTART_RECEIPT_INTEGRITY_MISMATCH")
        if receipt.get("batch_id") == batch_id:
            if receipt.get("input_sha256") != digest:
                raise ValueError("CONFLICTING_BATCH_REPLAY")
            return deepcopy(receipt)
    base = {"schema": SCHEMA, "batch_id": batch_id, "input_sha256": digest,
            "orders": 0, "economic_replays": 0, "execution_authorized": False}
    if enabled is not True:
        return _seal_receipt({**base, "status": "DISABLED", "action": "hold", "allocations": [],
                "required_inputs": [], "audit": {"upstream_behavior_unchanged": True}})
    try:
        with localcontext() as context:
            context.prec = 80
            result = _calculate(batch, contract)
    except (InputError, InvalidOperation) as exc:
        result = {"status": "REQUIRED_INPUT", "action": "hold", "allocations": [],
                  "required_inputs": [str(exc)], "audit": {"no_partial_allocation": True}}
    return _seal_receipt({**base, **result})
