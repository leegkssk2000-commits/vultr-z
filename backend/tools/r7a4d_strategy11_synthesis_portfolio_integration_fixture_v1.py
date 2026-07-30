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


def trade(index: int, net_r: float, regime: str, month: int = 9) -> dict:
    core = {
        "trade_id": f"core-fixture-{month}-{index:02d}",
        "timestamp": f"2026-{month:02d}-{index + 1:02d}T00:00:00Z",
        "net_r": net_r,
        "symbol": "SOLUSDT" if index % 2 == 0 else "XRPUSDT",
        "regime": regime,
    }
    return {**core, "source_row_sha": canonical_sha(core)}


def core_candidate(*, candidate_sha: str = "d" * 64, strategy_id: str = "core.turtle.fixture") -> tuple[dict, dict, list[dict]]:
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
                "win_rate_pct": 56.25,
                "net_pct": 3.5,
                "profit_factor": 1.42,
                "payoff": 1.25,
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
                "max_drawdown_pct": 2.0,
                "avg_loss_r": -0.42,
                "worst_loss_r": -0.68,
                "stress_worst_loss_r": -0.74,
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
            "reason_codes": ["INDEPENDENT_CORE_FIXTURE"],
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
    ledger = [
        trade(0, 0.35, "UPTREND"), trade(1, -0.25, "RANGE"), trade(2, 0.50, "UPTREND"),
        trade(3, -0.20, "HIGH_VOL"), trade(4, 0.55, "UPTREND"), trade(5, 0.25, "RANGE"),
        trade(6, -0.15, "HIGH_VOL"), trade(7, 0.45, "UPTREND"), trade(8, 0.30, "RANGE"),
        trade(9, -0.20, "HIGH_VOL"), trade(10, 0.40, "UPTREND"), trade(11, 0.20, "RANGE"),
        trade(12, -0.15, "HIGH_VOL"), trade(13, 0.50, "UPTREND"), trade(14, 0.25, "RANGE"),
        trade(15, -0.10, "HIGH_VOL"),
    ]
    return proposal, classification, ledger


def material(
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


def package(proposal: dict, classification: dict, ledger: list[dict], row_material: dict) -> dict:
    value = {
        "schema_version": "strategy11.portfolio_candidate_package.v1",
        "proposal": proposal,
        "classification": classification,
        "source_ledger": ledger,
        "material": row_material,
        **SAFETY,
    }
    value["package_sha"] = canonical_sha(value)
    return value


def synthesis_package() -> dict:
    result = adapt_and_classify(adapter_fixture_input())
    return package(
        result["proposal"],
        result["classification"],
        result["source_ledger"],
        material(
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
        material(
            proposal["strategy_id"],
            proposal,
            classification,
            net=3.5,
            confidence=0.90,
            uncertainty=0.10,
            dd=2.0,
            joint=3.0,
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = fixture_input()
    passed = integrate(payload)
    assert passed["state"] == "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION"
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
    unsealed_package = unsealed["candidate_packages"][0]
    unsealed_package["material"]["material_sealed"] = False
    unsealed_package.pop("package_sha", None)
    unsealed_package["package_sha"] = canonical_sha(unsealed_package)
    expect_failure("MATERIAL_NOT_SEALED", lambda: integrate(unsealed))

    correlated = fixture_input()
    synthesis_ledger = copy.deepcopy(correlated["candidate_packages"][0]["source_ledger"])
    core_pkg = correlated["candidate_packages"][1]
    remapped: list[dict] = []
    for index, row in enumerate(synthesis_ledger):
        core = {
            "trade_id": f"correlated-core-{index:02d}",
            "timestamp": row["timestamp"],
            "net_r": row["net_r"],
            "symbol": row["symbol"],
            "regime": row["regime"],
        }
        remapped.append({**core, "source_row_sha": canonical_sha(core)})
    core_pkg["source_ledger"] = remapped
    core_pkg.pop("package_sha", None)
    core_pkg["package_sha"] = canonical_sha(core_pkg)
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
