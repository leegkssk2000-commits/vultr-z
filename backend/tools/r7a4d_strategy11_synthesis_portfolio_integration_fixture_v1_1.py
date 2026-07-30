from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_synthesis_classifier_adapter_v1 import adapt_and_classify
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha
from backend.research.strategy11_synthesis_portfolio_integration_v1 import (
    SynthesisPortfolioIntegrationError,
    integrate,
)
from backend.tools.r7a4d_strategy11_synthesis_classifier_adapter_fixture_v1 import (
    classifier_policy,
    fixture_input as adapter_fixture_input,
)

OUT = Path("artifacts/strategy11_synthesis_portfolio_integration_v1")


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except SynthesisPortfolioIntegrationError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def source_trade(trade_id: str, timestamp: str, net_r: float, symbol: str, regime: str) -> dict:
    core = {
        "trade_id": trade_id,
        "timestamp": timestamp,
        "net_r": net_r,
        "symbol": symbol,
        "regime": regime,
    }
    return {**core, "source_row_sha": canonical_sha(core)}


def core_ledger() -> list[dict]:
    values = [0.35, 0.10, 0.50, 0.12, 0.55, 0.25, 0.10, 0.45, 0.30, 0.12, 0.40, 0.20, 0.10, 0.50, 0.25, 0.08]
    regimes = ["UPTREND", "RANGE", "UPTREND", "HIGH_VOL"] * 4
    return [
        source_trade(
            f"core-independent-{index:02d}",
            f"2026-09-{index + 1:02d}T00:00:00Z",
            value,
            "SOLUSDT" if index % 2 == 0 else "XRPUSDT",
            regimes[index],
        )
        for index, value in enumerate(values)
    ]


def core_candidate() -> tuple[dict, dict, list[dict]]:
    candidate_sha = "d" * 64
    strategy_id = "core.turtle.fixture"
    proposal = seal_proposal(
        {
            "schema_version": "strategy11.strategy_proposal.v1",
            "proposal_id": f"proposal.{strategy_id}",
            "strategy_id": strategy_id,
            "candidate_sha": candidate_sha,
            "producer": {"team_lane": "BETA", "role": "RESEARCH", "independent_proposal": True},
            "market": {
                "symbols": ["SOLUSDT", "XRPUSDT"],
                "timeframe": "15m",
                "side": "LONG",
                "regime": "MIXED",
                "session": "ALL",
            },
            "edge": {
                "trades": 16,
                "win_rate_pct": 100.0,
                "net_pct": 5.17,
                "profit_factor": 9.0,
                "payoff": 2.0,
                "positive_windows": 3,
                "total_windows": 3,
                "retention_pct": 88.0,
            },
            "confidence": {"score": 0.90, "uncertainty": 0.10, "sample_quality": "HIGH", "oos_windows": 3},
            "cost_envelope": {
                "fee_bps": 5.0,
                "slippage_bps": 4.0,
                "funding_8h_pct": 0.01,
                "latency_ms": 220.0,
                "stress_multiplier": 2.0,
                "capacity_notional_usdt": 6000.0,
            },
            "risk_envelope": {
                "max_drawdown_pct": 0.0,
                "avg_loss_r": 0.0,
                "worst_loss_r": 0.0,
                "stress_worst_loss_r": 0.0,
                "joint_tail_budget_pct": 3.0,
                "max_exposure_pct": 20.0,
            },
            "lineage": {
                "strategy_source_sha": "e" * 64,
                "candidate_config_sha": candidate_sha,
                "data_sha": "f" * 64,
                "window_sha": "1" * 64,
                "source_manifest_sha": "2" * 64,
                "run_id": "fixture-core-run-1",
                "artifact": "fixture/core/new_sealed.json",
                "data_epoch": "fixture-core-epoch-1",
            },
            "proposal_state": "REQUEST_EVALUATION",
            "reason_codes": ["INDEPENDENT_CORE_FIXTURE", "NON_OVERLAPPING_DRAWDOWN_FIXTURE"],
            "authority": {
                "stage": "RESEARCH",
                "research_only": True,
                "promotion_authority": False,
                "execution_allowed": False,
                "order_authority": "BLOCKED",
                "protected_mutations": 0,
            },
            "metadata": {"fixture_only": True, "production_authority": False},
        }
    )
    evidence = {
        "stages": {"w1": "PASS", "w2": "PASS", "w3": "PASS", "new_sealed": "PASS"},
        "trade_quota_pass": True,
        "regime_coverage_pass": True,
        "dsr_pass": True,
        "bh_fdr_pass": True,
        "independent_edge_pass": True,
        "synthesis_eligible": False,
        "symbol_concentration_pct": 50.0,
        "window_concentration_pct": 40.0,
        "regime_concentration_pct": 45.0,
        "evidence_manifest_sha": "3" * 64,
    }
    classification = classify_candidate(proposal, evidence, classifier_policy())
    assert classification["classification"] == "CORE"
    return proposal, classification, core_ledger()


def sealed_material(
    material_id: str,
    proposal: dict,
    classification: dict,
    *,
    net: float,
    confidence: float,
    uncertainty: float,
    dd: float,
    joint: float,
    cost: float,
    capacity: float,
    incumbent: float,
) -> dict:
    core = {
        "material_id": material_id,
        "classification": classification["classification"],
        "candidate_sha": proposal["candidate_sha"],
        "proposal_sha": proposal["proposal_sha"],
        "classification_sha": classification["classification_sha"],
        "net_after_cost": net,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "dd_pct": dd,
        "joint_tail_dd_pct": joint,
        "cost_pct": cost,
        "capacity_score": capacity,
        "incumbent_weight": incumbent,
    }
    return {
        "material_id": material_id,
        "material_sealed": True,
        "material_seal_sha": canonical_sha(core),
        "net_after_cost": net,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "dd_pct": dd,
        "joint_tail_dd_pct": joint,
        "cost_pct": cost,
        "capacity_score": capacity,
        "incumbent_weight": incumbent,
    }


def package(proposal: dict, classification: dict, ledger: list[dict], material: dict) -> dict:
    result = {
        "schema_version": "strategy11.portfolio_candidate_package.v1",
        "proposal": proposal,
        "classification": classification,
        "source_ledger": ledger,
        "material": material,
        **SAFETY,
    }
    result["package_sha"] = canonical_sha(result)
    return result


def synthesis_package() -> dict:
    result = adapt_and_classify(adapter_fixture_input())
    return package(
        result["proposal"],
        result["classification"],
        result["source_ledger"],
        sealed_material(
            result["strategy_id"],
            result["proposal"],
            result["classification"],
            net=4.2,
            confidence=0.82,
            uncertainty=0.18,
            dd=2.4,
            joint=3.5,
            cost=0.09,
            capacity=0.90,
            incumbent=0.50,
        ),
    )


def core_package() -> dict:
    proposal, classification, ledger = core_candidate()
    return package(
        proposal,
        classification,
        ledger,
        sealed_material(
            proposal["strategy_id"],
            proposal,
            classification,
            net=5.17,
            confidence=0.90,
            uncertainty=0.10,
            dd=0.0,
            joint=1.0,
            cost=0.09,
            capacity=0.95,
            incumbent=0.50,
        ),
    )


def correlation_policy() -> dict:
    return {
        "policy_id": "FIXTURE_CORRELATION_POLICY_NOT_PRODUCTION_AUTHORITY",
        "max_cosine_similarity": 0.60,
        "max_abs_pnl_correlation": 0.90,
        "max_loss_concurrence": 0.80,
        "max_drawdown_concurrence": 0.90,
        "rolling_window": 3,
        "min_combination_size": 2,
        "max_combination_size": 2,
        "max_candidate_combinations": 5,
    }


def governor_policy(max_turnover: float = 2.0) -> dict:
    return {
        "policy_id": "FIXTURE_GOVERNOR_POLICY_NOT_PRODUCTION_AUTHORITY",
        "total_risk_budget": 1.0,
        "max_material_weight": 0.80,
        "min_material_weight": 0.20,
        "max_turnover": max_turnover,
    }


def fixture_input() -> dict:
    return {
        "schema_version": "strategy11.synthesis_portfolio_integration.input.v1",
        "candidate_packages": [synthesis_package(), core_package()],
        "correlation_policy": correlation_policy(),
        "governor_policy": governor_policy(),
        "authority": dict(SAFETY),
    }


def repack(candidate_package: dict) -> None:
    candidate_package.pop("package_sha", None)
    candidate_package["package_sha"] = canonical_sha(candidate_package)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = fixture_input()
    passed = integrate(payload)
    assert passed["state"] == "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION", passed
    assert passed["shadow_targets_ready"] is True
    assert passed["automatic_shadow_start"] is False
    assert passed["governor_result"]["status"] == "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS"
    assert len(passed["selected_members"]) == 2
    assert passed["correlation_analysis"]["blocked_pair_count"] == 0
    assert abs(sum(passed["governor_result"]["target_risk_weights"].values()) - 1.0) < 1e-9
    for key, expected in SAFETY.items():
        assert passed[key] == expected

    package_tamper = fixture_input()
    package_tamper["candidate_packages"][0]["material"]["net_after_cost"] = 99.0
    expect_failure("PACKAGE_SHA_MISMATCH", lambda: integrate(package_tamper))

    unsealed = fixture_input()
    unsealed["candidate_packages"][0]["material"]["material_sealed"] = False
    repack(unsealed["candidate_packages"][0])
    expect_failure("MATERIAL_NOT_SEALED", lambda: integrate(unsealed))

    correlated = fixture_input()
    synthesis_ledger = copy.deepcopy(correlated["candidate_packages"][0]["source_ledger"])
    remapped = []
    for index, row in enumerate(synthesis_ledger):
        remapped.append(
            source_trade(
                f"correlated-core-{index:02d}",
                row["timestamp"],
                row["net_r"],
                row["symbol"],
                row["regime"],
            )
        )
    correlated["candidate_packages"][1]["source_ledger"] = remapped
    repack(correlated["candidate_packages"][1])
    correlated_result = integrate(correlated)
    assert correlated_result["state"] == "HOLD_NO_COMPATIBLE_SYNTHESIS_PORTFOLIO"
    assert correlated_result["shadow_targets_ready"] is False
    assert correlated_result["correlation_analysis"]["blocked_pair_count"] == 1

    turnover = fixture_input()
    turnover["governor_policy"] = governor_policy(max_turnover=0.0)
    turnover_result = integrate(turnover)
    assert turnover_result["state"] == "HOLD_SYNTHESIS_PORTFOLIO_GOVERNOR"
    assert turnover_result["shadow_targets_ready"] is False
    assert "TURNOVER_LIMIT" in turnover_result["governor_result"]["blockers"]

    (OUT / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "pass.json").write_text(json.dumps(passed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_correlated.json").write_text(json.dumps(correlated_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "hold_turnover.json").write_text(json.dumps(turnover_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION_FIXTURE",
        "integration_sha": passed["integration_sha"],
        "shadow_targets_ready_fixture": True,
        "automatic_shadow_start": False,
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (OUT / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
