from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_market_digital_twin_contract_v1 import (
    DigitalTwinContractError,
    evaluate_digital_twin,
    stable_sha,
)

VERSION = "STRATEGY11_MARKET_DIGITAL_TWIN_FIXTURE_V1"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def scenario(**kwargs: Any) -> dict[str, Any]:
    row = dict(kwargs)
    row["scenario_sha"] = stable_sha(row)
    return row


def build_package(policy_sha: str) -> dict[str, Any]:
    portfolio = [
        {
            "strategy_id": "alpha_combo",
            "candidate_sha": "1" * 64,
            "material_sha": "2" * 64,
            "weight": 0.60,
        },
        {
            "strategy_id": "turtle_trend",
            "candidate_sha": "3" * 64,
            "material_sha": "4" * 64,
            "weight": 0.40,
        },
    ]
    scenarios = [
        scenario(
            scenario_id="baseline-001",
            scenario_type="BASELINE",
            seed=101,
            returns_by_strategy={
                "alpha_combo": [0.30, -0.10, 0.40, 0.20, -0.05, 0.25],
                "turtle_trend": [0.20, -0.05, 0.30, 0.15, 0.05, 0.20],
            },
            fill_ratio=1.0,
            spread_bps=4.0,
            slippage_bps=3.0,
            fee_bps=5.0,
            funding_bps=1.0,
            latency_ms=250,
            api_gap_bars=0,
            stale_feed_ms=1000,
            liquidity_depth_ratio=1.0,
            liquidation_buffer_pct=30.0,
        ),
        scenario(
            scenario_id="liquidity-shock-001",
            scenario_type="LIQUIDITY_SHOCK",
            seed=202,
            returns_by_strategy={
                "alpha_combo": [-1.20, -1.00, 0.20, -0.40, 0.10, -0.20],
                "turtle_trend": [-0.80, -1.10, 0.10, -0.30, 0.05, -0.10],
            },
            fill_ratio=0.35,
            spread_bps=35.0,
            slippage_bps=45.0,
            fee_bps=5.0,
            funding_bps=8.0,
            latency_ms=2400,
            api_gap_bars=0,
            stale_feed_ms=5000,
            liquidity_depth_ratio=0.10,
            liquidation_buffer_pct=6.0,
        ),
        scenario(
            scenario_id="api-gap-001",
            scenario_type="API_GAP",
            seed=303,
            returns_by_strategy={
                "alpha_combo": [0.10, -0.60, -0.40, 0.20, 0.10, -0.10],
                "turtle_trend": [0.05, -0.40, -0.50, 0.15, 0.05, -0.05],
            },
            fill_ratio=0.70,
            spread_bps=12.0,
            slippage_bps=18.0,
            fee_bps=5.0,
            funding_bps=2.0,
            latency_ms=2800,
            api_gap_bars=3,
            stale_feed_ms=200000,
            liquidity_depth_ratio=0.50,
            liquidation_buffer_pct=12.0,
        ),
        scenario(
            scenario_id="correlation-break-001",
            scenario_type="CORRELATION_BREAK",
            seed=404,
            returns_by_strategy={
                "alpha_combo": [0.20, -0.90, -0.80, -0.50, 0.15, 0.10],
                "turtle_trend": [0.10, -0.85, -0.75, -0.45, 0.05, 0.08],
            },
            fill_ratio=1.0,
            spread_bps=8.0,
            slippage_bps=8.0,
            fee_bps=5.0,
            funding_bps=2.0,
            latency_ms=700,
            api_gap_bars=0,
            stale_feed_ms=2000,
            liquidity_depth_ratio=0.75,
            liquidation_buffer_pct=14.0,
        ),
        scenario(
            scenario_id="funding-spike-001",
            scenario_type="FUNDING_SPIKE",
            seed=505,
            returns_by_strategy={
                "alpha_combo": [0.25, 0.10, -0.15, 0.20, -0.10, 0.15],
                "turtle_trend": [0.20, 0.05, -0.10, 0.15, -0.05, 0.10],
            },
            fill_ratio=1.0,
            spread_bps=6.0,
            slippage_bps=5.0,
            fee_bps=5.0,
            funding_bps=90.0,
            latency_ms=500,
            api_gap_bars=0,
            stale_feed_ms=1500,
            liquidity_depth_ratio=0.90,
            liquidation_buffer_pct=20.0,
        ),
        scenario(
            scenario_id="latency-plus-one-bar-001",
            scenario_type="LATENCY_PLUS_ONE_BAR",
            seed=606,
            returns_by_strategy={
                "alpha_combo": [0.15, -0.35, 0.05, -0.20, 0.10, 0.05],
                "turtle_trend": [0.10, -0.25, 0.00, -0.15, 0.08, 0.03],
            },
            fill_ratio=0.85,
            spread_bps=10.0,
            slippage_bps=15.0,
            fee_bps=5.0,
            funding_bps=2.0,
            latency_ms=4000,
            api_gap_bars=1,
            stale_feed_ms=60000,
            liquidity_depth_ratio=0.60,
            liquidation_buffer_pct=10.0,
        ),
    ]
    return {
        "source_binding": {
            "source_sha": "a" * 64,
            "data_sha": "b" * 64,
            "portfolio_sha": stable_sha(portfolio),
            "policy_sha": policy_sha,
            "run_id": "fixture-run-digital-twin-001",
            "artifact_id": "fixture-artifact-digital-twin-001",
        },
        "portfolio": portfolio,
        "scenarios": scenarios,
    }


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
    package = build_package(str(policy["policy_sha"]))

    first = evaluate_digital_twin(package, policy)
    second = evaluate_digital_twin(deepcopy(package), policy)
    assert first["state"] == "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE"
    assert first["capital_gate"] == "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    assert first["scenario_count"] == 6
    assert first["twin_result_sha"] == second["twin_result_sha"]
    assert all(first["liquidity_failure_coverage"].values())
    assert {"liquidity-shock-001", "api-gap-001", "funding-spike-001", "latency-plus-one-bar-001"}.issubset(set(first["risk_scenarios"]))

    missing = deepcopy(package)
    missing["scenarios"] = [row for row in missing["scenarios"] if row["scenario_type"] != "API_GAP"]
    missing_error = expect_error(
        "MISSING_API_GAP_SCENARIO",
        lambda: evaluate_digital_twin(missing, policy),
        "MISSING_SCENARIO_TYPES:API_GAP",
    )

    tampered = deepcopy(package)
    tampered["scenarios"][0]["returns_by_strategy"]["alpha_combo"][0] = 99.0
    tamper_error = expect_error(
        "SCENARIO_SHA_TAMPER",
        lambda: evaluate_digital_twin(tampered, policy),
        "SCENARIO_SHA_MISMATCH:baseline-001",
    )

    bad_portfolio = deepcopy(package)
    bad_portfolio["portfolio"][0]["weight"] = 0.9
    portfolio_error = expect_error(
        "PORTFOLIO_WEIGHT_TAMPER",
        lambda: evaluate_digital_twin(bad_portfolio, policy),
        "PORTFOLIO_WEIGHT_SUM",
    )

    summary = {
        "schema_version": "strategy11.market_digital_twin_fixture.v1",
        "version": VERSION,
        "state": "PASS_MARKET_DIGITAL_TWIN_FIXTURES",
        "case_count": 5,
        "result": first,
        "determinism_repeat_sha": second["twin_result_sha"],
        "negative_cases": [missing_error, tamper_error, portfolio_error],
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
    atomic_json(args.out / "digital_twin_result.json", first)
    atomic_json(args.out / "scenario_results.json", first["scenario_results"])
    print(summary["state"], first["scenario_count"], first["capital_gate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
