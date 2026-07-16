from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .policy_contracts import (
    DEFENSIVE_TEAM_ACTIONS,
    ORDINARY_TEAM_ACTIONS,
    TEAM_POLICY_REGISTRY,
    validate_team_policy_registry,
)
from .registry import TEAM_REGISTRY, validate_registry
from .role_engine import validate_role_engine_contract
from .router_counterfactual import (
    REMAINING_SHARED_GAPS as ROUTER_REMAINING_SHARED_GAPS,
    validate_router_contract,
)
from .watcher_confidence import validate_watcher_confidence_contract

TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]

TEAM_SGRADE_LOCK_VERSION = "team-sgrade-lock/1.0.0"
TEAM_NAMES = ("AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam")
REQUIRED_CAPABILITIES = (
    "distinct_policy_identity",
    "regime_eligibility",
    "dynamic_role_assignment",
    "conditional_helper",
    "safe_reserve_recovery",
    "watcher_severity",
    "confidence_calibration",
    "team_router_ranking",
    "counterfactual_selection",
    "fail_closed_integrity",
    "source_evidence_lineage",
    "authority_boundary",
)


@dataclass(frozen=True, slots=True)
class TeamSGradeProof:
    team_id: TeamName
    mission: str
    policy_family: str
    main_owner: str
    support_owner: str
    watcher_owners: tuple[str, ...]
    helper_triggers: tuple[str, ...]
    reserve_owner: str | None
    capability_hits: tuple[str, ...]
    reason_codes: tuple[str, ...]
    sgrade_ready: bool
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = TEAM_SGRADE_LOCK_VERSION

    def binding_team(self) -> TeamName | None:
        return self.team_id if self.sgrade_ready else None


def _global_errors() -> tuple[str, ...]:
    errors: list[str] = []
    errors.extend(f"REGISTRY:{item}" for item in validate_registry())
    errors.extend(f"POLICY:{item}" for item in validate_team_policy_registry())
    errors.extend(f"ROLE:{item}" for item in validate_role_engine_contract())
    errors.extend(f"WATCHER:{item}" for item in validate_watcher_confidence_contract())
    errors.extend(f"ROUTER:{item}" for item in validate_router_contract())

    if tuple(sorted(TEAM_REGISTRY)) != tuple(sorted(TEAM_NAMES)):
        errors.append("TEAM_SET_INVALID")
    if tuple(sorted(TEAM_POLICY_REGISTRY)) != tuple(sorted(TEAM_NAMES)):
        errors.append("TEAM_POLICY_SET_INVALID")
    if {spec.main for spec in TEAM_REGISTRY.values()} != {"LBot", "MBot", "OBot", "SBot"}:
        errors.append("MAIN_OWNER_ROTATION_INVALID")
    identities = {
        (policy.policy_family, policy.primary_objective, policy.eligible_regimes)
        for policy in TEAM_POLICY_REGISTRY.values()
    }
    if len(identities) != 4:
        errors.append("TEAM_POLICY_IDENTITY_COLLISION")
    if ROUTER_REMAINING_SHARED_GAPS:
        errors.append("TEAM_SHARED_GAPS_REMAIN")
    return tuple(dict.fromkeys(errors))


def _team_reasons(team_id: TeamName) -> tuple[str, ...]:
    spec = TEAM_REGISTRY[team_id]
    policy = TEAM_POLICY_REGISTRY[team_id]
    reasons: list[str] = []

    if spec.mission != policy.mission:
        reasons.append("MISSION_MISMATCH")
    if spec.main != policy.main_owner or spec.support != policy.support_owner:
        reasons.append("MAIN_SUPPORT_MISMATCH")
    if set(spec.watchers) != set(policy.watcher_priorities):
        reasons.append("WATCHER_SET_MISMATCH")
    if set(spec.helper_triggers) != set(policy.helper_trigger_map):
        reasons.append("HELPER_TRIGGER_MISMATCH")
    if not set(policy.helper_trigger_map.values()).issubset(set(spec.conditional_helpers)):
        reasons.append("HELPER_OWNER_INVALID")
    if spec.reserve != policy.reserve_owner:
        reasons.append("RESERVE_OWNER_MISMATCH")

    decision_roles = {spec.main, spec.support, *spec.watchers, *spec.conditional_helpers}
    if spec.external_proof_watcher != "ZBot" or "ZBot" in decision_roles:
        reasons.append("ZBOT_EXTERNAL_ONLY_BOUNDARY_INVALID")
    if spec.runtime_enabled or spec.paper_enabled or spec.live_enabled or spec.order_enabled:
        reasons.append("TEAM_RUNTIME_AUTHORITY_ENABLED")
    if spec.execution_authority != "none":
        reasons.append("TEAM_EXECUTION_AUTHORITY_INVALID")
    if policy.authority != "advisory_only" or policy.runtime_enabled:
        reasons.append("POLICY_AUTHORITY_INVALID")
    if policy.execution_authority != "none":
        reasons.append("POLICY_EXECUTION_AUTHORITY_INVALID")

    if team_id == "DeltaTeam":
        if policy.reserve_owner != "LBot":
            reasons.append("DELTA_RESERVE_INVALID")
        if policy.allowed_actions != DEFENSIVE_TEAM_ACTIONS:
            reasons.append("DELTA_ACTION_BOUNDARY_INVALID")
    else:
        if policy.reserve_owner is not None:
            reasons.append("ORDINARY_TEAM_RESERVE_FORBIDDEN")
        if policy.allowed_actions != ORDINARY_TEAM_ACTIONS:
            reasons.append("ORDINARY_ACTION_BOUNDARY_INVALID")

    if tuple(policy.threshold_source_prefixes) != ("cf:", "sheets:"):
        reasons.append("SOURCE_POLICY_INVALID")
    if not policy.eligible_regimes:
        reasons.append("ELIGIBLE_REGIME_EMPTY")
    return tuple(dict.fromkeys(reasons))


def build_team_sgrade_proofs() -> tuple[TeamSGradeProof, ...]:
    global_errors = _global_errors()
    proofs: list[TeamSGradeProof] = []
    for team_id in TEAM_NAMES:
        spec = TEAM_REGISTRY[team_id]
        policy = TEAM_POLICY_REGISTRY[team_id]
        reasons = tuple((*global_errors, *_team_reasons(team_id)))
        ready = not reasons
        proofs.append(
            TeamSGradeProof(
                team_id=team_id,  # type: ignore[arg-type]
                mission=policy.mission,
                policy_family=policy.policy_family,
                main_owner=policy.main_owner,
                support_owner=policy.support_owner,
                watcher_owners=tuple(policy.watcher_priorities),
                helper_triggers=tuple(policy.helper_trigger_map),
                reserve_owner=policy.reserve_owner,
                capability_hits=REQUIRED_CAPABILITIES if ready else (),
                reason_codes=reasons,
                sgrade_ready=ready,
            )
        )
    return tuple(proofs)


def validate_team_sgrade_lock_contract() -> tuple[str, ...]:
    errors: list[str] = list(_global_errors())
    proofs = build_team_sgrade_proofs()
    if len(proofs) != 4:
        errors.append("TEAM_PROOF_COUNT_INVALID")
    if sum(proof.sgrade_ready for proof in proofs) != 4:
        errors.append("TEAM_SGRADE_READY_COUNT_INVALID")
    for proof in proofs:
        if proof.reason_codes:
            errors.extend(f"{proof.team_id}:{item}" for item in proof.reason_codes)
        if proof.capability_hits != REQUIRED_CAPABILITIES:
            errors.append(f"{proof.team_id}:CAPABILITY_LOCK_INCOMPLETE")
        if proof.authority != "advisory_only" or proof.runtime_enabled:
            errors.append(f"{proof.team_id}:LOCK_AUTHORITY_INVALID")
        if proof.execution_authority != "none":
            errors.append(f"{proof.team_id}:LOCK_EXECUTION_AUTHORITY_INVALID")
    return tuple(dict.fromkeys(errors))
