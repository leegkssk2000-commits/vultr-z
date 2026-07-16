from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

POLICY_OWNER = "policy/zbot_attribution.py"
RUNTIME_ENABLED = False
PROVIDER_INVOCATION_ENABLED = False


@dataclass(frozen=True)
class ProviderOutcome:
    observation_id: str
    receipt_id: str
    provider_id: str
    task_kind: str
    model_id: str
    proposed_action: str
    realized_r: float
    baseline_r: float
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    observed_at_ms: int
    outcome_ref: str


@dataclass(frozen=True)
class AttributionPolicy:
    min_samples_per_provider: int
    max_sample_age_ms: int
    max_cost_per_positive_r_micro_usd: int
    min_net_value_r: float
    policy_ref: str


@dataclass(frozen=True)
class ProviderAttribution:
    provider_id: str
    model_ids: tuple[str, ...]
    sample_count: int
    gross_incremental_r: float
    total_cost_micro_usd: int
    cost_per_positive_r_micro_usd: int | None
    net_value_r: float
    positive_value_rate: float


@dataclass(frozen=True)
class AttributionResult:
    state: str
    reason_codes: tuple[str, ...]
    provider_rows: tuple[ProviderAttribution, ...]
    ensemble_sample_count: int
    ensemble_gross_incremental_r: float
    ensemble_total_cost_micro_usd: int
    ensemble_net_value_r: float
    attribution_ready: bool
    fail_closed: bool


def _summarize(provider_id: str, rows: Sequence[ProviderOutcome]) -> ProviderAttribution:
    gross = sum(item.realized_r - item.baseline_r for item in rows)
    total_cost = sum(item.cost_micro_usd for item in rows)
    positive_count = sum(1 for item in rows if item.realized_r - item.baseline_r > 0)
    positive_r = max(gross, 0.0)
    cost_per_positive_r = None if positive_r <= 0 else int(round(total_cost / positive_r))
    return ProviderAttribution(
        provider_id=provider_id,
        model_ids=tuple(sorted({item.model_id for item in rows})),
        sample_count=len(rows),
        gross_incremental_r=round(gross, 8),
        total_cost_micro_usd=total_cost,
        cost_per_positive_r_micro_usd=cost_per_positive_r,
        net_value_r=round(gross - total_cost / 1_000_000.0, 8),
        positive_value_rate=round(positive_count / len(rows), 8) if rows else 0.0,
    )


def evaluate_attribution(
    observations: Sequence[ProviderOutcome],
    *,
    expected_provider_ids: tuple[str, ...],
    now_ms: int,
    policy: AttributionPolicy,
) -> AttributionResult:
    reasons: list[str] = []
    if policy.min_samples_per_provider < 1 or policy.max_sample_age_ms < 0:
        reasons.append("ATTRIBUTION_POLICY_INVALID")
    if policy.max_cost_per_positive_r_micro_usd < 0:
        reasons.append("ATTRIBUTION_COST_LIMIT_INVALID")
    if not policy.policy_ref or ":" not in policy.policy_ref:
        reasons.append("ATTRIBUTION_POLICY_REF_INVALID")
    if not expected_provider_ids or len(set(expected_provider_ids)) != len(expected_provider_ids):
        reasons.append("ATTRIBUTION_EXPECTED_PROVIDER_SET_INVALID")
    if now_ms < 0:
        reasons.append("ATTRIBUTION_NOW_INVALID")

    seen_observations: set[str] = set()
    seen_receipt_provider: set[tuple[str, str]] = set()
    grouped: dict[str, list[ProviderOutcome]] = {provider_id: [] for provider_id in expected_provider_ids}
    for item in observations:
        if not item.observation_id or item.observation_id in seen_observations:
            reasons.append("ATTRIBUTION_OBSERVATION_ID_INVALID_OR_DUPLICATE")
        seen_observations.add(item.observation_id)
        pair = (item.receipt_id, item.provider_id)
        if not item.receipt_id or pair in seen_receipt_provider:
            reasons.append("ATTRIBUTION_RECEIPT_PROVIDER_DUPLICATE")
        seen_receipt_provider.add(pair)
        if item.provider_id not in grouped:
            reasons.append("ATTRIBUTION_PROVIDER_UNEXPECTED")
            continue
        if not item.task_kind or not item.model_id or not item.proposed_action:
            reasons.append("ATTRIBUTION_IDENTITY_MISSING")
        if item.input_tokens < 0 or item.output_tokens < 0 or item.cost_micro_usd < 0:
            reasons.append("ATTRIBUTION_USAGE_INVALID")
        if item.observed_at_ms < 0 or item.observed_at_ms > now_ms:
            reasons.append("ATTRIBUTION_TIMESTAMP_INVALID")
        elif now_ms - item.observed_at_ms > policy.max_sample_age_ms:
            reasons.append("ATTRIBUTION_SAMPLE_STALE")
        if not item.outcome_ref or ":" not in item.outcome_ref:
            reasons.append("ATTRIBUTION_OUTCOME_REF_INVALID")
        grouped[item.provider_id].append(item)

    provider_rows = tuple(_summarize(provider_id, grouped[provider_id]) for provider_id in expected_provider_ids)
    for row in provider_rows:
        if row.sample_count < policy.min_samples_per_provider:
            reasons.append("ATTRIBUTION_SAMPLE_COUNT_BELOW_MIN")
        if row.net_value_r < policy.min_net_value_r:
            reasons.append("ATTRIBUTION_NET_VALUE_BELOW_MIN")
        if row.cost_per_positive_r_micro_usd is not None and row.cost_per_positive_r_micro_usd > policy.max_cost_per_positive_r_micro_usd:
            reasons.append("ATTRIBUTION_COST_EFFICIENCY_EXCEEDED")

    ensemble_samples = len({item.receipt_id for item in observations})
    ensemble_gross = sum(row.gross_incremental_r for row in provider_rows) / len(provider_rows) if provider_rows else 0.0
    ensemble_cost = sum(row.total_cost_micro_usd for row in provider_rows)
    ensemble_net = ensemble_gross - ensemble_cost / 1_000_000.0
    state = "READY" if not reasons else "HOLD"
    return AttributionResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("ATTRIBUTION_READY",),
        provider_rows=provider_rows,
        ensemble_sample_count=ensemble_samples,
        ensemble_gross_incremental_r=round(ensemble_gross, 8),
        ensemble_total_cost_micro_usd=ensemble_cost,
        ensemble_net_value_r=round(ensemble_net, 8),
        attribution_ready=not reasons,
        fail_closed=True,
    )
