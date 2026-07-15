from __future__ import annotations

from types import MappingProxyType
from .models import TeamSpec

ALPHA = TeamSpec("AlphaTeam", "trend_primary_continuation", "LBot", "MBot", ("OBot", "SBot"), "ZBot", ("MBot", "OBot"), ("pullback_retest", "method_conflict", "momentum_exhaustion"))
BETA = TeamSpec("BetaTeam", "range_method_mean_reversion", "MBot", "LBot", ("OBot", "SBot"), "ZBot", ("LBot", "OBot"), ("range_extreme", "fake_breakout", "directional_bias_conflict"))
GAMMA = TeamSpec("GammaTeam", "breakout_momentum_acceleration", "OBot", "MBot", ("LBot", "SBot"), "ZBot", ("LBot", "MBot"), ("volume_expansion", "retest_required", "breakout_quality_conflict"))
DELTA = TeamSpec("DeltaTeam", "defense_regime_shift_capital_preservation", "SBot", "OBot", ("MBot", "LBot"), "ZBot", ("OBot", "MBot", "LBot"), ("regime_shift", "recovery_route", "reduce_or_rollback_conflict"), reserve="LBot")

TEAM_REGISTRY = MappingProxyType({spec.team_id: spec for spec in (ALPHA, BETA, GAMMA, DELTA)})


def validate_registry() -> tuple[str, ...]:
    errors: list[str] = []
    if set(TEAM_REGISTRY) != {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}:
        errors.append("TEAM_SET_INVALID")
    if {spec.main for spec in TEAM_REGISTRY.values()} != {"LBot", "MBot", "OBot", "SBot"}:
        errors.append("MAIN_ROTATION_INVALID")
    for team_id, spec in TEAM_REGISTRY.items():
        errors.extend(f"{team_id}:{item}" for item in spec.validate())
    return tuple(errors)
