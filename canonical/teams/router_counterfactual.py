from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping

from .policy_contracts import CANONICAL_SOURCES, TEAM_POLICY_REGISTRY

TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]

ROUTER_VERSION = "team-router-counterfactual/1.0.0"
TEAM_NAMES = frozenset(TEAM_POLICY_REGISTRY)
SCORE_WEIGHT_KEYS = frozenset({"confidence", "net_r", "drawdown", "cost"})
REMAINING_SHARED_GAPS: tuple[str, ...] = ()


def _source_reasons(source_ids: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if not source_ids:
        return (f"{prefix}_SOURCE_IDS_MISSING",)
    if len(set(source_ids)) != len(source_ids):
        reasons.append(f"{prefix}_SOURCE_IDS_DUPLICATE")
    if any(not source.startswith(CANONICAL_SOURCES) for source in source_ids):
        reasons.append(f"{prefix}_SOURCE_PREFIX_INVALID")
    if not any(source.startswith("cf:") for source in source_ids):
        reasons.append(f"{prefix}_CF_SOURCE_MISSING")
    if not any(source.startswith("sheets:") for source in source_ids):
        reasons.append(f"{prefix}_SHEETS_SOURCE_MISSING")
    return tuple(reasons)


def _ratio_valid(value: float) -> bool:
    return 0.0 <= value <= 1.0


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    policy_id: str
    source_ids: tuple[str, ...]
    score_weights: Mapping[str, float]
    minimum_score_margin: float
    minimum_counterfactual_uplift_r: float
    maximum_candidate_dd_pct: float
    defense_override_regimes: tuple[str, ...]
    contract_version: str = ROUTER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_weights", MappingProxyType(dict(self.score_weights)))
        errors = self.validate()
        if errors:
            raise ValueError("ROUTER_POLICY_INVALID:" + ",".join(errors))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = list(_source_reasons(self.source_ids, "POLICY"))
        if not self.policy_id:
            errors.append("POLICY_ID_MISSING")
        if set(self.score_weights) != SCORE_WEIGHT_KEYS:
            errors.append("SCORE_WEIGHT_KEYS_INVALID")
        elif any(value < 0.0 for value in self.score_weights.values()):
            errors.append("SCORE_WEIGHT_NEGATIVE")
        elif sum(self.score_weights.values()) <= 0.0:
            errors.append("SCORE_WEIGHT_TOTAL_ZERO")
        if self.minimum_score_margin < 0.0:
            errors.append("MINIMUM_SCORE_MARGIN_NEGATIVE")
        if self.minimum_counterfactual_uplift_r < 0.0:
            errors.append("MINIMUM_COUNTERFACTUAL_UPLIFT_NEGATIVE")
        if self.maximum_candidate_dd_pct < 0.0:
            errors.append("MAXIMUM_CANDIDATE_DD_NEGATIVE")
        if not self.defense_override_regimes:
            errors.append("DEFENSE_OVERRIDE_REGIMES_EMPTY")
        if self.contract_version != ROUTER_VERSION:
            errors.append("CONTRACT_VERSION_INVALID")
        return tuple(errors)


@dataclass(frozen=True, slots=True)
class TeamRouteCandidate:
    team_id: TeamName
    observed_regime: str
    calibrated_confidence: float
    expected_net_r: float
    expected_dd_pct: float
    expected_cost_r: float
    role_ready: bool
    confidence_ready: bool
    hard_veto: bool
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    data_state: str = "FRESH"
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.team_id not in TEAM_NAMES:
            raise ValueError("TEAM_ID_INVALID")
        if not self.observed_regime:
            raise ValueError("OBSERVED_REGIME_REQUIRED")
        if not _ratio_valid(self.calibrated_confidence):
            raise ValueError("CALIBRATED_CONFIDENCE_RANGE_INVALID")
        if self.expected_dd_pct < 0.0:
            raise ValueError("EXPECTED_DD_NEGATIVE")
        if self.expected_cost_r < 0.0:
            raise ValueError("EXPECTED_COST_NEGATIVE")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("CANDIDATE_EVIDENCE_DUPLICATE")


@dataclass(frozen=True, slots=True)
class TeamRouterRequest:
    request_id: str
    candidates: tuple[TeamRouteCandidate, ...]
    no_team_expected_net_r: float
    policy: RouterPolicy
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    data_state: str = "FRESH"

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("REQUEST_ID_MISSING")
        team_ids = tuple(candidate.team_id for candidate in self.candidates)
        if len(set(team_ids)) != len(team_ids):
            raise ValueError("CANDIDATE_TEAM_DUPLICATE")
        if set(team_ids) != TEAM_NAMES:
            raise ValueError("CANDIDATE_TEAM_SET_INVALID")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("REQUEST_EVIDENCE_DUPLICATE")


@dataclass(frozen=True, slots=True)
class RankedTeam:
    team_id: TeamName
    observed_regime: str
    eligible: bool
    score: float
    calibrated_confidence: float
    expected_net_r: float
    expected_dd_pct: float
    expected_cost_r: float
    counterfactual_uplift_r: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamRouteEnvelope:
    route_id: str
    selected_team: TeamName | None
    ranked_teams: tuple[RankedTeam, ...]
    decision_ready: bool
    fail_closed: bool
    abstain: bool
    hard_veto: bool
    action: str
    score_margin: float | None
    counterfactual_uplift_r: float | None
    reason_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    policy_id: str
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = ROUTER_VERSION

    def binding_team(self) -> TeamName | None:
        return self.selected_team if self.decision_ready else None


def _route_id(request: TeamRouterRequest) -> str:
    raw = "|".join(
        (
            request.request_id,
            request.policy.policy_id,
            str(request.no_team_expected_net_r),
            ",".join(
                f"{candidate.team_id}:{candidate.observed_regime}:{candidate.calibrated_confidence}:"
                f"{candidate.expected_net_r}:{candidate.expected_dd_pct}:{candidate.expected_cost_r}:"
                f"{candidate.role_ready}:{candidate.confidence_ready}:{candidate.hard_veto}"
                for candidate in sorted(request.candidates, key=lambda item: item.team_id)
            ),
            ",".join(request.source_ids),
            ",".join(request.evidence_ids),
        )
    ).encode("utf-8")
    return f"route.{hashlib.sha256(raw).hexdigest()[:24]}"


def _candidate_score(candidate: TeamRouteCandidate, policy: RouterPolicy) -> float:
    weights = policy.score_weights
    return (
        weights["confidence"] * candidate.calibrated_confidence
        + weights["net_r"] * candidate.expected_net_r
        - weights["drawdown"] * candidate.expected_dd_pct
        - weights["cost"] * candidate.expected_cost_r
    )


def _candidate_reasons(candidate: TeamRouteCandidate, policy: RouterPolicy) -> tuple[str, ...]:
    reasons: list[str] = list(_source_reasons(candidate.source_ids, f"CANDIDATE_{candidate.team_id}"))
    if candidate.data_state != "FRESH":
        reasons.append(f"CANDIDATE_{candidate.team_id}_DATA_NOT_FRESH")
    if not candidate.evidence_ids:
        reasons.append(f"CANDIDATE_{candidate.team_id}_EVIDENCE_MISSING")
    if not candidate.role_ready:
        reasons.append(f"CANDIDATE_{candidate.team_id}_ROLE_NOT_READY")
    if not candidate.confidence_ready:
        reasons.append(f"CANDIDATE_{candidate.team_id}_CONFIDENCE_NOT_READY")
    if candidate.expected_dd_pct > policy.maximum_candidate_dd_pct:
        reasons.append(f"CANDIDATE_{candidate.team_id}_DD_ABOVE_SSOT_MAX")
    reasons.extend(candidate.reason_codes)
    return tuple(dict.fromkeys(reasons))


def _regime_eligible(candidate: TeamRouteCandidate, policy: RouterPolicy) -> tuple[bool, tuple[str, ...]]:
    team_policy = TEAM_POLICY_REGISTRY[candidate.team_id]
    if candidate.observed_regime in policy.defense_override_regimes and candidate.team_id != "DeltaTeam":
        return False, (f"CANDIDATE_{candidate.team_id}_DEFENSE_OVERRIDE",)
    if candidate.observed_regime in team_policy.excluded_regimes:
        return False, (f"CANDIDATE_{candidate.team_id}_REGIME_EXCLUDED",)
    if candidate.observed_regime not in team_policy.eligible_regimes:
        return False, (f"CANDIDATE_{candidate.team_id}_REGIME_NOT_ELIGIBLE",)
    return True, ()


def route_teams(request: TeamRouterRequest) -> TeamRouteEnvelope:
    reasons: list[str] = list(_source_reasons(request.source_ids, "REQUEST"))
    reasons.extend(_source_reasons(request.policy.source_ids, "POLICY"))
    if request.data_state != "FRESH":
        reasons.append("ROUTER_DATA_NOT_FRESH")
    if not request.evidence_ids:
        reasons.append("ROUTER_EVIDENCE_IDS_MISSING")

    hard_veto = any(candidate.hard_veto for candidate in request.candidates)
    if hard_veto:
        reasons.append("ROUTER_SBOT_HARD_VETO")

    ranked: list[RankedTeam] = []
    integrity_failure = False
    for candidate in request.candidates:
        candidate_reasons = list(_candidate_reasons(candidate, request.policy))
        eligible, regime_reasons = _regime_eligible(candidate, request.policy)
        candidate_reasons.extend(regime_reasons)
        hard_candidate_reasons = tuple(
            reason
            for reason in candidate_reasons
            if not reason.endswith("REGIME_NOT_ELIGIBLE")
            and not reason.endswith("REGIME_EXCLUDED")
            and not reason.endswith("DEFENSE_OVERRIDE")
        )
        integrity_failure = integrity_failure or bool(hard_candidate_reasons)
        ranked.append(
            RankedTeam(
                team_id=candidate.team_id,
                observed_regime=candidate.observed_regime,
                eligible=eligible and not hard_candidate_reasons and not candidate.hard_veto,
                score=_candidate_score(candidate, request.policy),
                calibrated_confidence=candidate.calibrated_confidence,
                expected_net_r=candidate.expected_net_r,
                expected_dd_pct=candidate.expected_dd_pct,
                expected_cost_r=candidate.expected_cost_r,
                counterfactual_uplift_r=candidate.expected_net_r - request.no_team_expected_net_r,
                reason_codes=tuple(dict.fromkeys(candidate_reasons)),
            )
        )

    if integrity_failure:
        reasons.append("ROUTER_CANDIDATE_INTEGRITY_FAILURE")

    ordered = tuple(
        sorted(
            ranked,
            key=lambda item: (item.eligible, item.score, item.calibrated_confidence, item.team_id),
            reverse=True,
        )
    )
    eligible_teams = tuple(item for item in ordered if item.eligible)
    selected = eligible_teams[0] if eligible_teams else None
    score_margin: float | None = None
    uplift: float | None = None

    if selected is None:
        reasons.append("ROUTER_NO_ELIGIBLE_TEAM")
    else:
        no_team_score = request.policy.score_weights["net_r"] * request.no_team_expected_net_r
        comparison_score = eligible_teams[1].score if len(eligible_teams) > 1 else no_team_score
        score_margin = selected.score - comparison_score
        uplift = selected.counterfactual_uplift_r
        if score_margin < request.policy.minimum_score_margin:
            reasons.append("ROUTER_SCORE_MARGIN_BELOW_SSOT_MINIMUM")
        if uplift < request.policy.minimum_counterfactual_uplift_r:
            reasons.append("ROUTER_COUNTERFACTUAL_UPLIFT_BELOW_SSOT_MINIMUM")

    hard_prefixes = (
        "REQUEST_",
        "POLICY_",
        "ROUTER_DATA_",
        "ROUTER_EVIDENCE_",
        "ROUTER_CANDIDATE_",
        "ROUTER_NO_",
        "ROUTER_SCORE_",
        "ROUTER_COUNTERFACTUAL_",
        "ROUTER_SBOT_",
    )
    fail_closed = any(reason.startswith(hard_prefixes) for reason in reasons)
    decision_ready = not fail_closed and selected is not None

    return TeamRouteEnvelope(
        route_id=_route_id(request),
        selected_team=selected.team_id if decision_ready and selected else None,
        ranked_teams=ordered,
        decision_ready=decision_ready,
        fail_closed=fail_closed,
        abstain=fail_closed,
        hard_veto=hard_veto,
        action="block" if hard_veto else "hold",
        score_margin=score_margin,
        counterfactual_uplift_r=uplift,
        reason_codes=tuple(dict.fromkeys(reasons)),
        source_ids=request.source_ids,
        evidence_ids=request.evidence_ids,
        policy_id=request.policy.policy_id,
    )


def validate_router_contract() -> tuple[str, ...]:
    errors: list[str] = []
    if set(TEAM_POLICY_REGISTRY) != {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}:
        errors.append("ROUTER_TEAM_SET_INVALID")
    if REMAINING_SHARED_GAPS:
        errors.append("ROUTER_SHARED_GAPS_NOT_CLOSED")
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        if not policy.eligible_regimes:
            errors.append(f"{team_id}:ROUTER_ELIGIBLE_REGIME_EMPTY")
        if policy.authority != "advisory_only" or policy.runtime_enabled or policy.execution_authority != "none":
            errors.append(f"{team_id}:ROUTER_AUTHORITY_INVALID")
    return tuple(errors)
