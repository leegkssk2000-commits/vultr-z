from __future__ import annotations

from policy import zbot_arbitration, zbot_budget
from policy.zbot_dryrun_canary import evaluate_provider_dryrun_canary
from policy.zbot_dryrun_types import DryRunTransportPolicy
from policy.zbot_shadow_router import build_shadow_observer_plan
from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot


def observer():
    previous = ShadowSnapshot(
        "r62.prev", "shadow.r62", 9900, "r62-test",
        "cf:shadow:r62", "cf:market:r62", "cf:position:r62", "sheets:ledger:r62",
        10, 1, 5, 4.0, 100, "sha256:" + "a" * 64,
    )
    current = ShadowSnapshot(
        "r62.current", "shadow.r62", 10000, "r62-test",
        "cf:shadow:r62", "cf:market:r62", "cf:position:r62", "sheets:ledger:r62",
        11, 1, 6, 4.5, 101, "sha256:" + "b" * 64,
    )
    plan = build_shadow_observer_plan(
        current,
        now_ms=10020,
        policy=ShadowObserverPolicy(1000, 0, 6, "sheets:zbot:shadow-observer"),
        sgrade_ready=True,
        previous_snapshot=previous,
    )
    assert plan.state == "PLAN_READY", plan.reason_codes
    assert len(plan.route_plans) == 4, plan.reason_codes
    return plan


def usage():
    return {
        "openai": zbot_budget.UsageSnapshot("openai", 100, 50, 100),
        "gemini": zbot_budget.UsageSnapshot("gemini", 100, 50, 100),
    }


def prices():
    return {
        "openai": zbot_budget.ProviderPrice("openai", 10, 20, "sheets:zbot:price:openai"),
        "gemini": zbot_budget.ProviderPrice("gemini", 5, 10, "sheets:zbot:price:gemini"),
    }


def budget_policy(**changes):
    values = dict(
        daily_token_limit=100000,
        daily_cost_micro_usd_limit=100000,
        per_request_token_limit=3000,
        max_input_tokens=2000,
        max_output_tokens=1000,
        budget_ref="sheets:zbot:budget",
    )
    values.update(changes)
    return zbot_budget.BudgetPolicy(**values)


def transport_policy():
    return DryRunTransportPolicy(500, 200, 100, "sheets:zbot:dryrun-transport")


def arbitration_policy():
    return zbot_arbitration.ArbitrationPolicy(
        0.5, 0.6, 0.2, True, "sheets:zbot:arbitration"
    )


def evaluate(*, observer_value=None, budget_value=None, prior_keys=()):
    return evaluate_provider_dryrun_canary(
        observer_value or observer(),
        decision_ts_ms=10000,
        transport_policy=transport_policy(),
        usage=usage(),
        prices=prices(),
        budget_policy=budget_value or budget_policy(),
        arbitration_policy=arbitration_policy(),
        prior_idempotency_keys=prior_keys,
    )
