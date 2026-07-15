from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

ZLICE_CONTRACT_VERSION = "zlice-evidence/1.0.0"
ALLOWED_EVENT_TYPES = frozenset({
    "strategy_selected", "method_selected", "skill_selected", "bot_response_emitted",
    "team_proposal_emitted", "lico_context_applied", "zbot_advice_emitted",
    "zico_lease_state_cleaned", "zico_gate_decided", "position_opened",
    "position_closed", "outcome_joined", "counterfactual_evaluated",
})


@dataclass(frozen=True, slots=True)
class ZliceEvent:
    event_id: str
    parent_event_id: str
    decision_id: str
    position_id: str
    event_type: str
    event_ts: str
    producer_id: str
    producer_version: str
    attribution_id: str
    payload_hash: str
    source_ids: tuple[str, ...]
    sequence_no: int
    metadata: Mapping[str, str] = field(default_factory=dict)
    append_only: bool = True
    authority: str = "evidence_only"
    execution_authority: str = "none"
    contract_version: str = ZLICE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        required = {
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "position_id": self.position_id,
            "event_type": self.event_type,
            "event_ts": self.event_ts,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "attribution_id": self.attribution_id,
            "payload_hash": self.payload_hash,
        }
        missing = sorted(name for name, value in required.items() if not str(value or "").strip())
        if missing:
            raise ValueError(f"ZLICE_FIELDS_MISSING:{','.join(missing)}")
        if self.event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError("ZLICE_EVENT_TYPE_INVALID")
        if not isinstance(self.sequence_no, int) or isinstance(self.sequence_no, bool) or self.sequence_no < 0:
            raise ValueError("ZLICE_SEQUENCE_INVALID")
        if not self.append_only or self.authority != "evidence_only" or self.execution_authority != "none":
            raise ValueError("ZLICE_AUTHORITY_INVALID")
        if self.contract_version != ZLICE_CONTRACT_VERSION:
            raise ValueError("ZLICE_CONTRACT_VERSION_MISMATCH")
        object.__setattr__(self, "source_ids", tuple(str(value) for value in self.source_ids if str(value)))
        object.__setattr__(self, "metadata", dict(self.metadata))
