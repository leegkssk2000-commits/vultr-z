from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, Tuple

from canonical.bots.contracts import ALLOWED_ACTIONS
from .registry import TEAM_REGISTRY

TeamName = Literal["AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"]
BotName = Literal["LBot", "MBot", "OBot", "SBot"]

TEAM_POLICY_VERSION = "team-policy/1.0.0"
CANONICAL_SOURCES = ("cf:", "sheets:")
ORDINARY_TEAM_ACTIONS = frozenset({"hold", "reduce25", "partial30", "route_change"})
DEFENSIVE_TEAM_ACTIONS = frozenset(ALLOWED_ACTIONS)


@dataclass(frozen=True, slots=True)
class TeamPolicyContract:
    team_id: TeamName
    mission: str
    policy_family: str
    primary_objective: str
    eligible_regimes: Tuple[str, ...]
    excluded_regimes: Tuple[str, ...]
    main_owner: BotName
    support_owner: BotName
    watcher_priorities: Mapping[BotName, Tuple[str, ...]]
    helper_trigger_map: Mapping[str, BotName]
    reserve_owner: BotName | None
    recovery_routes: Tuple[str, ...]
    allowed_actions: frozenset[str]
    threshold_source_prefixes: Tuple[str, ...] = CANONICAL_SOURCES
    authority: str = "advisory_only"
    runtime_enabled: bool = False
    execution_authority: str = "none"
    contract_version: str = TEAM_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "watcher_priorities", MappingProxyType(dict(self.watcher_priorities)))
        object.__setattr__(self, "helper_trigger_map", MappingProxyType(dict(self.helper_trigger_map)))

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        spec = TEAM_REGISTRY.get(self.team_id)
        if spec is None:
            return ("TEAM_NOT_REGISTERED",)
        if self.mission != spec.mission:
            errors.append("MISSION_MISMATCH")
        if self.main_owner != spec.main or self.support_owner != spec.support:
            errors.append("MAIN_SUPPORT_MISMATCH")
        if set(self.watcher_priorities) != set(spec.watchers):
            errors.append("WATCHER_SET_MISMATCH")
        if not self.policy_family or not self.primary_objective:
            errors.append("POLICY_IDENTITY_MISSING")
        if not self.eligible_regimes or set(self.eligible_regimes) & set(self.excluded_regimes):
            errors.append("REGIME_CONTRACT_INVALID")
        if not self.helper_trigger_map:
            errors.append("HELPER_TRIGGER_MAP_EMPTY")
        for trigger, helper in self.helper_trigger_map.items():
            if trigger not in spec.helper_triggers or helper not in spec.conditional_helpers:
                errors.append(f"HELPER_POLICY_INVALID:{trigger}:{helper}")
        if self.reserve_owner != spec.reserve:
            errors.append("RESERVE_OWNER_MISMATCH")
        if self.team_id == "DeltaTeam" and not self.recovery_routes:
            errors.append("DEFENSE_RECOVERY_ROUTE_EMPTY")
        if self.team_id != "DeltaTeam" and self.allowed_actions != ORDINARY_TEAM_ACTIONS:
            errors.append("ORDINARY_ACTION_BOUNDARY_INVALID")
        if self.team_id == "DeltaTeam" and self.allowed_actions != DEFENSIVE_TEAM_ACTIONS:
            errors.append("DEFENSIVE_ACTION_BOUNDARY_INVALID")
        if self.threshold_source_prefixes != CANONICAL_SOURCES:
            errors.append("SOURCE_POLICY_INVALID")
        if self.authority != "advisory_only" or self.runtime_enabled or self.execution_authority != "none":
            errors.append("AUTHORITY_BOUNDARY_INVALID")
        if self.contract_version != TEAM_POLICY_VERSION:
            errors.append("CONTRACT_VERSION_INVALID")
        return tuple(errors)


ALPHA_POLICY = TeamPolicyContract(
    team_id="AlphaTeam",
    mission="trend_primary_continuation",
    policy_family="trend_continuation",
    primary_objective="capture_persistent_direction_without_chasing_exhaustion",
    eligible_regimes=("trend", "trend_transition"),
    excluded_regimes=("range", "high_noise", "capital_stress"),
    main_owner="LBot",
    support_owner="MBot",
    watcher_priorities={
        "OBot": ("momentum", "fakeout", "exhaustion", "mfe_mae"),
        "SBot": ("stop", "drawdown", "exposure", "buffer", "stale"),
    },
    helper_trigger_map={
        "pullback_retest": "MBot",
        "method_conflict": "MBot",
        "momentum_exhaustion": "OBot",
    },
    reserve_owner=None,
    recovery_routes=("hold", "route_change"),
    allowed_actions=ORDINARY_TEAM_ACTIONS,
)

BETA_POLICY = TeamPolicyContract(
    team_id="BetaTeam",
    mission="range_method_mean_reversion",
    policy_family="range_mean_reversion",
    primary_objective="trade_range_extremes_only_when_directional_contamination_is_bounded",
    eligible_regimes=("range", "compressed_range", "mean_reversion"),
    excluded_regimes=("strong_trend", "breakout_acceleration", "capital_stress"),
    main_owner="MBot",
    support_owner="LBot",
    watcher_priorities={
        "OBot": ("fakeout", "breakout", "anomaly", "mfe_mae"),
        "SBot": ("stop", "drawdown", "exposure", "buffer", "stale"),
    },
    helper_trigger_map={
        "range_extreme": "OBot",
        "fake_breakout": "OBot",
        "directional_bias_conflict": "LBot",
    },
    reserve_owner=None,
    recovery_routes=("hold", "route_change"),
    allowed_actions=ORDINARY_TEAM_ACTIONS,
)

GAMMA_POLICY = TeamPolicyContract(
    team_id="GammaTeam",
    mission="breakout_momentum_acceleration",
    policy_family="breakout_acceleration",
    primary_objective="capture_confirmed_expansion_while_rejecting_fakeout_and_failed_retest",
    eligible_regimes=("breakout", "volatility_expansion", "momentum_acceleration"),
    excluded_regimes=("low_volume_range", "failed_breakout", "capital_stress"),
    main_owner="OBot",
    support_owner="MBot",
    watcher_priorities={
        "LBot": ("trend", "continuation", "invalidation", "conflict"),
        "SBot": ("stop", "drawdown", "exposure", "buffer", "stale"),
    },
    helper_trigger_map={
        "volume_expansion": "LBot",
        "retest_required": "MBot",
        "breakout_quality_conflict": "LBot",
    },
    reserve_owner=None,
    recovery_routes=("hold", "route_change"),
    allowed_actions=ORDINARY_TEAM_ACTIONS,
)

DELTA_POLICY = TeamPolicyContract(
    team_id="DeltaTeam",
    mission="defense_regime_shift_capital_preservation",
    policy_family="capital_preservation",
    primary_objective="preserve_capital_and_restore_safe_routing_during_regime_or_execution_stress",
    eligible_regimes=("capital_stress", "regime_shift", "execution_degradation", "recovery"),
    excluded_regimes=(),
    main_owner="SBot",
    support_owner="OBot",
    watcher_priorities={
        "MBot": ("method", "conflict", "helper"),
        "LBot": ("invalidation", "conflict", "hysteresis"),
    },
    helper_trigger_map={
        "regime_shift": "LBot",
        "recovery_route": "OBot",
        "reduce_or_rollback_conflict": "MBot",
    },
    reserve_owner="LBot",
    recovery_routes=("reduce25", "partial30", "route_change", "rollback", "stop", "block"),
    allowed_actions=DEFENSIVE_TEAM_ACTIONS,
)

TEAM_POLICY_REGISTRY = MappingProxyType({
    policy.team_id: policy
    for policy in (ALPHA_POLICY, BETA_POLICY, GAMMA_POLICY, DELTA_POLICY)
})


def validate_team_policy_registry() -> tuple[str, ...]:
    errors: list[str] = []
    if set(TEAM_POLICY_REGISTRY) != set(TEAM_REGISTRY):
        errors.append("TEAM_POLICY_SET_INVALID")
    identities = {
        (policy.policy_family, policy.primary_objective, policy.eligible_regimes)
        for policy in TEAM_POLICY_REGISTRY.values()
    }
    if len(identities) != 4:
        errors.append("TEAM_POLICY_IDENTITY_COLLISION")
    for team_id, policy in TEAM_POLICY_REGISTRY.items():
        errors.extend(f"{team_id}:{error}" for error in policy.validate())
    return tuple(errors)
