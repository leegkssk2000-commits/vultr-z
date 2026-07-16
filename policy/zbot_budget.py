from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

POLICY_OWNER = "policy/zbot_budget.py"
RUNTIME_ENABLED = False


@dataclass(frozen=True)
class ProviderPrice:
    provider_id: str
    input_micro_usd_per_1k: int
    output_micro_usd_per_1k: int
    price_ref: str


@dataclass(frozen=True)
class BudgetPolicy:
    daily_token_limit: int
    daily_cost_micro_usd_limit: int
    per_request_token_limit: int
    max_input_tokens: int
    max_output_tokens: int
    budget_ref: str


@dataclass(frozen=True)
class UsageSnapshot:
    provider_id: str
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int


@dataclass(frozen=True)
class BudgetResult:
    state: str
    reason_codes: tuple[str, ...]
    projected_tokens: int
    projected_cost_micro_usd: int
    token_budget_valid: bool
    cost_budget_valid: bool


def project_cost(input_tokens: int, output_tokens: int, price: ProviderPrice) -> int:
    numerator = input_tokens * price.input_micro_usd_per_1k + output_tokens * price.output_micro_usd_per_1k
    return (numerator + 999) // 1000


def evaluate_budget(
    provider_ids: tuple[str, ...],
    *,
    estimated_input_tokens: int,
    requested_output_tokens: int,
    usage: Mapping[str, UsageSnapshot],
    prices: Mapping[str, ProviderPrice],
    policy: BudgetPolicy,
) -> BudgetResult:
    reasons: list[str] = []
    limits = (
        policy.daily_token_limit,
        policy.daily_cost_micro_usd_limit,
        policy.per_request_token_limit,
        policy.max_input_tokens,
        policy.max_output_tokens,
    )
    if any(value <= 0 for value in limits) or not policy.budget_ref:
        reasons.append("BUDGET_POLICY_INVALID")
    if estimated_input_tokens <= 0 or requested_output_tokens <= 0:
        reasons.append("TOKEN_ESTIMATE_INVALID")
    if estimated_input_tokens > policy.max_input_tokens:
        reasons.append("INPUT_TOKEN_CAP_EXCEEDED")
    if requested_output_tokens > policy.max_output_tokens:
        reasons.append("OUTPUT_TOKEN_CAP_EXCEEDED")
    per_provider_tokens = estimated_input_tokens + requested_output_tokens
    if per_provider_tokens > policy.per_request_token_limit:
        reasons.append("REQUEST_TOKEN_BUDGET_EXCEEDED")

    current_tokens = 0
    current_cost = 0
    projected_cost = 0
    for provider_id in provider_ids:
        usage_row = usage.get(provider_id)
        price_row = prices.get(provider_id)
        if usage_row is None:
            reasons.append("USAGE_SNAPSHOT_MISSING")
            continue
        if price_row is None:
            reasons.append("PROVIDER_PRICE_MISSING")
            continue
        if usage_row.provider_id != provider_id or price_row.provider_id != provider_id:
            reasons.append("PROVIDER_ID_MISMATCH")
        if min(usage_row.input_tokens, usage_row.output_tokens, usage_row.cost_micro_usd) < 0:
            reasons.append("USAGE_SNAPSHOT_INVALID")
        if min(price_row.input_micro_usd_per_1k, price_row.output_micro_usd_per_1k) < 0:
            reasons.append("PROVIDER_PRICE_INVALID")
        if not price_row.price_ref:
            reasons.append("PROVIDER_PRICE_REF_INVALID")
        current_tokens += usage_row.input_tokens + usage_row.output_tokens
        current_cost += usage_row.cost_micro_usd
        projected_cost += project_cost(estimated_input_tokens, requested_output_tokens, price_row)

    projected_tokens = per_provider_tokens * len(provider_ids)
    token_valid = current_tokens + projected_tokens <= policy.daily_token_limit
    cost_valid = current_cost + projected_cost <= policy.daily_cost_micro_usd_limit
    if not token_valid:
        reasons.append("DAILY_TOKEN_BUDGET_EXCEEDED")
    if not cost_valid:
        reasons.append("DAILY_COST_BUDGET_EXCEEDED")
    state = "READY" if not reasons else "HOLD"
    return BudgetResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("BUDGET_READY",),
        projected_tokens=projected_tokens,
        projected_cost_micro_usd=projected_cost,
        token_budget_valid=token_valid and not reasons,
        cost_budget_valid=cost_valid and not reasons,
    )
