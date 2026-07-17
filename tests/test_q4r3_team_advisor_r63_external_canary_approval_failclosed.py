from __future__ import annotations

from policy.zbot_external_canary_approval import evaluate_external_canary_approval
from tests.q4r3_r63_fixture import candidate, policy


def hold(**changes):
    return evaluate_external_canary_approval(candidate(**changes), now_ms=12000, policy=policy())


def test_expired_approval_holds() -> None:
    result = evaluate_external_canary_approval(candidate(expires_at_ms=11001), now_ms=12000, policy=policy())
    assert result.state == "HOLD"
    assert "APPROVAL_EXPIRED" in result.reason_codes


def test_future_approval_holds() -> None:
    result = evaluate_external_canary_approval(candidate(approved_at_ms=13000), now_ms=12000, policy=policy())
    assert result.state == "HOLD"
    assert "APPROVAL_NOT_ACTIVE" in result.reason_codes


def test_non_human_approver_holds() -> None:
    result = hold(approved_by="service:zbot")
    assert "HUMAN_APPROVER_INVALID" in result.reason_codes


def test_unknown_provider_holds() -> None:
    result = hold(providers=("openai", "unknown"))
    assert "PROVIDER_SCOPE_FORBIDDEN" in result.reason_codes


def test_forbidden_route_holds() -> None:
    result = hold(routes=("optimization_candidate_review",))
    assert "ROUTE_SCOPE_FORBIDDEN" in result.reason_codes


def test_call_limit_holds() -> None:
    result = hold(max_calls_total=3)
    assert "TOTAL_CALL_LIMIT_EXCEEDED" in result.reason_codes


def test_cost_limit_holds() -> None:
    result = hold(max_cost_micro_usd=20001)
    assert "COST_LIMIT_EXCEEDED" in result.reason_codes


def test_missing_credential_ref_holds() -> None:
    result = hold(credential_refs=(("openai", "secret-ref:zbot/openai"),))
    assert "CREDENTIAL_REFERENCE_INVALID" in result.reason_codes


def test_embedded_secret_holds() -> None:
    result = hold(credential_refs=(("openai", "sk-abcdefgh12345678"), ("gemini", "secret-ref:zbot/gemini")))
    assert "SECRET_MATERIAL_PRESENT" in result.reason_codes


def test_invalid_evidence_digest_holds() -> None:
    result = hold(dryrun_evidence_sha256="a" * 64)
    assert "DRYRUN_EVIDENCE_DIGEST_INVALID" in result.reason_codes


def test_missing_kill_switch_ref_holds() -> None:
    result = hold(kill_switch_ref="missing")
    assert "KILL_SWITCH_REF_INVALID" in result.reason_codes


def test_missing_rollback_ref_holds() -> None:
    result = hold(rollback_ref="missing")
    assert "ROLLBACK_REF_INVALID" in result.reason_codes
