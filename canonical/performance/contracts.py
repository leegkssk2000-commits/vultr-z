from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

PERFORMANCE_CONTRACT_VERSION = "performance-attribution/1.0.0"


@dataclass(frozen=True, slots=True)
class ComponentRef:
    component_type: str
    component_id: str
    version: str
    trace_id: str
    mode: str = "observer"

    def __post_init__(self) -> None:
        required = (self.component_type, self.component_id, self.version, self.trace_id, self.mode)
        if any(not str(value or "").strip() for value in required):
            raise ValueError("COMPONENT_REF_REQUIRED_FIELD_MISSING")
        if self.mode not in {"baseline", "observer", "advisor", "control", "evidence"}:
            raise ValueError("COMPONENT_REF_MODE_INVALID")


@dataclass(frozen=True, slots=True)
class AttributionEnvelope:
    attribution_id: str
    decision_id: str
    position_id: str
    event_id: str
    strategy_id: str
    method_id: str
    skill_id: str
    team_id: str
    policy_variant_id: str
    counterfactual_cohort_id: str
    component_refs: tuple[ComponentRef, ...]
    dimensions: Mapping[str, str] = field(default_factory=dict)
    contract_version: str = PERFORMANCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        required = {
            "attribution_id": self.attribution_id,
            "decision_id": self.decision_id,
            "position_id": self.position_id,
            "event_id": self.event_id,
            "strategy_id": self.strategy_id,
            "method_id": self.method_id,
            "skill_id": self.skill_id,
            "team_id": self.team_id,
            "policy_variant_id": self.policy_variant_id,
            "counterfactual_cohort_id": self.counterfactual_cohort_id,
        }
        missing = sorted(name for name, value in required.items() if not str(value or "").strip())
        if missing:
            raise ValueError(f"ATTRIBUTION_FIELDS_MISSING:{','.join(missing)}")
        if self.contract_version != PERFORMANCE_CONTRACT_VERSION:
            raise ValueError("PERFORMANCE_CONTRACT_VERSION_MISMATCH")
        keys = [(item.component_type, item.component_id, item.trace_id) for item in self.component_refs]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_COMPONENT_REF")
        object.__setattr__(self, "dimensions", dict(self.dimensions))
