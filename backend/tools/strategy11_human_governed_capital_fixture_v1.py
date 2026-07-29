from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_human_governed_capital_contract_v1 import (
    HumanGovernanceContractError,
    evaluate_human_governance,
    stable_sha,
)

VERSION = "STRATEGY11_HUMAN_GOVERNED_CAPITAL_FIXTURE_V1"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def base_request(policy_sha: str) -> dict[str, Any]:
    return {
        "now_ms": 10000,
        "requested_stage": "LIVE_READINESS",
        "completed_stages": [],
        "exchange": "BINGX",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "requested_capital_usdt": 500.0,
        "requested_leverage": 10.0,
        "requested_exposure_pct": 10.0,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
        "kill_switch_engaged": False,
        "emergency_stop_available": True,
        "upstream_gates": {
            "ADAPTIVE_EXECUTION": {
                "state": "PASS_ADAPTIVE_EXECUTION_PREVIEW",
                "evidence_sha": "1" * 64,
            },
            "SELF_HEALING_OPERATIONS": {
                "state": "PASS_SELF_HEALING_OBSERVER",
                "evidence_sha": "2" * 64,
            },
            "CHAMPION_CHALLENGER": {
                "state": "PASS_CHAMPION_CHALLENGER_GATE",
                "evidence_sha": "3" * 64,
            },
            "MARKET_DIGITAL_TWIN": {
                "state": "PASS_MARKET_DIGITAL_TWIN_SCENARIO_COVERAGE",
                "capital_gate": "PASS_DIGITAL_TWIN_RISK_ENVELOPE",
                "evidence_sha": "4" * 64,
            },
        },
        "source_binding": {
            "source_sha": "a" * 64,
            "data_sha": "b" * 64,
            "portfolio_sha": "c" * 64,
            "policy_sha": policy_sha,
            "run_id": "fixture-run-human-governed-001",
            "artifact_id": "fixture-artifact-human-governed-001",
        },
    }


def approval_for(request: dict[str, Any], policy_sha: str, approver_type: str = "HUMAN_USER") -> dict[str, Any]:
    row = {
        "approval_id": "human-approval-001",
        "approver_type": approver_type,
        "approved_by": "user:leegkssk2000-commits",
        "issued_at_ms": 1000,
        "expires_at_ms": 50000,
        "stage": request["requested_stage"],
        "policy_sha": policy_sha,
        "revoked": False,
        "max_capital_usdt": 1000.0,
        "max_leverage": 20.0,
        "max_exposure_pct": 25.0,
        "allowed_exchanges": ["BINGX"],
        "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    }
    row["approval_sha"] = stable_sha(row)
    return row


def expect_error(name: str, fn: Any, prefix: str) -> dict[str, Any]:
    try:
        fn()
    except HumanGovernanceContractError as exc:
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
    request = base_request(str(policy["policy_sha"]))
    approval = approval_for(request, str(policy["policy_sha"]))

    missing = evaluate_human_governance(request, policy, None)
    assert missing["state"] == "HOLD_HUMAN_GOVERNANCE_PREFLIGHT"
    assert missing["blockers"] == ["EXPLICIT_USER_APPROVAL_MISSING"]

    valid = evaluate_human_governance(request, policy, approval)
    assert valid["state"] == "PASS_HUMAN_GOVERNANCE_PREFLIGHT"
    assert valid["action"] == "hold"
    assert valid["blockers"] == []
    assert valid["live_activation_allowed"] is False
    assert valid["external_manual_enable_required"] is True
    assert valid["metrics"]["preflight_pass_does_not_enable_live"] is True

    ai_approval = approval_for(request, str(policy["policy_sha"]), approver_type="AI_MODEL")
    ai_block = evaluate_human_governance(request, policy, ai_approval)
    assert ai_block["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert ai_block["blockers"] == ["APPROVER_TYPE_NOT_HUMAN"]

    expired_approval = approval_for(request, str(policy["policy_sha"]))
    expired_approval["issued_at_ms"] = 100
    expired_approval["expires_at_ms"] = 9000
    expired_approval["approval_sha"] = stable_sha({key: value for key, value in expired_approval.items() if key != "approval_sha"})
    expired = evaluate_human_governance(request, policy, expired_approval)
    assert expired["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert expired["blockers"] == ["APPROVAL_EXPIRED_OR_INVALID_TIME"]

    kill_request = deepcopy(request)
    kill_request["kill_switch_engaged"] = True
    kill_block = evaluate_human_governance(kill_request, policy, approval)
    assert kill_block["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert kill_block["blockers"] == ["KILL_SWITCH_ENGAGED"]

    twin_request = deepcopy(request)
    twin_request["upstream_gates"]["MARKET_DIGITAL_TWIN"]["capital_gate"] = "HOLD_DIGITAL_TWIN_RISK_EXPOSED"
    twin_block = evaluate_human_governance(twin_request, policy, approval)
    assert twin_block["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert twin_block["blockers"] == ["DIGITAL_TWIN_CAPITAL_GATE:HOLD_DIGITAL_TWIN_RISK_EXPOSED"]

    capital_request = deepcopy(request)
    capital_request["requested_capital_usdt"] = 5000.0
    capital_block = evaluate_human_governance(capital_request, policy, approval)
    assert capital_block["state"] == "BLOCK_HUMAN_GOVERNED_CAPITAL"
    assert "CAPITAL_LIMIT" in capital_block["blockers"]

    sequence_request = deepcopy(request)
    sequence_request["requested_stage"] = "CORE_SUBSET"
    sequence_request["completed_stages"] = ["LIVE_READINESS"]
    sequence_approval = approval_for(sequence_request, str(policy["policy_sha"]))
    sequence_hold = evaluate_human_governance(sequence_request, policy, sequence_approval)
    assert sequence_hold["state"] == "HOLD_HUMAN_GOVERNANCE_PREFLIGHT"
    assert sequence_hold["blockers"] == ["CANARY_SEQUENCE_MISMATCH"]

    tampered_approval = deepcopy(approval)
    tampered_approval["max_capital_usdt"] = 999999.0
    approval_error = expect_error(
        "APPROVAL_SHA_TAMPER",
        lambda: evaluate_human_governance(request, policy, tampered_approval),
        "APPROVAL_SHA_MISMATCH",
    )

    tampered_policy = deepcopy(policy)
    tampered_policy["max_leverage"] = 100.0
    policy_error = expect_error(
        "POLICY_SHA_TAMPER",
        lambda: evaluate_human_governance(request, tampered_policy, approval),
        "POLICY_SHA_MISMATCH",
    )

    summary = {
        "schema_version": "strategy11.human_governed_capital_fixture.v1",
        "version": VERSION,
        "state": "PASS_HUMAN_GOVERNED_CAPITAL_FIXTURES",
        "case_count": 10,
        "missing_approval_hold": missing,
        "valid_human_preflight": valid,
        "ai_approval_block": ai_block,
        "expired_approval_block": expired,
        "kill_switch_block": kill_block,
        "digital_twin_risk_block": twin_block,
        "capital_limit_block": capital_block,
        "canary_sequence_hold": sequence_hold,
        "negative_cases": [approval_error, policy_error],
        "runtime_activation_allowed": False,
        "live_activation_allowed": False,
        "order_submission_allowed": False,
        "capital_allocation_execute_allowed": False,
        "external_manual_enable_required": True,
        "ai_approval_authority": False,
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
    atomic_json(args.out / "valid_human_preflight.json", valid)
    atomic_json(args.out / "ai_approval_block.json", ai_block)
    atomic_json(args.out / "digital_twin_risk_block.json", twin_block)
    print(summary["state"], summary["case_count"], valid["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
