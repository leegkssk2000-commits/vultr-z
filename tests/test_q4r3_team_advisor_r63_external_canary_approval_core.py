from __future__ import annotations

import json
from pathlib import Path

from policy.zbot_external_canary_approval import evaluate_external_canary_approval
from tests.q4r3_r63_fixture import candidate, policy

ROOT = Path(__file__).parents[1]


def test_valid_candidate_is_approval_eligible() -> None:
    result = evaluate_external_canary_approval(candidate(), now_ms=12000, policy=policy())
    assert result.state == "APPROVAL_ELIGIBLE"
    assert result.approval_eligible is True
    assert result.reason_codes == ()
    assert result.scope_valid is True
    assert result.budget_valid is True
    assert result.credential_refs_valid is True
    assert result.evidence_lineage_valid is True


def test_gate_never_enables_external_authority() -> None:
    result = evaluate_external_canary_approval(candidate(), now_ms=12000, policy=policy())
    assert result.action == "hold"
    assert result.provider_invocation_enabled is False
    assert result.network_call_enabled is False
    assert result.credential_resolution_enabled is False
    assert result.execution_authority == "none"
    assert result.order_authority == "none"


def test_nonce_replay_is_blocked() -> None:
    current = candidate()
    result = evaluate_external_canary_approval(
        current,
        now_ms=12000,
        policy=policy(),
        prior_nonces=(current.approval_nonce,),
    )
    assert result.state == "HOLD"
    assert result.replay_blocked is True
    assert "APPROVAL_NONCE_REPLAY" in result.reason_codes


def test_contract_keeps_external_canary_unapproved() -> None:
    contract = json.loads(
        (ROOT / "config/q4r3_zbot_external_canary_approval_gate_v1.json").read_text(encoding="utf-8")
    )
    authority = contract["authority"]
    assert authority["external_canary_approved"] is False
    assert authority["provider_invocation_enabled"] is False
    assert authority["network_call_enabled"] is False
    assert authority["credential_resolution_enabled"] is False
    assert contract["expected"]["network_call_count"] == 0
    assert contract["expected"]["credential_resolution_count"] == 0
