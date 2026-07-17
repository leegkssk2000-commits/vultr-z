from __future__ import annotations

from dataclasses import replace

from policy.zbot_dryrun_transport import contains_secret_material
from q4r3_r62_fixture import budget_policy, evaluate, observer


def test_exhausted_budget_holds() -> None:
    result = evaluate(budget_value=budget_policy(daily_token_limit=1000))
    assert result.state == "HOLD"
    assert "DAILY_TOKEN_BUDGET_EXCEEDED" in result.reason_codes
    assert result.network_call_count == 0


def test_duplicate_idempotency_key_holds() -> None:
    baseline = evaluate()
    key = baseline.route_results[0].idempotency_key
    result = evaluate(prior_keys=(key,))
    assert result.state == "HOLD"
    assert "IDEMPOTENCY_DUPLICATE" in result.reason_codes
    assert result.network_call_count == 0


def test_observer_authority_violation_holds_before_compile() -> None:
    unsafe = replace(observer(), provider_invocation_enabled=True)
    result = evaluate(observer_value=unsafe)
    assert result.state == "HOLD"
    assert "R61_OBSERVER_AUTHORITY_BOUNDARY_INVALID" in result.reason_codes
    assert result.route_count == 0


def test_duplicate_route_or_request_holds() -> None:
    source = observer()
    duplicated = replace(source, route_plans=(source.route_plans[0], source.route_plans[0]))
    result = evaluate(observer_value=duplicated)
    assert result.state == "HOLD"
    assert "DRYRUN_DUPLICATE_ROUTE_OR_REQUEST" in result.reason_codes


def test_unknown_provider_holds() -> None:
    source = observer()
    first = replace(
        source.route_plans[0],
        required_providers=("openai", "unknown"),
        provider_request_count=2,
    )
    unsafe = replace(source, route_plans=(first, *source.route_plans[1:]))
    result = evaluate(observer_value=unsafe)
    assert result.state == "HOLD"
    assert result.network_call_count == 0


def test_secret_material_detector_blocks_auth_and_keys() -> None:
    assert contains_secret_material({"authorization": "Bearer abc"}) is True
    assert contains_secret_material({"api_key": "abc"}) is True
    assert contains_secret_material("sk-live-example") is True
    assert contains_secret_material({"headers": {"content-type": "application/json"}}) is False


def test_secret_material_detector_does_not_flag_risk_prompt_hash() -> None:
    benign = "sha256:risk-review-r53-1"
    assert contains_secret_material(benign) is False
    assert contains_secret_material({"prompt_template_hash": benign}) is False
