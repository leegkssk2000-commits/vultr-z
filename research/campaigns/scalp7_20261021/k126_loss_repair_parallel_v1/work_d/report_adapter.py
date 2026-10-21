"""Aggregate supplied ledgers only. Never simulate fills, size orders or claim NAV.

The common-risk interface accepts A's two full chronological ledgers, not a
filtered/scaled copy of the saved 126 trades. Its provenance declarations must
be verified by A against immutable execution receipts before publication.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from functools import wraps
import hashlib
import json
import re

CURRENT_BASELINE = "81a12c422ee9329996d2f6b983267d2def490d4b"
CURRENT_IDENTITY = "scalp7_k126_native_pullback_invalidation_next_open_v1"
OWNER = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
FIXED_INPUTS = {
    "baseline_rows_uncompressed_sha256": "98eaa46994eb8c4e9d89e7e17bbb9a9cce97b86f6a3a727c11e8136da75a85f3",
    "context_fit_sha256": "168044bf3bfd2bc4299c55fca84bc45c2e3ce56a79310e4583b02277c296b86c",
    "cost_snapshot_sha256": "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73",
    "window_utc": ["2026-01-13T00:00:00Z", "2026-09-15T00:00:00Z"],
}
MATCHED_FIELDS = ("baseline_commit", "baseline_identity", "source_binding_sha256",
                  "window_binding_sha256", "cost_binding_sha256", "risk_budget", *FIXED_INPUTS)
WINDOW_START_MS = 1768262400000
WINDOW_END_MS = 1789430400000


class RequiredInput(ValueError):
    pass


def required(obj, name):
    if name not in obj or obj[name] is None:
        raise RequiredInput(name)
    return obj[name]


def number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("INVALID_NUMBER:" + name)
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("INVALID_NUMBER:" + name) from exc
    if not result.is_finite() or (minimum is not None and result < minimum):
        raise ValueError("INVALID_NUMBER:" + name)
    return result


def exact_accounting(function):
    """Use input-derived precision for finite sums/products; never round income.

    Four times the widest input decimal span covers the largest three-factor
    quantity/notional and ratio cross-products, plus sum carry digits. Sorting
    report keys below is deterministic arithmetic, never an admission priority.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        spans = []

        def visit(value):
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
            elif isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool):
                try:
                    item = Decimal(str(value))
                except InvalidOperation:
                    return
                if item.is_finite():
                    spans.append(max(item.adjusted() + 1, 0) + max(-item.as_tuple().exponent, 0))

        visit(args)
        visit(kwargs)
        with localcontext() as context:
            context.prec = max(64, 4 * max(spans, default=1) + len(str(len(spans))) + 16)
            return function(*args, **kwargs)
    return wrapped


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def digest(value, length, name):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{%d}" % length, value):
        raise ValueError("INVALID_DIGEST:" + name)


def key(row):
    """The signal key identifies the opportunity, not a sorted admission priority."""
    symbol = required(row, "symbol")
    side = required(row, "side")
    signal = required(row, "signal_ts_ms")
    if not isinstance(symbol, str) or not symbol or isinstance(side, bool) or side not in (-1, 1):
        raise ValueError("INVALID_TRADE_KEY")
    if isinstance(signal, bool) or not isinstance(signal, int) or signal < 0:
        raise ValueError("INVALID_SIGNAL_TIMESTAMP")
    return (symbol, side, signal)


@exact_accounting
def saved_equal_notional(rows, authoritative_metrics=None):
    """Saved-size diagnostic only; authoritative row-streak metrics remain intact.

    Costs already include the recorded carry scenario. Do not add it again.
    This function does not evaluate an admission policy or infer account size.
    """
    seen = set()
    gross = cost = Decimal(0)
    winners = large_winners = 0
    for row in rows:
        k = key(row)
        if k in seen:
            raise ValueError("DUPLICATE_LIFECYCLE")
        seen.add(k)
        if required(row, "management_comparison_identity") != CURRENT_IDENTITY:
            raise ValueError("CURRENT_BASELINE_IDENTITY_MISMATCH")
        g = number(required(row, "gross_bps"), "gross_bps")
        c = number(required(row, "cost_bps"), "cost_bps", Decimal(0))
        gross += g
        cost += c
        if g - c > 0:
            winners += 1
            # Reuse A's existing retrospective cohort; never an admission feature.
            large_winners += number(required(row, "mfe_R"), "mfe_R", Decimal(0)) >= 2
    return {
        "state": "SAVED_EQUAL_NOTIONAL_DIAGNOSTIC",
        "baseline_commit": CURRENT_BASELINE,
        "identity": CURRENT_IDENTITY,
        "unit": "equal_notional_trade_bps",
        "T": len(rows), "gross_trade_bps": str(gross),
        "cost1x_trade_bps": str(cost), "cost2x_trade_bps": str(2 * cost),
        "net1x_trade_bps": str(gross - cost), "net2x_trade_bps": str(gross - 2 * cost),
        "winner_T": winners, "large_winner_T": large_winners,
        "large_winner_definition": "existing_A_diagnostic: net1x > 0 and mfe_R >= 2",
        "authoritative_original_row_metrics": deepcopy(authoritative_metrics),
        "row_streak_redefined": False, "account_NAV": False,
        "new_economic_evaluation": False,
    }


def _validate_run(run):
    if required(run, "classification") != "ACTUAL_FULL_CHRONOLOGY":
        raise ValueError("A_FULL_CHRONOLOGY_REQUIRED_NO_FILTERED_OR_PAIRED_PROXY")
    if required(run, "owner") != OWNER:
        raise ValueError("ECONOMIC_OWNER_MISMATCH")
    if not required(run, "run_id") or not required(run, "identity"):
        raise ValueError("EMPTY_RUN_IDENTITY")
    if required(run, "opportunity_stream_complete") is not True:
        raise ValueError("FULL_OPPORTUNITY_STREAM_REQUIRED")
    if required(run, "unresolved") != []:
        raise ValueError("UNRESOLVED_LEDGER_NO_COMPLETE_COMPARISON")
    contract = required(run, "contract")
    for field in MATCHED_FIELDS:
        required(contract, field)
    if contract["baseline_commit"] != CURRENT_BASELINE or contract["baseline_identity"] != CURRENT_IDENTITY:
        raise ValueError("EXACT_CURRENT126_BASELINE_REQUIRED")
    for field in ("source_binding_sha256", "window_binding_sha256", "cost_binding_sha256"):
        digest(contract[field], 64, field)
    if any(contract[name] != value for name, value in FIXED_INPUTS.items()):
        raise ValueError("EXACT_CURRENT_SOURCE_WINDOW_COST_REQUIRED")
    budget = contract["risk_budget"]
    if required(budget, "risk_unit") != "quote_currency_stop_distance_plus_reserve":
        raise ValueError("RISK_UNIT_MISMATCH")
    currency = required(budget, "quote_currency")
    if not isinstance(currency, str) or not currency:
        raise ValueError("EMPTY_QUOTE_CURRENCY")
    digest(required(budget, "source_ref"), 40, "risk_budget.source_ref")
    digest(required(budget, "source_sha256"), 64, "risk_budget.source_sha256")
    number(required(budget, "total_risk_limit_quote"), "total_risk_limit_quote", Decimal(0))
    sides = required(budget, "directional_risk_limit_quote")
    if set(sides) != {"1", "-1"}:
        raise ValueError("DIRECTIONAL_LIMIT_SET_MISMATCH")
    for side, value in sides.items():
        number(value, "directional_risk_limit_quote." + side, Decimal(0))
    digest(required(run, "risk_budget_audit_sha256"), 64, "risk_budget_audit_sha256")
    rows = required(run, "rows")
    if not isinstance(rows, list):
        raise ValueError("ROWS_MUST_BE_LIST")
    digest(required(run, "ledger_sha256"), 64, "ledger_sha256")
    if canonical_sha(rows) != run["ledger_sha256"]:
        raise ValueError("LEDGER_SHA_CHANGED")
    mapped = {}
    for row in rows:
        k = key(row)
        if k in mapped:
            raise ValueError("DUPLICATE_LIFECYCLE")
        if row.get("hypothetical") or row.get("paired_only"):
            raise ValueError("PROXY_ROW_REJECTED")
        if required(row, "quote_currency") != currency:
            raise ValueError("QUOTE_CURRENCY_MISMATCH")
        clocks = [required(row, name) for name in ("entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms")]
        if any(isinstance(t, bool) or not isinstance(t, int) for t in clocks) or not (k[2] <= clocks[0] <= clocks[1] <= clocks[2]):
            raise ValueError("LIFECYCLE_CLOCK_MISMATCH")
        if not (WINDOW_START_MS <= clocks[0] < WINDOW_END_MS and clocks[2] <= WINDOW_END_MS):
            raise ValueError("LIFECYCLE_OUTSIDE_BOUND_WINDOW")
        qty = number(required(row, "entry_quantity"), "entry_quantity", Decimal(0))
        multiplier = number(required(row, "base_units_per_contract"), "base_units_per_contract", Decimal(0))
        unit = required(row, "quantity_unit")
        if qty <= 0 or multiplier <= 0 or unit not in ("BASE_ASSET", "CONTRACTS"):
            raise ValueError("INVALID_QUANTITY_UNIT")
        if unit == "BASE_ASSET" and multiplier != 1:
            raise ValueError("BASE_ASSET_MULTIPLIER_MUST_EQUAL_ONE")
        price = number(required(row, "entry_price"), "entry_price", Decimal(0))
        notional = number(required(row, "entry_notional_quote"), "entry_notional_quote", Decimal(0))
        if price <= 0 or qty * multiplier * price != notional:
            raise ValueError("QUANTITY_NOTIONAL_MISMATCH")
        if not required(row, "admission_receipt_id"):
            raise ValueError("ADMISSION_RECEIPT_REQUIRED")
        risk = number(required(row, "admission_risk_quote"), "admission_risk_quote", Decimal(0))
        gross = number(required(row, "gross_quote"), "gross_quote")
        cost = number(required(row, "cost_quote"), "cost_quote", Decimal(0))
        mfe = number(required(row, "mfe_R_analysis_only"), "mfe_R_analysis_only", Decimal(0))
        mapped[k] = {"row": row, "quantity_base": qty * multiplier, "notional": notional,
                     "gross": gross, "cost": cost, "risk": risk, "mfe": mfe,
                     "net1x": gross - cost, "net2x": gross - 2 * cost}
    return mapped, currency


@exact_accounting
def compare_common_total_risk(control=None, candidate=None):
    """Aggregate A's actual matched-budget ledgers, without running a comparison.

    Declarations and audit SHA references are not proof this function executed
    economics. The caller must publish the referenced A receipts separately.
    """
    missing = []
    if control is None:
        missing.append("A_control_ACTUAL_FULL_CHRONOLOGY_receipt")
    if candidate is None:
        missing.append("A_candidate_ACTUAL_FULL_CHRONOLOGY_receipt")
    if missing:
        return {"state": "REQUIRED_INPUT", "required_inputs": missing,
                "comparison": None, "new_profit_claim": False, "account_NAV": False}
    try:
        before, currency = _validate_run(control)
        after, after_currency = _validate_run(candidate)
    except RequiredInput as exc:
        return {"state": "REQUIRED_INPUT", "required_inputs": [str(exc)],
                "comparison": None, "new_profit_claim": False, "account_NAV": False}
    if currency != after_currency or any(control["contract"][name] != candidate["contract"][name] for name in MATCHED_FIELDS):
        raise ValueError("MATCHED_SOURCE_WINDOW_COST_AND_TOTAL_RISK_CONTRACT_REQUIRED")
    if control["identity"] != CURRENT_IDENTITY:
        raise ValueError("CONTROL_IDENTITY_MUST_BE_CURRENT126")
    common = set(before) & set(after)
    removed = set(before) - set(after)
    added = set(after) - set(before)
    totals = {}
    for unit in ("net1x", "net2x"):
        old = sum((before[k][unit] for k in sorted(before)), Decimal(0))
        new = sum((after[k][unit] for k in sorted(after)), Decimal(0))
        common_delta = sum((after[k][unit] - before[k][unit] for k in sorted(common)), Decimal(0))
        removed_net = sum((before[k][unit] for k in sorted(removed)), Decimal(0))
        added_net = sum((after[k][unit] for k in sorted(added)), Decimal(0))
        assert new - old == common_delta - removed_net + added_net
        totals[unit + "_quote"] = {
            "control": str(old), "candidate": str(new), "delta": str(new - old),
            "common_delta": str(common_delta), "removed_net": str(removed_net),
            "added_net": str(added_net), "attribution_reconciled": True}
    cohorts = {}
    for name, predicate in (("winners", lambda r: r["net1x"] > 0),
                            ("large_winners", lambda r: r["net1x"] > 0 and r["mfe"] >= 2),
                            ("losses", lambda r: r["net1x"] < 0)):
        keys = {k for k, row in before.items() if predicate(row)}
        kept = keys & set(after)
        cohorts[name] = {
            "control_T": len(keys), "retained_T": len(kept), "removed_T": len(keys - kept),
            "worsened_quote_T": sum(after[k]["net1x"] < before[k]["net1x"] for k in kept),
            "control_net1x_quote": str(sum((before[k]["net1x"] for k in sorted(keys)), Decimal(0))),
            "retained_net1x_quote": str(sum((after[k]["net1x"] for k in sorted(kept)), Decimal(0)))}
    # Equal relative size change, identical opportunities/timing and scaled
    # gross/cost are size-only evidence, regardless of reduced monetary losses.
    uniform = bool(common) and not removed and not added
    ratios = set()
    for k in sorted(common):
        a, b = before[k], after[k]
        ratio = Fraction(b["quantity_base"]) / Fraction(a["quantity_base"])
        ratios.add(ratio)
        for field in ("entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms", "entry_price"):
            uniform &= a["row"][field] == b["row"][field]
        uniform &= b["gross"] * a["quantity_base"] == a["gross"] * b["quantity_base"]
        uniform &= b["cost"] * a["quantity_base"] == a["cost"] * b["quantity_base"]
    uniform &= len(ratios) == 1
    scale = next(iter(ratios)) if uniform else None
    # Fractions such as 1/3 stay exact instead of displaying a rounded scale.
    denominator = scale.denominator if scale else 1
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    scale_text = (str(Decimal(scale.numerator) / Decimal(scale.denominator))
                  if scale is not None and denominator == 1 else str(scale)) if uniform else None
    return {
        "state": "A_SUPPLIED_COMMON_TOTAL_RISK_FULL_CHRONOLOGY_REPORT",
        "unit": currency, "contract": deepcopy(control["contract"]),
        "run_ids": {"control": control["run_id"], "candidate": candidate["run_id"]},
        "ledger_sha256": {"control": control["ledger_sha256"], "candidate": candidate["ledger_sha256"]},
        "T": {"control": len(before), "candidate": len(after), "common": len(common),
              "removed": len(removed), "added": len(added)},
        "totals": totals, "cohorts_analysis_only": cohorts,
        "uniform_quantity_scale_only": bool(uniform),
        "uniform_quantity_scale": scale_text,
        "alpha_improvement_claim": False, "account_NAV": False,
        "row_streak_redefined": False,
        "source_provenance_must_be_verified_by_A": True,
        "note": "Quantity reduction is not trading-edge evidence; opportunity/occupancy effects require A full chronology. No NAV or MTM inference.",
    }
