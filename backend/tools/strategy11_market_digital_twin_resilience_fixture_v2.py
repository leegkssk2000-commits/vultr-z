from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_market_digital_twin_contract_v1 import DigitalTwinContractError, stable_sha
from backend.contracts.strategy11_market_digital_twin_resilience_v2 import evaluate_digital_twin_resilience_v2
from backend.tools.strategy11_market_digital_twin_fixture_v1 import build_package

VERSION = "STRATEGY11_MARKET_DIGITAL_TWIN_RESILIENCE_FIXTURE_V2"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def reseal(row: dict[str, Any]) -> None:
    material = {key: value for key, value in row.items() if key != "scenario_sha"}
    row["scenario_sha"] = stable_sha(material)


def resilient_package(policy_sha: str) -> dict[str, Any]:
    package = build_package(policy_sha)
    for row in package["scenarios"]:
        scenario_type = row["scenario_type"]
        if scenario_type == "LIQUIDITY_SHOCK":
            row.update({
                "fill_ratio": 0.45,
                "spread_bps": 10.0,
                "slippage_bps": 10.0,
                "fee_bps": 5.0,
                "funding_bps": 5.0,
                "latency_ms": 1000,
                "api_gap_bars": 0,
                "stale_feed_ms": 5000,
                "liquidity_depth_ratio": 0.20,
                "liquidation_buffer_pct": 12.0,
            })
        reseal(row)
    return package


def expect_error(name: str, fn: Any, prefix: str) -> dict[str, Any]:
    try:
        fn()
    except DigitalTwinContractError as exc:
        message = str(exc)
        if not message.startswith(prefix):
            raise AssertionError(f"{name}:{message}:{prefix}") from exc
        return {"name": name, "state": "PASS_EXPECTED_ERROR", "error": message}
    raise AssertionError(f"{name}:EXPECTED_ERROR_NOT_RAISED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))

    risk_package = build_package(str(policy["policy_sha"]))
    risk = evaluate_digital_twin_resilience_v2(risk_package, policy)
    assert risk["state"] == "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE"
    assert risk["capital_gate"] == "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    assert "liquidity-shock-001" in risk["blocking_scenarios"]
    liquidity_row = next(row for row in risk["resilience_rows"] if row["scenario_id"] == "liquidity-shock-001")
    assert "COST_BREACH" not in liquidity_row["unexpected_risk_flags"]
    assert liquidity_row["unexpected_risk_flags"] == ["LIQUIDATION_BUFFER_BREACH"]

    package = resilient_package(str(policy["policy_sha"]))
    passed = evaluate_digital_twin_resilience_v2(package, policy)
    repeated = evaluate_digital_twin_resilience_v2(deepcopy(package), policy)
    assert passed["state"] == "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE"
    assert passed["capital_gate"] == "PASS_DIGITAL_TWIN_RISK_ENVELOPE"
    assert passed["blocking_scenarios"] == []
    assert all(row["resilience_pass"] is True for row in passed["resilience_rows"])
    assert passed["twin_result_sha"] == repeated["twin_result_sha"]

    missing_expected = deepcopy(package)
    funding_row = next(row for row in missing_expected["scenarios"] if row["scenario_type"] == "FUNDING_SPIKE")
    funding_row["funding_bps"] = 1.0
    reseal(funding_row)
    missing_result = evaluate_digital_twin_resilience_v2(missing_expected, policy)
    assert missing_result["capital_gate"] == "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    funding_resilience = next(row for row in missing_result["resilience_rows"] if row["scenario_type"] == "FUNDING_SPIKE")
    assert funding_resilience["missing_expected_flags"] == ["COST_BREACH"]

    bad_policy = deepcopy(policy)
    del bad_policy["allowed_expected_flags_by_type"]["BASELINE"]
    bad_policy_error = expect_error(
        "RESILIENCE_POLICY_SET_MISMATCH",
        lambda: evaluate_digital_twin_resilience_v2(package, bad_policy),
        "POLICY_SHA_MISMATCH",
    )

    summary = {
        "schema_version": "strategy11.market_digital_twin_resilience_fixture.v2",
        "version": VERSION,
        "state": "PASS_MARKET_DIGITAL_TWIN_RESILIENCE_FIXTURES_V2",
        "case_count": 4,
        "risk_exposed": risk,
        "resilience_pass": passed,
        "missing_expected_stress_hold": missing_result,
        "negative_cases": [bad_policy_error],
        "runtime_activation_allowed": False,
        "market_data_mutation_allowed": False,
        "order_submission_allowed": False,
        "capital_allocation_allowed": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    summary["fixture_sha"] = stable_sha(summary)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "summary.json", summary)
    atomic_json(args.out / "risk_exposed.json", risk)
    atomic_json(args.out / "resilience_pass.json", passed)
    print(summary["state"], passed["capital_gate"], len(risk["blocking_scenarios"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
