from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_adaptive_execution_contract_v1 import evaluate_preview
from backend.contracts.strategy11_human_governed_capital_contract_v1 import evaluate_human_governance
from backend.contracts.strategy11_market_digital_twin_resilience_v2 import evaluate_digital_twin_resilience_v2
from backend.contracts.strategy11_self_healing_operations_contract_v1 import evaluate_operations
from backend.tools import r7a4d_strategy11_source_bound_chain_fixture_v1 as champion_chain
from backend.tools.strategy11_adaptive_execution_fixture_v1 import base_request as adaptive_request
from backend.tools.strategy11_human_governed_capital_fixture_v1 import approval_for, base_request as human_request
from backend.tools.strategy11_market_digital_twin_fixture_v1 import build_package as risk_twin_package
from backend.tools.strategy11_market_digital_twin_resilience_fixture_v2 import resilient_package
from backend.tools.strategy11_self_healing_fixture_v1 import base_snapshot as self_healing_snapshot

VERSION = "STRATEGY11_HUMAN_GOVERNED_AUTONOMY_CHAIN_FIXTURE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "live_activation_allowed": False,
    "order_submission_allowed": False,
    "capital_allocation_execute_allowed": False,
    "external_manual_enable_required": True,
}


def stable_sha(value: Any) -> str:
    import hashlib

    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_champion_chain(out: Path) -> dict[str, Any]:
    previous_out = champion_chain.OUT
    champion_chain.OUT = out
    try:
        rc = champion_chain.main()
    finally:
        champion_chain.OUT = previous_out
    if rc != 0:
        raise RuntimeError(f"CHAMPION_CHAIN_EXIT:{rc}")
    summary = load_json(out / "summary.json")
    if summary.get("state") != "PASS_SOURCE_BOUND_CHAIN_E2E_FIXTURE":
        raise RuntimeError(f"CHAMPION_CHAIN_STATE:{summary.get('state')}")
    if not summary.get("chain_sha"):
        raise RuntimeError("CHAMPION_CHAIN_SHA_MISSING")
    if summary.get("runtime_bound") is not False:
        raise RuntimeError("CHAMPION_CHAIN_RUNTIME_BOUND")
    return summary


def human_request_with_upstream(
    *,
    policy_sha: str,
    adaptive: dict[str, Any],
    self_healing: dict[str, Any],
    champion: dict[str, Any],
    digital_twin: dict[str, Any],
) -> dict[str, Any]:
    request = human_request(policy_sha)
    request["upstream_gates"] = {
        "ADAPTIVE_EXECUTION": {
            "state": adaptive["state"],
            "evidence_sha": adaptive["decision_sha"],
        },
        "SELF_HEALING_OPERATIONS": {
            "state": self_healing["state"],
            "evidence_sha": self_healing["decision_sha"],
        },
        "CHAMPION_CHALLENGER": {
            "state": "PASS_CHAMPION_CHALLENGER_GATE",
            "evidence_sha": champion["chain_sha"],
        },
        "MARKET_DIGITAL_TWIN": {
            "state": digital_twin["state"],
            "capital_gate": digital_twin["capital_gate"],
            "evidence_sha": digital_twin["twin_result_sha"],
        },
    }
    request["source_binding"] = {
        "source_sha": stable_sha({
            "adaptive_source_sha": adaptive["lineage"]["source_sha"],
            "self_healing_source_sha": self_healing["lineage"]["source_sha"],
            "champion_chain_sha": champion["chain_sha"],
            "digital_twin_source_sha": digital_twin["lineage"]["source_sha"],
        }),
        "data_sha": digital_twin["lineage"]["data_sha"],
        "portfolio_sha": digital_twin["lineage"]["portfolio_sha"],
        "policy_sha": policy_sha,
        "run_id": "fixture-run-human-governed-autonomy-chain-001",
        "artifact_id": "fixture-artifact-human-governed-autonomy-chain-001",
    }
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adaptive-policy", type=Path, required=True)
    parser.add_argument("--self-healing-policy", type=Path, required=True)
    parser.add_argument("--digital-twin-policy", type=Path, required=True)
    parser.add_argument("--human-policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    adaptive_policy = load_json(args.adaptive_policy)
    self_policy = load_json(args.self_healing_policy)
    twin_policy = load_json(args.digital_twin_policy)
    human_policy = load_json(args.human_policy)
    args.out.mkdir(parents=True, exist_ok=True)

    adaptive = evaluate_preview(
        adaptive_request(str(adaptive_policy["policy_sha"])),
        adaptive_policy,
    )
    assert adaptive["state"] == "PASS_ADAPTIVE_EXECUTION_PREVIEW"
    assert adaptive["action"] == "hold"
    assert adaptive["blockers"] == []
    assert adaptive["metrics"]["next_step"] == "SHADOW_EXECUTION_SIMULATION_ONLY"

    self_healing = evaluate_operations(
        self_healing_snapshot(str(self_policy["policy_sha"])),
        self_policy,
    )
    assert self_healing["state"] == "PASS_SELF_HEALING_OBSERVER"
    assert self_healing["action"] == "hold"
    assert self_healing["blockers"] == []

    champion = run_champion_chain(args.out / "champion_challenger")
    assert champion["classification"] == {
        "alpha_combo": "CORE",
        "turtle_trend": "SYNTHESIS",
    }
    assert champion["source_history_verified"] is True
    assert all(state == "PASS_MODEL_RISK_GOVERNANCE" for state in champion["model_risk_states"])

    twin_pass = evaluate_digital_twin_resilience_v2(
        resilient_package(str(twin_policy["policy_sha"])),
        twin_policy,
    )
    assert twin_pass["state"] == "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE"
    assert twin_pass["capital_gate"] == "PASS_DIGITAL_TWIN_RISK_ENVELOPE"
    assert twin_pass["blocking_scenarios"] == []

    pass_request = human_request_with_upstream(
        policy_sha=str(human_policy["policy_sha"]),
        adaptive=adaptive,
        self_healing=self_healing,
        champion=champion,
        digital_twin=twin_pass,
    )
    pass_approval = approval_for(pass_request, str(human_policy["policy_sha"]))
    human_pass = evaluate_human_governance(pass_request, human_policy, pass_approval)
    assert human_pass["state"] == "PASS_HUMAN_GOVERNANCE_PREFLIGHT"
    assert human_pass["action"] == "hold"
    assert human_pass["blockers"] == []
    assert human_pass["live_activation_allowed"] is False
    assert human_pass["order_submission_allowed"] is False
    assert human_pass["external_manual_enable_required"] is True
    assert human_pass["metrics"]["preflight_pass_does_not_enable_live"] is True

    twin_risk = evaluate_digital_twin_resilience_v2(
        risk_twin_package(str(twin_policy["policy_sha"])),
        twin_policy,
    )
    assert twin_risk["capital_gate"] == "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    assert twin_risk["blocking_scenarios"]
    risk_request = human_request_with_upstream(
        policy_sha=str(human_policy["policy_sha"]),
        adaptive=adaptive,
        self_healing=self_healing,
        champion=champion,
        digital_twin=twin_risk,
    )
    risk_approval = approval_for(risk_request, str(human_policy["policy_sha"]))
    human_block = evaluate_human_governance(risk_request, human_policy, risk_approval)
    assert human_block["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert human_block["action"] == "block"
    assert human_block["blockers"] == ["DIGITAL_TWIN_CAPITAL_GATE:HOLD_DIGITAL_TWIN_RISK_EXPOSED"]

    stage_shas = {
        "adaptive_execution": adaptive["decision_sha"],
        "self_healing_operations": self_healing["decision_sha"],
        "champion_challenger": champion["chain_sha"],
        "market_digital_twin_pass": twin_pass["twin_result_sha"],
        "market_digital_twin_risk": twin_risk["twin_result_sha"],
        "human_governance_pass": human_pass["decision_sha"],
        "human_governance_block": human_block["decision_sha"],
    }
    summary = {
        "schema_version": "strategy11.human_governed_autonomy_chain_fixture.v1",
        "version": VERSION,
        "state": "PASS_HUMAN_GOVERNED_AUTONOMY_CHAIN_FIXTURE",
        "stage_count": 5,
        "stages": [
            "CHAMPION_CHALLENGER",
            "ADAPTIVE_EXECUTION",
            "SELF_HEALING_OPERATIONS",
            "MARKET_DIGITAL_TWIN_RESILIENCE_V2",
            "HUMAN_GOVERNED_CAPITAL",
        ],
        "normal_path": {
            "adaptive_state": adaptive["state"],
            "self_healing_state": self_healing["state"],
            "champion_state": champion["state"],
            "digital_twin_state": twin_pass["state"],
            "digital_twin_capital_gate": twin_pass["capital_gate"],
            "human_state": human_pass["state"],
            "human_action": human_pass["action"],
            "live_activation_allowed": human_pass["live_activation_allowed"],
            "external_manual_enable_required": human_pass["external_manual_enable_required"],
        },
        "risk_path": {
            "digital_twin_state": twin_risk["state"],
            "digital_twin_capital_gate": twin_risk["capital_gate"],
            "blocking_scenarios": twin_risk["blocking_scenarios"],
            "human_state": human_block["state"],
            "human_action": human_block["action"],
            "human_blockers": human_block["blockers"],
        },
        "stage_shas": stage_shas,
        "fixture_only": True,
        "production_threshold_authority": False,
        "real_w1_candidate_consumed": False,
        "next": "REAL_W1_W2_W3_NEW_SEALED_THEN_SHADOW_PAPER_CANARY",
        **SAFETY,
    }
    summary["chain_sha"] = stable_sha(summary)

    atomic_json(args.out / "summary.json", summary)
    atomic_json(args.out / "adaptive_execution.json", adaptive)
    atomic_json(args.out / "self_healing_operations.json", self_healing)
    atomic_json(args.out / "digital_twin_pass.json", twin_pass)
    atomic_json(args.out / "digital_twin_risk.json", twin_risk)
    atomic_json(args.out / "human_governance_pass.json", human_pass)
    atomic_json(args.out / "human_governance_block.json", human_block)
    print(summary["state"], summary["stage_count"], human_pass["state"], human_block["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
