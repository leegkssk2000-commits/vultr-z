from __future__ import annotations

import math
import re
from dataclasses import dataclass

from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot

POLICY_OWNER = "policy/zbot_shadow_validation.py"
_ALLOWED_SOURCE_PREFIXES = ("cf:", "sheets:")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ShadowValidationResult:
    state: str
    reason_codes: tuple[str, ...]
    closed_delta: int
    point_in_time_valid: bool
    source_lineage_valid: bool
    count_integrity_valid: bool
    ledger_integrity_valid: bool
    sgrade_valid: bool


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_source_ref(value: str) -> bool:
    return bool(value) and value.startswith(_ALLOWED_SOURCE_PREFIXES)


def validate_shadow_snapshot(
    snapshot: ShadowSnapshot,
    *,
    now_ms: int,
    policy: ShadowObserverPolicy,
    sgrade_ready: bool,
    previous_snapshot: ShadowSnapshot | None = None,
) -> ShadowValidationResult:
    reasons: list[str] = []
    if not snapshot.snapshot_id or not snapshot.epoch_id or not snapshot.schema_version:
        reasons.append("SHADOW_SNAPSHOT_IDENTITY_MISSING")
    if not _is_int(snapshot.observed_at_ms) or snapshot.observed_at_ms < 0:
        reasons.append("SHADOW_TIMESTAMP_INVALID")
    if not _is_int(now_ms) or now_ms < 0:
        reasons.append("NOW_TIMESTAMP_INVALID")
    if not _is_int(policy.snapshot_max_age_ms) or policy.snapshot_max_age_ms < 0:
        reasons.append("SNAPSHOT_MAX_AGE_INVALID")
    if not _is_int(policy.max_future_skew_ms) or policy.max_future_skew_ms < 0:
        reasons.append("FUTURE_SKEW_INVALID")
    if not _is_int(policy.optimization_min_closed) or policy.optimization_min_closed < 1:
        reasons.append("OPTIMIZATION_MIN_CLOSED_INVALID")
    if not _valid_source_ref(policy.policy_ref):
        reasons.append("OBSERVER_POLICY_REF_INVALID")

    source_refs = (
        snapshot.shadow_source_ref,
        snapshot.market_source_ref,
        snapshot.position_source_ref,
        snapshot.ledger_source_ref,
    )
    source_valid = all(_valid_source_ref(value) for value in source_refs)
    if not source_valid:
        reasons.append("SHADOW_SOURCE_LINEAGE_INVALID")

    counts = (
        snapshot.candidate_count,
        snapshot.open_count,
        snapshot.closed_count,
        snapshot.ledger_row_count,
    )
    count_valid = all(_is_int(value) and value >= 0 for value in counts)
    if not count_valid:
        reasons.append("SHADOW_COUNT_INVALID")
    if isinstance(snapshot.pnl_r, bool) or not isinstance(snapshot.pnl_r, (int, float)) or not math.isfinite(float(snapshot.pnl_r)):
        reasons.append("SHADOW_PNL_INVALID")

    digest_valid = bool(_SHA256_PATTERN.fullmatch(snapshot.ledger_sha256))
    if not digest_valid:
        reasons.append("LEDGER_DIGEST_INVALID")
    if count_valid and snapshot.closed_count > snapshot.ledger_row_count:
        reasons.append("CLOSED_COUNT_EXCEEDS_LEDGER_ROWS")
    if not sgrade_ready:
        reasons.append("ZBOT_SGRADE_NOT_READY")

    point_valid = False
    if _is_int(now_ms) and _is_int(snapshot.observed_at_ms):
        if snapshot.observed_at_ms > now_ms + max(policy.max_future_skew_ms, 0):
            reasons.append("SHADOW_SNAPSHOT_FROM_FUTURE")
        elif now_ms - snapshot.observed_at_ms > max(policy.snapshot_max_age_ms, 0):
            reasons.append("SHADOW_SNAPSHOT_STALE")
        else:
            point_valid = True

    closed_delta = 0
    if previous_snapshot is not None:
        if previous_snapshot.epoch_id != snapshot.epoch_id:
            reasons.append("SHADOW_EPOCH_MISMATCH")
        if previous_snapshot.snapshot_id == snapshot.snapshot_id:
            reasons.append("SHADOW_SNAPSHOT_DUPLICATE")
        if snapshot.observed_at_ms <= previous_snapshot.observed_at_ms:
            reasons.append("SHADOW_TIMESTAMP_NOT_MONOTONIC")
        if snapshot.closed_count < previous_snapshot.closed_count:
            reasons.append("SHADOW_CLOSED_COUNT_REGRESSION")
        if snapshot.ledger_row_count < previous_snapshot.ledger_row_count:
            reasons.append("LEDGER_ROW_COUNT_REGRESSION")
        closed_delta = max(0, snapshot.closed_count - previous_snapshot.closed_count)

    state = "READY" if not reasons else "HOLD"
    return ShadowValidationResult(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("SHADOW_SNAPSHOT_VALID",),
        closed_delta=closed_delta if not reasons else 0,
        point_in_time_valid=point_valid and not reasons,
        source_lineage_valid=source_valid and not reasons,
        count_integrity_valid=count_valid and not reasons,
        ledger_integrity_valid=digest_valid and not reasons,
        sgrade_valid=sgrade_ready and not reasons,
    )
