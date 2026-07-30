from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha
from backend.research.strategy11_synthesis_portfolio_integration_v1 import (
    SynthesisPortfolioIntegrationError,
    integrate,
)
from backend.tools.r7a4d_strategy11_synthesis_classifier_adapter_fixture_v1 import classifier_policy
from backend.tools.r7a4d_strategy11_synthesis_portfolio_integration_fixture_v1_1 import (
    correlation_policy,
    fixture_input,
    governor_policy,
    package,
    sealed_material,
    source_trade,
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


def reseal_material(candidate_package: dict) -> None:
    proposal = candidate_package["proposal"]
    classification = candidate_package["classification"]
    material = candidate_package["material"]
    core = {
        "material_id": material["material_id"],
        "classification": classification["classification"],
        "candidate_sha": proposal["candidate_sha"],
        "proposal_sha": proposal["proposal_sha"],
        "classification_sha": classification["classification_sha"],
        "net_after_cost": material["net_after_cost"],
        "confidence": material["confidence"],
        "uncertainty": material["uncertainty"],
        "dd_pct": material["dd_pct"],
        "joint_tail_dd_pct": material["joint_tail_dd_pct"],
        "cost_pct": material["cost_pct"],
        "capacity_score": material["capacity_score"],
        "incumbent_weight": material["incumbent_weight"],
    }
    material["material_seal_sha"] = canonical_sha(core)
    candidate_package.pop("package_sha", None)
    candidate_package["package_sha"] = canonical_sha(candidate_package)


def second_core_package() -> dict:
    strategy_id = "core.breakout.fixture"
    candidate_sha = "7" * 64
    proposal = seal_proposal(
        {
            "schema_version": "strategy11.strategy_proposal.v1",
            "proposal_id": f"proposal.{strategy_id}",
            "strategy_id": strategy_id,
            "candidate_sha": candidate_sha,
            "producer": {"team_lane": "GAMMA", "role": "RESEARCH", "independent_proposal": True},
            "market": {
                "symbols": ["LINKUSDT"],
                "timeframe": "15m",
                "side": "LONG",
                "regime": "UPTREND",
                "session": "ALL",
            },
            "edge": {
                "trades": 16,
                "win_rate_pct": 100.0,
                "net_pct": 6.0,
                "profit_factor": 10.0,
                "payoff": 2.2,
                "positive_windows": 3,
                "total_windows": 3,
                "retention_pct": 90.0,
            },
            "confidence": {"score": 0.92, "uncertainty": 0.08, "sample_quality": "HIGH", "oos_windows": 3},
            "cost_envelope": {
                "fee_bps": 5.0,
                "slippage_bps": 4.0,
                "funding_8h_pct": 0.01,
                "latency_ms": 200.0,
                "stress_multiplier": 2.0,
                "capacity_notional_usdt": 6500.0,
            },
            "risk_envelope": {
                "max_drawdown_pct": 0.0,
                "avg_loss_r": 0.0,
                "worst_loss_r": 0.0,
                "stress_worst_loss_r": 0.0,
                "joint_tail_budget_pct": 2.5,
                "max_exposure_pct": 20.0,
            },
            "lineage": {
                "strategy_source_sha": "8" * 64,
                "candidate_config_sha": candidate_sha,
                "data_sha": "9" * 64,
                "window_sha": "a" * 64,
                "source_manifest_sha": "b" * 64,
                "run_id": "fixture-second-core-run",
                "artifact": "fixture/second-core/new-sealed.json",
                "data_epoch": "fixture-second-core-epoch",
            },
            "proposal_state": "REQUEST_EVALUATION",
            "reason_codes": ["SECOND_INDEPENDENT_CORE_FIXTURE"],
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
        "symbol_concentration_pct": 45.0,
        "window_concentration_pct": 40.0,
        "regime_concentration_pct": 45.0,
        "evidence_manifest_sha": "c" * 64,
    }
    classification = classify_candidate(proposal, evidence, classifier_policy())
    assert classification["classification"] == "CORE"
    values = [0.50, 0.20, 0.55, 0.18, 0.60, 0.30, 0.15, 0.50, 0.35, 0.15, 0.45, 0.25, 0.12, 0.55, 0.30, 0.10]
    ledger = [
        source_trade(
            f"second-core-{index:02d}",
            f"2026-10-{index + 1:02d}T00:00:00Z",
            value,
            "LINKUSDT",
            "UPTREND",
        )
        for index, value in enumerate(values)
    ]
    return package(
        proposal,
        classification,
        ledger,
        sealed_material(
            strategy_id,
            proposal,
            classification,
            net=6.0,
            confidence=0.92,
            uncertainty=0.08,
            dd=0.0,
            joint=0.8,
            cost=0.09,
            capacity=0.96,
            incumbent=0.0,
        ),
    )


def main() -> int:
    duplicate = fixture_input()
    duplicate["candidate_packages"][1]["material"]["material_id"] = duplicate["candidate_packages"][0]["material"]["material_id"]
    reseal_material(duplicate["candidate_packages"][1])
    expect_failure("DUPLICATE_MATERIAL_ID", lambda: integrate(duplicate))

    three = fixture_input()
    three["candidate_packages"].append(second_core_package())
    three["correlation_policy"] = correlation_policy()
    three["correlation_policy"]["max_candidate_combinations"] = 10
    three["governor_policy"] = governor_policy(max_turnover=2.0)
    result = integrate(three)
    assert result["state"] == "PASS_SYNTHESIS_PORTFOLIO_INTEGRATION", result
    assert result["selected_synthesis_members"], result
    synthesis_ids = {
        row["proposal"]["strategy_id"]
        for row in three["candidate_packages"]
        if row["classification"]["classification"] == "SYNTHESIS"
    }
    assert synthesis_ids.intersection(result["selected_members"])
    assert result["governor_result"]["status"] == "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS"

    (OUT / "review_regression.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = {
        "state": "PASS_SYNTHESIS_PORTFOLIO_REVIEW_REGRESSION",
        "integration_sha": result["integration_sha"],
        "selected_synthesis_members": result["selected_synthesis_members"],
        "duplicate_material_id_rejected": True,
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (OUT / "review_status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
