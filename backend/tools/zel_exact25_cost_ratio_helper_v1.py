from __future__ import annotations

import argparse
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_COST_RATIO_HELPER_V1"
SCHEMA = "zel.exact25.cost_ratio.helper.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def decimal_value(value: Any, field: str, *, allow_zero: bool = True) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RuntimeError(f"INVALID_DECIMAL:{field}:{value}") from exc
    if not parsed.is_finite():
        raise RuntimeError(f"NONFINITE_DECIMAL:{field}:{value}")
    if parsed < 0 or (not allow_zero and parsed == 0):
        raise RuntimeError(f"INVALID_SIGN:{field}:{value}")
    return parsed


def all_in_cost_pct(
    *,
    round_trip_fee_pct: Any,
    slippage_stress_pct: Any,
    funding_horizon_pct: Any,
) -> Decimal:
    fee = decimal_value(round_trip_fee_pct, "round_trip_fee_pct")
    slippage = decimal_value(slippage_stress_pct, "slippage_stress_pct")
    funding = decimal_value(funding_horizon_pct, "funding_horizon_pct")
    total = fee + slippage + funding
    if total <= 0:
        raise RuntimeError("ALL_IN_COST_MUST_BE_POSITIVE")
    return total


def entry_risk_to_cost_ratio(
    *,
    risk_distance_pct: Any,
    round_trip_fee_pct: Any,
    slippage_stress_pct: Any,
    funding_horizon_pct: Any,
) -> Decimal:
    risk = decimal_value(risk_distance_pct, "risk_distance_pct", allow_zero=False)
    cost = all_in_cost_pct(
        round_trip_fee_pct=round_trip_fee_pct,
        slippage_stress_pct=slippage_stress_pct,
        funding_horizon_pct=funding_horizon_pct,
    )
    return risk / cost


def frozen_candidate_grid(policy: Mapping[str, Any]) -> list[Decimal]:
    raw = policy.get("candidate_ratio_thresholds")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise RuntimeError("CANDIDATE_RATIO_GRID_MISSING")
    values = [decimal_value(item, "candidate_ratio_threshold", allow_zero=False) for item in raw]
    if values != sorted(values):
        raise RuntimeError("CANDIDATE_RATIO_GRID_NOT_SORTED")
    if len(values) != len(set(values)):
        raise RuntimeError("CANDIDATE_RATIO_GRID_DUPLICATE")
    return values


def bind_cost_receipt(policy: Mapping[str, Any], cost_receipt: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "round_trip_fee_pct",
        "slippage_stress_pct",
        "funding_horizon_pct",
        "receipt_sha256",
    )
    missing = [key for key in required if key not in cost_receipt]
    if missing:
        raise RuntimeError(f"COST_RECEIPT_FIELDS_MISSING:{missing}")
    if cost_receipt.get("source") not in ("BINGX_REALIZED_CALIBRATION", "BINGX_PUBLIC_PLUS_REALIZED_CALIBRATION"):
        raise RuntimeError("COST_RECEIPT_SOURCE_NOT_ACCEPTED")
    if cost_receipt.get("future_information_used") is not False:
        raise RuntimeError("COST_RECEIPT_FUTURE_INFORMATION_FAIL")
    if int(cost_receipt.get("protected_mutations", -1)) != 0:
        raise RuntimeError("COST_RECEIPT_PROTECTED_MUTATION_FAIL")
    total_cost = all_in_cost_pct(
        round_trip_fee_pct=cost_receipt["round_trip_fee_pct"],
        slippage_stress_pct=cost_receipt["slippage_stress_pct"],
        funding_horizon_pct=cost_receipt["funding_horizon_pct"],
    )
    grid = frozen_candidate_grid(policy)
    incumbent_risk = decimal_value(policy["diagnostic_incumbent"]["minimum_risk_distance_pct"], "incumbent_risk", allow_zero=False)
    binding = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "axis_id": str(policy["axis_id"]),
        "strategy_id": str(policy["strategy_id"]),
        "cost_receipt_sha256": str(cost_receipt["receipt_sha256"]),
        "round_trip_fee_pct": format(decimal_value(cost_receipt["round_trip_fee_pct"], "fee"), "f"),
        "slippage_stress_pct": format(decimal_value(cost_receipt["slippage_stress_pct"], "slippage"), "f"),
        "funding_horizon_pct": format(decimal_value(cost_receipt["funding_horizon_pct"], "funding"), "f"),
        "all_in_cost_pct": format(total_cost, "f"),
        "diagnostic_incumbent_risk_distance_pct": format(incumbent_risk, "f"),
        "diagnostic_incumbent_ratio": format(incumbent_risk / total_cost, "f"),
        "candidate_ratio_thresholds": [format(value, "f") for value in grid],
        "selection_on_w1_only": True,
        "freeze_for_w2_w3": True,
        "economics_inspected": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    binding["binding_sha256"] = stable_sha(binding)
    return binding


def self_test() -> int:
    ratio = entry_risk_to_cost_ratio(
        risk_distance_pct="0.16",
        round_trip_fee_pct="0.08",
        slippage_stress_pct="0.04",
        funding_horizon_pct="0.00",
    )
    assert ratio == Decimal("1.333333333333333333333333333")
    policy = {
        "axis_id": "ENTRY_RISK_DISTANCE_TO_ALL_IN_COST_RATIO",
        "strategy_id": "scalp_snap",
        "candidate_ratio_thresholds": ["0.75", "1.00", "1.25", "1.50", "2.00", "2.50"],
        "diagnostic_incumbent": {"minimum_risk_distance_pct": "0.16"},
    }
    receipt = {
        "source": "BINGX_REALIZED_CALIBRATION",
        "round_trip_fee_pct": "0.08",
        "slippage_stress_pct": "0.04",
        "funding_horizon_pct": "0.00",
        "receipt_sha256": "a" * 64,
        "future_information_used": False,
        "protected_mutations": 0,
    }
    binding = bind_cost_receipt(policy, receipt)
    assert binding["all_in_cost_pct"] == "0.12"
    assert binding["diagnostic_incumbent_ratio"].startswith("1.333333")
    assert binding["candidate_ratio_thresholds"] == ["0.75", "1.00", "1.25", "1.50", "2.00", "2.50"]
    try:
        entry_risk_to_cost_ratio(
            risk_distance_pct="0.16",
            round_trip_fee_pct="0",
            slippage_stress_pct="0",
            funding_horizon_pct="0",
        )
    except RuntimeError as exc:
        assert "ALL_IN_COST_MUST_BE_POSITIVE" in str(exc)
    else:
        raise AssertionError("zero all-in cost must fail")
    try:
        decimal_value(float("nan"), "nan")
    except RuntimeError as exc:
        assert "NONFINITE_DECIMAL" in str(exc)
    else:
        raise AssertionError("non-finite value must fail")
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("only --self-test is available in preparation mode")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
