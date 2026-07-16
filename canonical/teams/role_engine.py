from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from .policy_contracts import CANONICAL_SOURCES, TEAM_POLICY_REGISTRY

BotName = Literal["LBot", "MBot", "OBot", "SBot"]
TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]

ROLE_ENGINE_VERSION = "team-role-engine/1.0.0"
BOT_NAMES = frozenset({"LBot", "MBot", "OBot", "SBot"})
REMAINING_SHARED_GAPS = (
    "confidence_calibration",
    "counterfactual_team_selection",
    "regime_eligibility_engine",
    "team_router_ranking",
    "watcher_severity_aggregation",
)


def _assignment_id(request: "RoleAssignmentRequest") -> str:
    raw = "|".join(
        (
            request.team_id,
            request.regime,
            ",".join(request.active_triggers),
            ",".join(request.unavailable_bots),
            request.data_state,
            ",".join(request.source_ids),
            ",".join(request.evidence_ids),
        )
    ).encode("utf-8")
    return f"role.{hashlib.sha256(raw).hexdigest()[:24]}"


def _source_state(source_ids: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not source_ids:
        return False, ("ROLE_SOURCE_IDS_MISSING",)
    invalid = tuple(source for source in source_ids if not source.startswith(CANONICAL_SOURCES))
    if invalid:
        reasons.append("ROLE_SOURCE_PREFIX_INVALID")
    has_cf = any(source.startswith("cf:") for source in source_ids)
    has_sheets = any(source.startswith("sheets:") for source in source_ids)
    if not has_cf or not has_sheets:
        reasons.append("ROLE_CF_SHEETS_PARITY_MISSING")
    return not reasons, tuple(reasons)


@dataclass(frozen=True, slots=True)
class RoleAssignmentRequest:
    team_id: TeamName
    regime: str
    active_triggers: tuple[str, ...] = field(default_factory=tuple)
    unavailable_bots: tuple[BotName, ...] = field(default_factory=tuple)
    data_state: str = "FRESH"
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.team_id not in TEAM_POLICY_REGISTRY:
            raise ValueError("TEAM_ID_INVALID")
        if not self.regime:
            raise ValueError("REGIME_REQUIRED")
        if len(set(self.active_triggers)) != len(self.active_triggers):
            raise ValueError("DUPLICATE_TRIGGER")
        if len(set(self.unavailable_bots)) != len(self.unavailable_bots):
            raise ValueError("DUPLICATE_UNAVAILABLE_BOT")
        if not set(self.unavailable_bots).issubset(BOT_NAMES):
            raise ValueError("UNAVAILABLE_BOT_INVALID")


@dataclass(frozen=True, slots=True)
class RoleAssignmentPlan:
    assignment_id: str
    team_id: TeamName
    mode: str
    canonical_main: BotName
    canonical_support: BotName
    effective_main: BotName
    effective_support: BotName
    active_watchers: tuple[BotName, ...]
    helper: BotName | None
    helper_trigger: str | None
    reserve_owner: BotName | None
    reserve_used: bool
    decision_ready: bool
    fail_closed: bool
    action: str
    abstain: bool
    reason_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = ROLE_ENGINE_VERSION

    def binding_helper(self) -> tuple[BotName | None, str | None]:
        if not self.decision_ready:
            return None, None
        return self.helper, self.helper_trigger


def assign_team_roles(request: RoleAssignmentRequest) -> RoleAssignmentPlan:
    policy = TEAM_POLICY_REGISTRY[request.team_id]
    unavailable = set(request.unavailable_bots)
    reasons: list[str] = []
    mode = "canonical"
    effective_main = policy.main_owner
    effective_support = policy.support_owner
    watchers = tuple(policy.watcher_priorities)
    helper: BotName | None = None
    helper_trigger: str | None = None
    reserve_used = False

    source_ok, source_reasons = _source_state(request.source_ids)
    reasons.extend(source_reasons)
    if request.data_state != "FRESH":
        reasons.append("ROLE_DATA_NOT_FRESH")
    if not request.evidence_ids:
        reasons.append("ROLE_EVIDENCE_IDS_MISSING")

    unknown_triggers = tuple(
        trigger for trigger in request.active_triggers if trigger not in policy.helper_trigger_map
    )
    if unknown_triggers:
        reasons.append("ROLE_HELPER_TRIGGER_UNKNOWN")

    known_active = tuple(
        trigger for trigger in policy.helper_trigger_map if trigger in request.active_triggers
    )
    if known_active:
        helper_trigger = known_active[0]
        helper = policy.helper_trigger_map[helper_trigger]
        mode = "helper_assisted"
        if len(known_active) > 1:
            reasons.append("ROLE_MULTIPLE_HELPER_TRIGGERS_PRIORITIZED")
        if helper in unavailable:
            reasons.append("ROLE_REQUIRED_HELPER_UNAVAILABLE")

    if policy.support_owner in unavailable:
        reasons.append("ROLE_SUPPORT_UNAVAILABLE")

    missing_watchers = tuple(bot for bot in watchers if bot in unavailable)
    if missing_watchers:
        reasons.append("ROLE_WATCHER_COVERAGE_DEGRADED")

    if policy.main_owner in unavailable:
        if request.team_id == "DeltaTeam" and policy.reserve_owner and policy.reserve_owner not in unavailable:
            effective_main = policy.reserve_owner
            reserve_used = True
            mode = "reserve_recovery"
            reasons.append("ROLE_DELTA_RESERVE_RECOVERY_HOLD")
        else:
            reasons.append("ROLE_MAIN_UNAVAILABLE")

    hard_reasons = {
        "ROLE_SOURCE_IDS_MISSING",
        "ROLE_SOURCE_PREFIX_INVALID",
        "ROLE_CF_SHEETS_PARITY_MISSING",
        "ROLE_DATA_NOT_FRESH",
        "ROLE_EVIDENCE_IDS_MISSING",
        "ROLE_HELPER_TRIGGER_UNKNOWN",
        "ROLE_REQUIRED_HELPER_UNAVAILABLE",
        "ROLE_SUPPORT_UNAVAILABLE",
        "ROLE_WATCHER_COVERAGE_DEGRADED",
        "ROLE_MAIN_UNAVAILABLE",
        "ROLE_DELTA_RESERVE_RECOVERY_HOLD",
    }
    hard_fail = any(reason in hard_reasons for reason in reasons)
    decision_ready = source_ok and not hard_fail
    fail_closed = not decision_ready

    return RoleAssignmentPlan(
        assignment_id=_assignment_id(request),
        team_id=request.team_id,
        mode=mode,
        canonical_main=policy.main_owner,
        canonical_support=policy.support_owner,
        effective_main=effective_main,
        effective_support=effective_support,
        active_watchers=watchers,
        helper=helper,
        helper_trigger=helper_trigger,
        reserve_owner=policy.reserve_owner,
        reserve_used=reserve_used,
        decision_ready=decision_ready,
        fail_closed=fail_closed,
        action="hold",
        abstain=fail_closed,
        reason_codes=tuple(dict.fromkeys(reasons)),
        source_ids=request.source_ids,
        evidence_ids=request.evidence_ids,
    )


def validate_role_engine_contract() -> tuple[str, ...]:
    errors: list[str] = []
    if set(TEAM_POLICY_REGISTRY) != {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}:
        errors.append("ROLE_ENGINE_TEAM_SET_INVALID")
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        if policy.authority != "advisory_only" or policy.runtime_enabled or policy.execution_authority != "none":
            errors.append(f"{team_id}:ROLE_ENGINE_AUTHORITY_INVALID")
        if not policy.helper_trigger_map:
            errors.append(f"{team_id}:ROLE_ENGINE_HELPER_MAP_EMPTY")
    if TEAM_POLICY_REGISTRY["DeltaTeam"].reserve_owner != "LBot":
        errors.append("DELTA_RESERVE_OWNER_INVALID")
    return tuple(errors)
