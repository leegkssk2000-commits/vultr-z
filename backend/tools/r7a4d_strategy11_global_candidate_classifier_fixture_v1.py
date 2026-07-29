from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.tools.r7a4d_strategy11_strategy_proposal_contract_fixture_v1 import valid_fixture

OUT = Path("artifacts/strategy11_global_candidate_classifier_v1")

POLICY = {
    "policy_id": "FIXTURE_ONLY_NOT_PRODUCTION_THRESHOLD_AUTHORITY",
    "min_trades": 30,
    "min_positive_window_ratio": 0.70,
    "min_retention_pct": 80.0,
    "min_profit_factor": 1.20,
    "min_net_pct": 0.0,
    "max_drawdown_pct": 10.0,
    "min_worst_loss_r": -0.75,
    "min_stress_worst_loss_r": -0.75,
    "min_confidence_core": 0.65,
    "max_uncertainty_core": 0.35,
    "max_symbol_concentration_core_pct": 60.0,
    "max_window_concentration_core_pct": 60.0,
    "max_regime_concentration_core_pct": 70.0,
    "max_concentration_synthesis_pct": 85.0,
}


def evidence(**overrides: object) -> dict:
    value = {
        "stages": {"w1": "PASS", "w2": "PASS", "w3": "PASS", "new_sealed": "PASS"},
        "trade_quota_pass": True,
        "regime_coverage_pass": True,
        "dsr_pass": True,
        "bh_fdr_pass": True,
        "independent_edge_pass": True,
        "synthesis_eligible": False,
        "symbol_concentration_pct": 40.0,
        "window_concentration_pct": 35.0,
        "regime_concentration_pct": 55.0,
        "evidence_manifest_sha": "e" * 64,
    }
    value.update(overrides)
    return value


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    base = seal_proposal(valid_fixture())

    core = classify_candidate(base, evidence(), POLICY)
    assert core["classification"] == "CORE", core

    synthesis_evidence = evidence(
        independent_edge_pass=False,
        synthesis_eligible=True,
        symbol_concentration_pct=75.0,
    )
    synthesis = classify_candidate(base, synthesis_evidence, POLICY)
    assert synthesis["classification"] == "SYNTHESIS", synthesis

    hold_evidence = evidence(stages={"w1": "PASS", "w2": "PASS", "w3": "NOT_RUN", "new_sealed": "NOT_RUN"})
    hold = classify_candidate(base, hold_evidence, POLICY)
    assert hold["classification"] == "HOLD", hold
    assert "all_nonoverlap_stages" in hold["failed_gates"]

    rejected_payload = copy.deepcopy(valid_fixture())
    rejected_payload["risk_envelope"]["stress_worst_loss_r"] = -1.05
    rejected = classify_candidate(seal_proposal(rejected_payload), evidence(), POLICY)
    assert rejected["classification"] == "REJECT", rejected
    assert "risk_stress_worst" in rejected["failed_gates"]

    rows = {"CORE": core, "SYNTHESIS": synthesis, "HOLD": hold, "REJECT": rejected}
    assert len({row["classification_sha"] for row in rows.values()}) == 4
    assert all(row["single_score_used"] is False for row in rows.values())
    assert all(row["pareto_first"] is True for row in rows.values())

    for name, row in rows.items():
        (OUT / f"{name.lower()}.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "state": "PASS_GLOBAL_CANDIDATE_CLASSIFIER",
        "classifications": {name: row["classification_sha"] for name, row in rows.items()},
        "fixture_policy_id": POLICY["policy_id"],
        "production_threshold_authority": False,
        "hard_gate_priority": True,
        "pareto_first": True,
        "single_score_used": False,
        "next": "ENSEMBLE_CORRELATION_ANALYZER",
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
