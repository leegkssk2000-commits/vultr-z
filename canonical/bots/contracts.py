from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

CONTRACT_VERSION = "canonical-bot/1.0.0"
ALLOWED_ACTIONS = frozenset({
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
})
ALLOWED_DATA_STATES = frozenset({"FRESH", "DEGRADED", "STALE", "UNKNOWN"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tuple_text(values: Sequence[Any] | None) -> tuple[str, ...]:
    return tuple(item for item in (_text(value) for value in (values or ())) if item)


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class BotRequest:
    decision_id: str
    position_id: str
    event_id: str
    parent_event_id: str
    event_ts: str
    symbol: str
    side: str
    strategy_id: str
    method_id: str
    skill_id: str
    team_id: str
    team_role: str
    data_state: str
    freshness_ms: int
    role_evidence: Mapping[str, Any] = field(default_factory=dict)
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        required = {
            "decision_id": self.decision_id,
            "position_id": self.position_id,
            "event_id": self.event_id,
            "event_ts": self.event_ts,
            "symbol": self.symbol,
            "side": self.side,
            "strategy_id": self.strategy_id,
            "method_id": self.method_id,
            "skill_id": self.skill_id,
            "team_id": self.team_id,
            "team_role": self.team_role,
        }
        missing = sorted(name for name, value in required.items() if not _text(value))
        if missing:
            raise ValueError(f"MISSING_REQUIRED_FIELDS:{','.join(missing)}")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("CONTRACT_VERSION_MISMATCH")
        if self.data_state not in ALLOWED_DATA_STATES:
            raise ValueError("DATA_STATE_INVALID")
        if not isinstance(self.freshness_ms, int) or self.freshness_ms < 0:
            raise ValueError("FRESHNESS_MS_INVALID")
        object.__setattr__(self, "role_evidence", _frozen_mapping(self.role_evidence))
        object.__setattr__(self, "source_ids", _tuple_text(self.source_ids))
        object.__setattr__(self, "evidence_ids", _tuple_text(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class BotResponse:
    bot_id: str
    semantic_role: str
    decision_id: str
    position_id: str
    action: str
    confidence: float
    abstain: bool
    veto: bool
    reason_codes: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    freshness_ms: int
    authority: str = "advisory_only"
    direct_order_allowed: bool = False
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.action not in ALLOWED_ACTIONS:
            raise ValueError("ACTION_INVALID")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")
        if self.authority != "advisory_only" or self.direct_order_allowed is not False:
            raise ValueError("BOT_AUTHORITY_VIOLATION")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("CONTRACT_VERSION_MISMATCH")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "reason_codes", _tuple_text(self.reason_codes))
        object.__setattr__(self, "source_ids", _tuple_text(self.source_ids))
        object.__setattr__(self, "evidence_ids", _tuple_text(self.evidence_ids))
