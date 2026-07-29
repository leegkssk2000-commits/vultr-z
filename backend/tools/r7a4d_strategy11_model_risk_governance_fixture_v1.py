from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_model_risk_governance_v1 import evaluate_model_risk

OUT = Path("artifacts/strategy11_model_risk_governance_v1")
POLICY = {
    "policy_id": "FIXTURE_ONLY_NOT_PRODUCTION_THRESHOLD_AUTHORITY",
    "drift_psi_warn": 0.10,
    "drift_psi_rollback": 0.25,
    "calibration_error_warn": 0.10,
    "calibration_error_rollback": 0.20,
    "error_budget_warn_ratio": 0.70,
    "error_budget_block_ratio": 1.00,
    "max_shadow_dd_pct": 5.0,
    "max_cost_overrun_pct": 20.0,
    "max_correlation_breach_count": 0,
    "max_consecutive_failures": 3,
}


def sha(char: str) -> str:
    return char * 64


def snapshot() -> dict:
    return {
        "candidate_id": "alpha_combo.TIME54",
        "candidate_sha": sha("a"),
        "proposal_sha": sha("b"),
        "classification_sha": sha("c"),
        "correlation_analysis_sha": sha("d"),
        "portfolio_governor_sha": sha("e"),
        "attribution_projection_sha": sha("f"),
        "role_boundary_sha": sha("1"),
        "source_manifest_sha": sha("2"),
        "lineage_match": True,
        "stale": False,
        "private_field_violation": False,
        "drift_psi": 0.05,
        "calibration_error": 0.05,
        "calibration_sample_count": 100,
        "error_budget_used": 2,
        "error_budget_limit": 10,
        "shadow_dd_pct": 2.0,
        "cost_overrun_pct": 5.0,
        "correlation_breach_count": 0,
        "consecutive_failures": 0,
        "incumbent_available": True,
        "shadow_only": True,
        "authority": {
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pass_case = evaluate_model_risk(snapshot(), POLICY)
    assert pass_case["state"] == "PASS_MODEL_RISK_GOVERNANCE", pass_case
    assert pass_case["requested_action"] == "hold"

    hold_input = copy.deepcopy(snapshot())
    hold_input["drift_psi"] = 0.15
    hold_input["error_budget_used"] = 8
    hold_case = evaluate_model_risk(hold_input, POLICY)
    assert hold_case["state"] == "HOLD_MODEL_RISK_REVIEW", hold_case
    assert hold_case["requested_action"] == "hold"
    assert "DRIFT_WARNING" in hold_case["reason_codes"]
    assert "ERROR_BUDGET_WARNING" in hold_case["reason_codes"]

    rollback_input = copy.deepcopy(snapshot())
    rollback_input["drift_psi"] = 0.30
    rollback_input["shadow_dd_pct"] = 6.0
    rollback_input["correlation_breach_count"] = 1
    rollback_case = evaluate_model_risk(rollback_input, POLICY)
    assert rollback_case["state"] == "ROLLBACK_MODEL_RISK", rollback_case
    assert rollback_case["requested_action"] == "rollback"
    assert rollback_case["rollback_target"] == "PREVIOUS_VERIFIED_INCUMBENT"

    block_input = copy.deepcopy(snapshot())
    block_input["lineage_match"] = False
    block_input["error_budget_used"] = 10
    block_case = evaluate_model_risk(block_input, POLICY)
    assert block_case["state"] == "BLOCK_MODEL_RISK", block_case
    assert block_case["requested_action"] == "block"
    assert "LINEAGE_MISMATCH" in block_case["reason_codes"]
    assert "ERROR_BUDGET_EXHAUSTED" in block_case["reason_codes"]

    rows = {
        "PASS": pass_case,
        "HOLD": hold_case,
        "ROLLBACK": rollback_case,
        "BLOCK": block_case,
    }
    assert len({row["governance_sha"] for row in rows.values()}) == 4
    assert all(row["automatic_order_action"] is False for row in rows.values())
    assert all(row["runtime_mutation_allowed"] is False for row in rows.values())
    assert all(row["shadow_only"] is True for row in rows.values())

    for name, row in rows.items():
        (OUT / f"{name.lower()}.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "state": "PASS_MODEL_RISK_GOVERNANCE_FIXTURES",
        "states": {name: row["state"] for name, row in rows.items()},
        "governance_sha": {name: row["governance_sha"] for name, row in rows.items()},
        "drift_gate": True,
        "calibration_gate": True,
        "error_budget_gate": True,
        "rollback_gate": True,
        "shadow_gate": True,
        "lineage_block_gate": True,
        "production_threshold_authority": False,
        "runtime_bound": False,
        "shadow_only": True,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "next": "INTERNAL_SYNERGY_CHAIN_COMPLETE_WAIT_W1_W2_W3_AND_NEW_SEALED",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
