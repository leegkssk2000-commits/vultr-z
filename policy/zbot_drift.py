from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

POLICY_OWNER = "policy/zbot_drift.py"
RUNTIME_ENABLED = False
PROVIDER_INVOCATION_ENABLED = False


@dataclass(frozen=True)
class QualitySnapshot:
    provider_id: str
    model_id: str
    sample_count: int
    mean_confidence: float
    positive_value_rate: float
    action_disagreement_rate: float
    schema_failure_rate: float
    mean_cost_micro_usd: float
    observed_at_ms: int
    metric_ref: str


@dataclass(frozen=True)
class DriftPolicy:
    min_samples: int
    max_snapshot_age_ms: int
    max_confidence_shift: float
    max_positive_value_rate_drop: float
    max_disagreement_rate_increase: float
    max_schema_failure_rate_increase: float
    max_cost_ratio: float
    policy_ref: str


@dataclass(frozen=True)
class ProviderDrift:
    provider_id: str
    reference_model_id: str
    current_model_id: str
    confidence_shift: float
    positive_value_rate_drop: float
    disagreement_rate_increase: float
    schema_failure_rate_increase: float
    cost_ratio: float
    drifted: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class DriftResult:
    state: str
    reason_codes: tuple[str, ...]
    provider_rows: tuple[ProviderDrift, ...]
    drifted_provider_count: int
    quality_drift_ready: bool
    fail_closed: bool


def _valid_rate(value: float) -> bool:
    return 0.0 <= value <= 1.0


def evaluate_quality_drift(
    reference: Sequence[QualitySnapshot],
    current: Sequence[QualitySnapshot],
    *,
    expected_provider_ids: tuple[str, ...],
    now_ms: int,
    policy: DriftPolicy,
) -> DriftResult:
    reasons: list[str] = []
    if policy.min_samples < 1 or policy.max_snapshot_age_ms < 0:
        reasons.append("DRIFT_POLICY_INVALID")
    thresholds = (
        policy.max_confidence_shift,
        policy.max_positive_value_rate_drop,
        policy.max_disagreement_rate_increase,
        policy.max_schema_failure_rate_increase,
    )
    if any(not 0.0 <= value <= 1.0 for value in thresholds) or policy.max_cost_ratio < 1.0:
        reasons.append("DRIFT_THRESHOLD_INVALID")
    if not policy.policy_ref or ":" not in policy.policy_ref:
        reasons.append("DRIFT_POLICY_REF_INVALID")
    if not expected_provider_ids or len(set(expected_provider_ids)) != len(expected_provider_ids):
        reasons.append("DRIFT_EXPECTED_PROVIDER_SET_INVALID")
    if now_ms < 0:
        reasons.append("DRIFT_NOW_INVALID")

    reference_map = {item.provider_id: item for item in reference}
    current_map = {item.provider_id: item for item in current}
    if len(reference_map) != len(reference):
        reasons.append("DRIFT_REFERENCE_PROVIDER_DUPLICATE")
    if len(current_map) != len(current):
        reasons.append("DRIFT_CURRENT_PROVIDER_DUPLICATE")
    if set(reference_map) != set(expected_provider_ids):
        reasons.append("DRIFT_REFERENCE_PROVIDER_SET_MISMATCH")
    if set(current_map) != set(expected_provider_ids):
        reasons.append("DRIFT_CURRENT_PROVIDER_SET_MISMATCH")

    rows: list[ProviderDrift] = []
    for provider_id in expected_provider_ids:
        baseline = reference_map.get(provider_id)
        observed = current_map.get(provider_id)
        if baseline is None or observed is None:
            continue
        local_reasons: list[str] = []
        for item, prefix in ((baseline, "REFERENCE"), (observed, "CURRENT")):
            if item.sample_count < policy.min_samples:
                local_reasons.append(f"DRIFT_{prefix}_SAMPLE_COUNT_BELOW_MIN")
            if not item.model_id:
                local_reasons.append(f"DRIFT_{prefix}_MODEL_ID_MISSING")
            rates = (
                item.mean_confidence,
                item.positive_value_rate,
                item.action_disagreement_rate,
                item.schema_failure_rate,
            )
            if any(not _valid_rate(value) for value in rates):
                local_reasons.append(f"DRIFT_{prefix}_RATE_INVALID")
            if item.mean_cost_micro_usd < 0:
                local_reasons.append(f"DRIFT_{prefix}_COST_INVALID")
            if item.observed_at_ms < 0 or item.observed_at_ms > now_ms:
                local_reasons.append(f"DRIFT_{prefix}_TIMESTAMP_INVALID")
            elif now_ms - item.observed_at_ms > policy.max_snapshot_age_ms:
                local_reasons.append(f"DRIFT_{prefix}_SNAPSHOT_STALE")
            if not item.metric_ref or ":" not in item.metric_ref:
                local_reasons.append(f"DRIFT_{prefix}_METRIC_REF_INVALID")

        confidence_shift = abs(observed.mean_confidence - baseline.mean_confidence)
        positive_drop = max(0.0, baseline.positive_value_rate - observed.positive_value_rate)
        disagreement_increase = max(0.0, observed.action_disagreement_rate - baseline.action_disagreement_rate)
        schema_increase = max(0.0, observed.schema_failure_rate - baseline.schema_failure_rate)
        if baseline.mean_cost_micro_usd == 0:
            cost_ratio = 1.0 if observed.mean_cost_micro_usd == 0 else float("inf")
        else:
            cost_ratio = observed.mean_cost_micro_usd / baseline.mean_cost_micro_usd

        if confidence_shift > policy.max_confidence_shift:
            local_reasons.append("DRIFT_CONFIDENCE_SHIFT_EXCEEDED")
        if positive_drop > policy.max_positive_value_rate_drop:
            local_reasons.append("DRIFT_POSITIVE_VALUE_RATE_DROP_EXCEEDED")
        if disagreement_increase > policy.max_disagreement_rate_increase:
            local_reasons.append("DRIFT_DISAGREEMENT_RATE_INCREASE_EXCEEDED")
        if schema_increase > policy.max_schema_failure_rate_increase:
            local_reasons.append("DRIFT_SCHEMA_FAILURE_RATE_INCREASE_EXCEEDED")
        if cost_ratio > policy.max_cost_ratio:
            local_reasons.append("DRIFT_COST_RATIO_EXCEEDED")

        rows.append(ProviderDrift(
            provider_id=provider_id,
            reference_model_id=baseline.model_id,
            current_model_id=observed.model_id,
            confidence_shift=round(confidence_shift, 8),
            positive_value_rate_drop=round(positive_drop, 8),
            disagreement_rate_increase=round(disagreement_increase, 8),
            schema_failure_rate_increase=round(schema_increase, 8),
            cost_ratio=round(cost_ratio, 8) if cost_ratio != float("inf") else cost_ratio,
            drifted=bool(local_reasons),
            reason_codes=tuple(sorted(set(local_reasons))) if local_reasons else ("NO_MATERIAL_DRIFT",),
        ))
        reasons.extend(local_reasons)

    state = "READY" if not reasons else "HOLD"
    return DriftResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("MODEL_QUALITY_DRIFT_READY",),
        provider_rows=tuple(rows),
        drifted_provider_count=sum(1 for row in rows if row.drifted),
        quality_drift_ready=not reasons,
        fail_closed=True,
    )
