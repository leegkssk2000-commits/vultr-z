from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from canonical.lico import (
    EXECUTION_AUTHORITY,
    OBSERVER_ONLY,
    ORDER_ENABLED,
    RUNTIME_ENABLED,
)

MODEL_OWNER = "canonical/lico.py"
MODEL_COMPONENT = "Lico"
MODEL_STAGE = "R4.6"
TEAM_CONTEXT_SURFACE = "team_context"
CALIBRATION_SURFACE = "shadow_paper_calibration"
ALL_TEAMS = frozenset({"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"})
ALL_BOTS = frozenset({"LBot", "MBot", "OBot", "SBot"})
ALLOWED_SIDES = frozenset({"long", "short"})
BPS = Decimal("10000")
ZERO = Decimal("0")


@dataclass(frozen=True)
class TeamContext:
    selected_team: str
    main_owner: str
    support_owner: str
    watcher_owners: tuple[str, str]
    reserve_owner: str | None
    helper_owner: str | None
    helper_trigger: str
    mission: str
    policy_family: str


@dataclass(frozen=True)
class EvidenceLineage:
    position_id: str
    decision_id: str
    strategy_id: str
    method_id: str
    skill_id: str
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    contract_version: str
    decision_ts_ms: int


@dataclass(frozen=True)
class FillObservation:
    mode: str
    position_id: str
    decision_id: str
    symbol: str
    side: str
    fill_price: Decimal
    fill_latency_ms: int
    partial_fill: bool
    net_r: Decimal
    observed_at_ms: int
    evidence_id: str


@dataclass(frozen=True)
class CalibrationPolicy:
    allowed_teams: tuple[str, ...]
    required_bots: tuple[str, ...]
    minimum_sample_count: int
    max_fill_price_error_bps: Decimal
    max_fill_latency_error_ms: int
    require_partial_fill_match: bool
    max_net_r_gap: Decimal
    policy_refs: tuple[str, ...]
    schema_version: str


@dataclass(frozen=True)
class LicoCalibrationEnvelope:
    state: str
    action: str
    reason_codes: tuple[str, ...]
    selected_team: str
    team_context: bool
    evidence_lineage: bool
    actual_vs_simulated: bool
    sample_count: int
    fill_price_error_bps: Decimal
    fill_latency_error_ms: int
    partial_fill_match: bool
    net_r_gap: Decimal
    calibration: bool
    sgrade_ready: bool
    accepted: bool
    fail_closed: bool
    abstain: bool
    observer_only: bool
    execution_authority: str
    runtime_enabled: bool
    order_enabled: bool
    contract_version: str


def _hold(
    reasons: Sequence[str],
    *,
    team: TeamContext | None,
    contract_version: str,
) -> LicoCalibrationEnvelope:
    return LicoCalibrationEnvelope(
        state="HOLD",
        action="hold",
        reason_codes=tuple(sorted(set(reasons))),
        selected_team=team.selected_team if team else "",
        team_context=False,
        evidence_lineage=False,
        actual_vs_simulated=False,
        sample_count=0,
        fill_price_error_bps=ZERO,
        fill_latency_error_ms=0,
        partial_fill_match=False,
        net_r_gap=ZERO,
        calibration=False,
        sgrade_ready=False,
        accepted=False,
        fail_closed=True,
        abstain=True,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        contract_version=contract_version,
    )


def _policy_errors(policy: CalibrationPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if set(policy.allowed_teams) != ALL_TEAMS:
        reasons.append("CALIBRATION_POLICY_TEAM_SET_INVALID")
    if set(policy.required_bots) != ALL_BOTS:
        reasons.append("CALIBRATION_POLICY_BOT_SET_INVALID")
    if policy.minimum_sample_count <= 0:
        reasons.append("CALIBRATION_POLICY_SAMPLE_COUNT_INVALID")
    if policy.max_fill_price_error_bps < 0 or policy.max_fill_latency_error_ms < 0 or policy.max_net_r_gap < 0:
        reasons.append("CALIBRATION_POLICY_THRESHOLD_INVALID")
    prefixes = {"cf:", "sheets:"}
    if not policy.policy_refs or not all(any(ref.startswith(prefix) for prefix in prefixes) for ref in policy.policy_refs):
        reasons.append("CALIBRATION_POLICY_REFS_INVALID")
    if not any(ref.startswith("cf:") for ref in policy.policy_refs) or not any(ref.startswith("sheets:") for ref in policy.policy_refs):
        reasons.append("CALIBRATION_POLICY_SOURCE_PAIR_INCOMPLETE")
    if not policy.schema_version:
        reasons.append("CALIBRATION_POLICY_SCHEMA_MISSING")
    return tuple(sorted(set(reasons)))


def _team_errors(team: TeamContext, policy: CalibrationPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if team.selected_team not in policy.allowed_teams:
        reasons.append("TEAM_CONTEXT_SELECTED_TEAM_INVALID")
    if team.main_owner not in ALL_BOTS or team.support_owner not in ALL_BOTS:
        reasons.append("TEAM_CONTEXT_PRIMARY_ROLE_INVALID")
    if team.main_owner == team.support_owner:
        reasons.append("TEAM_CONTEXT_PRIMARY_ROLE_DUPLICATE")
    if len(team.watcher_owners) != 2 or len(set(team.watcher_owners)) != 2:
        reasons.append("TEAM_CONTEXT_WATCHER_SET_INVALID")
    if any(owner not in ALL_BOTS for owner in team.watcher_owners):
        reasons.append("TEAM_CONTEXT_WATCHER_OWNER_INVALID")
    assigned = {team.main_owner, team.support_owner, *team.watcher_owners}
    if assigned != ALL_BOTS:
        reasons.append("TEAM_CONTEXT_FOUR_BOT_COVERAGE_INVALID")
    if team.reserve_owner is not None and team.reserve_owner not in ALL_BOTS:
        reasons.append("TEAM_CONTEXT_RESERVE_OWNER_INVALID")
    if team.helper_owner is None and team.helper_trigger:
        reasons.append("TEAM_CONTEXT_HELPER_TRIGGER_WITHOUT_OWNER")
    if team.helper_owner is not None:
        if team.helper_owner not in ALL_BOTS:
            reasons.append("TEAM_CONTEXT_HELPER_OWNER_INVALID")
        if not team.helper_trigger:
            reasons.append("TEAM_CONTEXT_HELPER_TRIGGER_MISSING")
    if not team.mission or not team.policy_family:
        reasons.append("TEAM_CONTEXT_POLICY_IDENTITY_MISSING")
    return tuple(sorted(set(reasons)))


def _lineage_errors(lineages: Sequence[EvidenceLineage]) -> tuple[str, ...]:
    reasons: list[str] = []
    if not lineages:
        return ("EVIDENCE_LINEAGE_MISSING",)
    position_ids: list[str] = []
    decision_ids: list[str] = []
    for lineage in lineages:
        position_ids.append(lineage.position_id)
        decision_ids.append(lineage.decision_id)
        required = (
            lineage.position_id,
            lineage.decision_id,
            lineage.strategy_id,
            lineage.method_id,
            lineage.skill_id,
            lineage.contract_version,
        )
        if any(not value for value in required):
            reasons.append("EVIDENCE_LINEAGE_IDENTITY_MISSING")
        if lineage.decision_ts_ms < 0:
            reasons.append("EVIDENCE_LINEAGE_TIMESTAMP_INVALID")
        if not lineage.source_ids:
            reasons.append("EVIDENCE_LINEAGE_SOURCE_IDS_MISSING")
        else:
            if not any(value.startswith("cf:") for value in lineage.source_ids):
                reasons.append("EVIDENCE_LINEAGE_CF_SOURCE_MISSING")
            if not any(value.startswith("sheets:") for value in lineage.source_ids):
                reasons.append("EVIDENCE_LINEAGE_SHEETS_SOURCE_MISSING")
        if not lineage.evidence_ids or any(not value for value in lineage.evidence_ids):
            reasons.append("EVIDENCE_LINEAGE_EVIDENCE_IDS_MISSING")
    if len(position_ids) != len(set(position_ids)):
        reasons.append("EVIDENCE_LINEAGE_POSITION_DUPLICATE")
    if len(decision_ids) != len(set(decision_ids)):
        reasons.append("EVIDENCE_LINEAGE_DECISION_DUPLICATE")
    return tuple(sorted(set(reasons)))


def _observation_errors(
    observations: Sequence[FillObservation],
    *,
    expected_mode: str,
    lineage_by_key: dict[tuple[str, str], EvidenceLineage],
) -> tuple[str, ...]:
    reasons: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in observations:
        key = (item.position_id, item.decision_id)
        if item.mode != expected_mode:
            reasons.append("CALIBRATION_MODE_INVALID")
        if key in seen:
            reasons.append("CALIBRATION_OBSERVATION_DUPLICATE")
        seen.add(key)
        lineage = lineage_by_key.get(key)
        if lineage is None:
            reasons.append("CALIBRATION_LINEAGE_JOIN_MISSING")
            continue
        if item.symbol.upper().replace("/", "").replace("-", "").replace("_", "").endswith("USDT") is False:
            reasons.append("CALIBRATION_SYMBOL_INVALID")
        if item.side not in ALLOWED_SIDES:
            reasons.append("CALIBRATION_SIDE_INVALID")
        if item.fill_price <= 0 or item.fill_latency_ms < 0:
            reasons.append("CALIBRATION_FILL_INPUT_INVALID")
        if item.observed_at_ms < lineage.decision_ts_ms:
            reasons.append("CALIBRATION_LOOKAHEAD_OR_TIMESTAMP_INVALID")
        if item.evidence_id not in lineage.evidence_ids:
            reasons.append("CALIBRATION_EVIDENCE_JOIN_INVALID")
    if seen != set(lineage_by_key):
        reasons.append("CALIBRATION_OBSERVATION_SET_INCOMPLETE")
    return tuple(sorted(set(reasons)))


def evaluate_team_lineage_calibration(
    team_context: TeamContext,
    lineages: Sequence[EvidenceLineage],
    shadow_observations: Sequence[FillObservation],
    paper_observations: Sequence[FillObservation],
    *,
    policy: CalibrationPolicy,
) -> LicoCalibrationEnvelope:
    errors = list(_policy_errors(policy))
    errors.extend(_team_errors(team_context, policy))
    errors.extend(_lineage_errors(lineages))
    lineage_by_key = {(item.position_id, item.decision_id): item for item in lineages}
    errors.extend(_observation_errors(shadow_observations, expected_mode="shadow", lineage_by_key=lineage_by_key))
    errors.extend(_observation_errors(paper_observations, expected_mode="paper", lineage_by_key=lineage_by_key))
    if len(lineages) < policy.minimum_sample_count:
        errors.append("CALIBRATION_SAMPLE_COUNT_BELOW_POLICY")
    if errors:
        return _hold(errors, team=team_context, contract_version=policy.schema_version)

    shadow_by_key = {(item.position_id, item.decision_id): item for item in shadow_observations}
    paper_by_key = {(item.position_id, item.decision_id): item for item in paper_observations}
    price_errors: list[Decimal] = []
    latency_errors: list[int] = []
    net_r_gaps: list[Decimal] = []
    partial_matches: list[bool] = []
    pair_errors: list[str] = []

    for key in sorted(lineage_by_key):
        shadow = shadow_by_key[key]
        paper = paper_by_key[key]
        if shadow.symbol.upper().replace("/", "").replace("-", "").replace("_", "") != paper.symbol.upper().replace("/", "").replace("-", "").replace("_", ""):
            pair_errors.append("CALIBRATION_SYMBOL_MISMATCH")
        if shadow.side != paper.side:
            pair_errors.append("CALIBRATION_SIDE_MISMATCH")
        price_errors.append(abs(paper.fill_price - shadow.fill_price) / paper.fill_price * BPS)
        latency_errors.append(abs(paper.fill_latency_ms - shadow.fill_latency_ms))
        net_r_gaps.append(abs(paper.net_r - shadow.net_r))
        partial_matches.append(paper.partial_fill == shadow.partial_fill)

    if pair_errors:
        return _hold(pair_errors, team=team_context, contract_version=policy.schema_version)

    fill_price_error_bps = max(price_errors, default=ZERO)
    fill_latency_error_ms = max(latency_errors, default=0)
    net_r_gap = max(net_r_gaps, default=ZERO)
    partial_fill_match = all(partial_matches)

    reasons: list[str] = []
    if fill_price_error_bps > policy.max_fill_price_error_bps:
        reasons.append("CALIBRATION_FILL_PRICE_ERROR_EXCEEDED")
    if fill_latency_error_ms > policy.max_fill_latency_error_ms:
        reasons.append("CALIBRATION_FILL_LATENCY_ERROR_EXCEEDED")
    if policy.require_partial_fill_match and not partial_fill_match:
        reasons.append("CALIBRATION_PARTIAL_FILL_MISMATCH")
    if net_r_gap > policy.max_net_r_gap:
        reasons.append("CALIBRATION_NET_R_GAP_EXCEEDED")

    calibration_passed = not reasons
    return LicoCalibrationEnvelope(
        state="READY",
        action="hold" if calibration_passed else "route_change",
        reason_codes=("LICO_SGRADE_CALIBRATION_READY",) if calibration_passed else tuple(sorted(set(reasons))),
        selected_team=team_context.selected_team,
        team_context=True,
        evidence_lineage=True,
        actual_vs_simulated=True,
        sample_count=len(lineages),
        fill_price_error_bps=fill_price_error_bps,
        fill_latency_error_ms=fill_latency_error_ms,
        partial_fill_match=partial_fill_match,
        net_r_gap=net_r_gap,
        calibration=calibration_passed,
        sgrade_ready=calibration_passed,
        accepted=calibration_passed,
        fail_closed=True,
        abstain=False,
        observer_only=OBSERVER_ONLY,
        execution_authority=EXECUTION_AUTHORITY,
        runtime_enabled=RUNTIME_ENABLED,
        order_enabled=ORDER_ENABLED,
        contract_version=policy.schema_version,
    )
