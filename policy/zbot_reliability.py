from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

POLICY_OWNER = "policy/zbot_reliability.py"
PROVIDER_INVOCATION_ENABLED = False
RUNTIME_ENABLED = False


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    state: str
    consecutive_failures: int
    circuit_open_until_ms: int
    observed_at_ms: int


@dataclass(frozen=True)
class ReliabilityPolicy:
    request_timeout_ms: int
    max_attempts: int
    base_backoff_ms: int
    max_backoff_ms: int
    circuit_failure_threshold: int
    circuit_open_ms: int
    health_max_age_ms: int
    policy_ref: str


@dataclass(frozen=True)
class ReliabilityResult:
    state: str
    reason_codes: tuple[str, ...]
    timeout_ms: int
    max_attempts: int
    retry_backoff_ms: tuple[int, ...]
    circuit_policy_valid: bool
    invocation_enabled: bool


def retry_schedule(policy: ReliabilityPolicy) -> tuple[int, ...]:
    delays: list[int] = []
    delay = policy.base_backoff_ms
    for _ in range(max(0, policy.max_attempts - 1)):
        delays.append(min(delay, policy.max_backoff_ms))
        delay = min(delay * 2, policy.max_backoff_ms)
    return tuple(delays)


def evaluate_reliability(
    provider_ids: tuple[str, ...],
    *,
    now_ms: int,
    health: Mapping[str, ProviderHealth],
    policy: ReliabilityPolicy,
) -> ReliabilityResult:
    reasons: list[str] = []
    if policy.request_timeout_ms <= 0 or policy.max_attempts < 1:
        reasons.append("RELIABILITY_POLICY_INVALID")
    if policy.base_backoff_ms <= 0 or policy.max_backoff_ms < policy.base_backoff_ms:
        reasons.append("RETRY_BACKOFF_INVALID")
    if policy.circuit_failure_threshold < 1 or policy.circuit_open_ms <= 0:
        reasons.append("CIRCUIT_POLICY_INVALID")
    if policy.health_max_age_ms < 0 or not policy.policy_ref:
        reasons.append("HEALTH_POLICY_INVALID")
    if now_ms < 0:
        reasons.append("NOW_TIMESTAMP_INVALID")

    for provider_id in provider_ids:
        row = health.get(provider_id)
        if row is None:
            reasons.append("PROVIDER_HEALTH_MISSING")
            continue
        if row.provider_id != provider_id:
            reasons.append("PROVIDER_ID_MISMATCH")
        if row.state not in {"ready", "degraded", "open"}:
            reasons.append("PROVIDER_HEALTH_STATE_INVALID")
        if row.observed_at_ms < 0 or row.observed_at_ms > now_ms:
            reasons.append("PROVIDER_HEALTH_TIMESTAMP_INVALID")
        elif now_ms - row.observed_at_ms > policy.health_max_age_ms:
            reasons.append("PROVIDER_HEALTH_STALE")
        if row.consecutive_failures < 0:
            reasons.append("PROVIDER_FAILURE_COUNT_INVALID")
        if row.state == "open" and now_ms < row.circuit_open_until_ms:
            reasons.append("CIRCUIT_OPEN")
        if row.consecutive_failures >= policy.circuit_failure_threshold:
            reasons.append("CIRCUIT_FAILURE_THRESHOLD_REACHED")

    state = "READY" if not reasons else "HOLD"
    return ReliabilityResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("RELIABILITY_READY",),
        timeout_ms=policy.request_timeout_ms,
        max_attempts=policy.max_attempts,
        retry_backoff_ms=retry_schedule(policy),
        circuit_policy_valid=not reasons,
        invocation_enabled=False,
    )
