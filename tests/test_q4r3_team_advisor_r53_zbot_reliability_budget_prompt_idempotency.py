from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


zbot = load("zbot_r53_test", "canonical/zbot.py")
prompt = load("zbot_prompt_r53_test", "policy/zbot_prompt.py")
budget = load("zbot_budget_r53_test", "policy/zbot_budget.py")
reliability = load("zbot_reliability_r53_test", "policy/zbot_reliability.py")
idempotency = load("zbot_idempotency_r53_test", "policy/zbot_idempotency.py")


def decision():
    evidence = zbot.EvidenceItem(
        evidence_id="evidence.r53.001",
        source_ref="cf:zbot:r53",
        available_at_ms=9900,
        schema_version="r53-test",
    )
    request = zbot.ZBotTaskRequest(
        request_id="zbot.r53.001",
        task_kind="risk_review",
        decision_ts_ms=10000,
        epoch_id="shadow.r53.001",
        evidence=(evidence,),
        payload={"symbol": "BTCUSDT", "mode": "review"},
        requested_action="hold",
    )
    return zbot.build_provider_requests(request)


def budget_policy(**changes):
    values = {
        "daily_token_limit": 10000,
        "daily_cost_micro_usd_limit": 10000,
        "per_request_token_limit": 3000,
        "max_input_tokens": 2000,
        "max_output_tokens": 1000,
        "budget_ref": "sheets:zbot:budget",
    }
    values.update(changes)
    return budget.BudgetPolicy(**values)


def usage():
    return {
        "openai": budget.UsageSnapshot("openai", 100, 50, 100),
        "gemini": budget.UsageSnapshot("gemini", 100, 50, 100),
    }


def prices():
    return {
        "openai": budget.ProviderPrice("openai", 10, 20, "sheets:zbot:price:openai"),
        "gemini": budget.ProviderPrice("gemini", 5, 10, "sheets:zbot:price:gemini"),
    }


def reliability_policy(**changes):
    values = {
        "request_timeout_ms": 15000,
        "max_attempts": 3,
        "base_backoff_ms": 250,
        "max_backoff_ms": 1000,
        "circuit_failure_threshold": 3,
        "circuit_open_ms": 60000,
        "health_max_age_ms": 1000,
        "policy_ref": "sheets:zbot:reliability",
    }
    values.update(changes)
    return reliability.ReliabilityPolicy(**values)


def health(state: str = "ready", failures: int = 0, open_until: int = 0):
    return {
        "openai": reliability.ProviderHealth("openai", state, failures, open_until, 9900),
        "gemini": reliability.ProviderHealth("gemini", state, failures, open_until, 9900),
    }


def test_prompt_registry_is_versioned_and_complete() -> None:
    assert prompt.validate_prompt_registry() == ()
    assert set(prompt.PROMPT_REGISTRY) == set(zbot.ROUTE_POLICY)
    assert all(item.version == "r53.1" for item in prompt.PROMPT_REGISTRY.values())


def test_budget_accounting_ready() -> None:
    result = budget.evaluate_budget(
        decision().required_providers,
        estimated_input_tokens=500,
        requested_output_tokens=200,
        usage=usage(),
        prices=prices(),
        policy=budget_policy(),
    )
    assert result.state == "READY"
    assert result.projected_tokens == 1400
    assert result.projected_cost_micro_usd > 0
    assert result.token_budget_valid is True
    assert result.cost_budget_valid is True


def test_daily_token_budget_fails_closed() -> None:
    result = budget.evaluate_budget(
        decision().required_providers,
        estimated_input_tokens=500,
        requested_output_tokens=200,
        usage=usage(),
        prices=prices(),
        policy=budget_policy(daily_token_limit=1000),
    )
    assert result.state == "HOLD"
    assert "DAILY_TOKEN_BUDGET_EXCEEDED" in result.reason_codes


def test_daily_cost_budget_fails_closed() -> None:
    result = budget.evaluate_budget(
        decision().required_providers,
        estimated_input_tokens=500,
        requested_output_tokens=200,
        usage=usage(),
        prices=prices(),
        policy=budget_policy(daily_cost_micro_usd_limit=201),
    )
    assert result.state == "HOLD"
    assert "DAILY_COST_BUDGET_EXCEEDED" in result.reason_codes


def test_reliability_policy_builds_bounded_retry_schedule() -> None:
    result = reliability.evaluate_reliability(
        decision().required_providers,
        now_ms=10000,
        health=health(),
        policy=reliability_policy(),
    )
    assert result.state == "READY"
    assert result.retry_backoff_ms == (250, 500)
    assert result.invocation_enabled is False


def test_open_circuit_fails_closed() -> None:
    result = reliability.evaluate_reliability(
        decision().required_providers,
        now_ms=10000,
        health=health(state="open", open_until=20000),
        policy=reliability_policy(),
    )
    assert result.state == "HOLD"
    assert "CIRCUIT_OPEN" in result.reason_codes


def test_failure_threshold_fails_closed() -> None:
    result = reliability.evaluate_reliability(
        decision().required_providers,
        now_ms=10000,
        health=health(failures=3),
        policy=reliability_policy(),
    )
    assert result.state == "HOLD"
    assert "CIRCUIT_FAILURE_THRESHOLD_REACHED" in result.reason_codes


def test_idempotency_key_is_stable_and_duplicate_is_blocked() -> None:
    current = decision()
    spec = prompt.get_prompt(current.task_kind)
    assert spec is not None
    first = idempotency.evaluate_idempotency(
        current,
        prompt_id=spec.prompt_id,
        prompt_version=spec.version,
        prior_keys=(),
    )
    second = idempotency.evaluate_idempotency(
        current,
        prompt_id=spec.prompt_id,
        prompt_version=spec.version,
        prior_keys=(first.idempotency_key,),
    )
    assert first.state == "READY"
    assert second.state == "HOLD"
    assert second.duplicate_blocked is True
    assert first.idempotency_key == second.idempotency_key


def test_prompt_version_changes_idempotency_key() -> None:
    current = decision()
    one = idempotency.build_idempotency_key(current, "zbot.risk_review", "r53.1")
    two = idempotency.build_idempotency_key(current, "zbot.risk_review", "r53.2")
    assert one != two


def test_contract_keeps_provider_invocation_disabled() -> None:
    contract = json.loads((ROOT / "config/q4r3_zbot_reliability_budget_prompt_idempotency_v1.json").read_text(encoding="utf-8"))
    assert contract["authority"]["provider_invocation_enabled"] is False
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["authority"]["execution_authority"] == "none"
    assert set(contract["closed_surfaces"]) == {
        "budget_token_accounting",
        "idempotency_cache_dedup",
        "prompt_versioning",
        "timeout_retry_circuit_breaker",
    }
