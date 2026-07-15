from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Final

from canonical.zlice import ZliceEvent

ZICO_CONTROL_VERSION: Final = "zico-control/1.0.0"
ALLOWED_ACTIONS: Final = frozenset({
    "reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"
})


class ZicoState(str, Enum):
    RECEIVED = "received"
    EVIDENCE_BOUND = "evidence_bound"
    TEAM_RESOLVED = "team_resolved"
    ADVISOR_REVIEWED = "advisor_reviewed"
    ADMISSION_DECIDED = "admission_decided"
    OPEN_REQUESTED = "open_requested"
    OPEN_CONFIRMED = "open_confirmed"
    MANAGING = "managing"
    CLOSE_REQUESTED = "close_requested"
    CLOSED_VERIFIED = "closed_verified"
    HELD = "held"
    BLOCKED = "blocked"
    ROLLED_BACK = "rolled_back"


ALLOWED_TRANSITIONS: Final[dict[ZicoState, frozenset[ZicoState]]] = {
    ZicoState.RECEIVED: frozenset({ZicoState.EVIDENCE_BOUND, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.EVIDENCE_BOUND: frozenset({ZicoState.TEAM_RESOLVED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.TEAM_RESOLVED: frozenset({ZicoState.ADVISOR_REVIEWED, ZicoState.ADMISSION_DECIDED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.ADVISOR_REVIEWED: frozenset({ZicoState.ADMISSION_DECIDED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.ADMISSION_DECIDED: frozenset({ZicoState.OPEN_REQUESTED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.OPEN_REQUESTED: frozenset({ZicoState.OPEN_CONFIRMED, ZicoState.HELD, ZicoState.BLOCKED, ZicoState.ROLLED_BACK}),
    ZicoState.OPEN_CONFIRMED: frozenset({ZicoState.MANAGING, ZicoState.CLOSE_REQUESTED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.MANAGING: frozenset({ZicoState.CLOSE_REQUESTED, ZicoState.HELD, ZicoState.BLOCKED}),
    ZicoState.CLOSE_REQUESTED: frozenset({ZicoState.CLOSED_VERIFIED, ZicoState.HELD, ZicoState.BLOCKED, ZicoState.ROLLED_BACK}),
    ZicoState.HELD: frozenset({ZicoState.EVIDENCE_BOUND, ZicoState.BLOCKED}),
    ZicoState.CLOSED_VERIFIED: frozenset(),
    ZicoState.BLOCKED: frozenset(),
    ZicoState.ROLLED_BACK: frozenset(),
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}.{digest[:32]}"


@dataclass(frozen=True, slots=True)
class ZicoControlRequest:
    decision_id: str
    position_id: str
    event_id: str
    parent_event_id: str
    event_ts: str
    current_state: ZicoState
    target_state: ZicoState
    action: str
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    idempotency_key: str
    integrity_ok: bool = True
    data_fresh: bool = True
    contract_version: str = ZICO_CONTROL_VERSION

    def __post_init__(self) -> None:
        required = {
            "decision_id": self.decision_id,
            "position_id": self.position_id,
            "event_id": self.event_id,
            "event_ts": self.event_ts,
            "idempotency_key": self.idempotency_key,
        }
        missing = sorted(name for name, value in required.items() if not str(value or "").strip())
        if missing:
            raise ValueError(f"ZICO_REQUEST_FIELDS_MISSING:{','.join(missing)}")
        if self.action not in ALLOWED_ACTIONS:
            raise ValueError("ZICO_ACTION_INVALID")
        if self.contract_version != ZICO_CONTROL_VERSION:
            raise ValueError("ZICO_CONTROL_VERSION_MISMATCH")
        object.__setattr__(self, "reason_codes", tuple(dict.fromkeys(str(v) for v in self.reason_codes if str(v))))
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(str(v) for v in self.evidence_ids if str(v))))
        object.__setattr__(self, "source_ids", tuple(dict.fromkeys(str(v) for v in self.source_ids if str(v))))


@dataclass(frozen=True, slots=True)
class ZicoControlResult:
    decision_id: str
    position_id: str
    from_state: ZicoState
    to_state: ZicoState
    action: str
    reason_codes: tuple[str, ...]
    idempotency_key: str
    request_fingerprint: str
    replayed: bool
    evidence_event: ZliceEvent | None
    authority: str = "control_validation_only"
    execution_authority: str = "none"
    runtime_enabled: bool = False
    contract_version: str = ZICO_CONTROL_VERSION


class IdempotencyConflict(ValueError):
    pass


class InMemoryIdempotencyRegistry:
    """Package-level proof store only. Runtime persistence is deferred to R7."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, ZicoControlResult]] = {}

    def lookup(self, key: str, fingerprint: str) -> ZicoControlResult | None:
        existing = self._entries.get(key)
        if existing is None:
            return None
        existing_fingerprint, result = existing
        if existing_fingerprint != fingerprint:
            raise IdempotencyConflict("ZICO_IDEMPOTENCY_KEY_PAYLOAD_CONFLICT")
        return replace(result, replayed=True, evidence_event=None)

    def record(self, key: str, fingerprint: str, result: ZicoControlResult) -> None:
        if key in self._entries:
            raise IdempotencyConflict("ZICO_IDEMPOTENCY_KEY_ALREADY_RECORDED")
        self._entries[key] = (fingerprint, result)

    @property
    def size(self) -> int:
        return len(self._entries)


class ZicoMinimalController:
    def __init__(self, registry: InMemoryIdempotencyRegistry | None = None) -> None:
        self.registry = registry or InMemoryIdempotencyRegistry()

    @staticmethod
    def _fingerprint(request: ZicoControlRequest) -> str:
        payload = asdict(request)
        payload["current_state"] = request.current_state.value
        payload["target_state"] = request.target_state.value
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    @staticmethod
    def _resolved_transition(request: ZicoControlRequest) -> tuple[ZicoState, str, tuple[str, ...]]:
        reasons = list(request.reason_codes)
        if not request.integrity_ok:
            reasons.append("INTEGRITY_FAIL_CLOSED")
            return ZicoState.HELD, "hold", tuple(dict.fromkeys(reasons))
        if not request.data_fresh:
            reasons.append("DATA_STALE_FAIL_CLOSED")
            return ZicoState.HELD, "hold", tuple(dict.fromkeys(reasons))
        if not request.evidence_ids:
            reasons.append("EVIDENCE_MISSING_FAIL_CLOSED")
            return ZicoState.HELD, "hold", tuple(dict.fromkeys(reasons))
        return request.target_state, request.action, tuple(dict.fromkeys(reasons))

    def decide(self, request: ZicoControlRequest, *, sequence_no: int) -> ZicoControlResult:
        if sequence_no < 0:
            raise ValueError("ZICO_SEQUENCE_INVALID")
        fingerprint = self._fingerprint(request)
        replay = self.registry.lookup(request.idempotency_key, fingerprint)
        if replay is not None:
            return replay

        target, action, reasons = self._resolved_transition(request)
        if target not in ALLOWED_TRANSITIONS[request.current_state]:
            raise ValueError(f"ZICO_TRANSITION_INVALID:{request.current_state.value}->{target.value}")

        payload = {
            "decision_id": request.decision_id,
            "position_id": request.position_id,
            "from_state": request.current_state.value,
            "to_state": target.value,
            "action": action,
            "reason_codes": reasons,
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": fingerprint,
        }
        payload_hash = hashlib.sha256(_canonical_json(payload)).hexdigest()
        event = ZliceEvent(
            event_id=_stable_id("zlice.zico", request.idempotency_key, fingerprint),
            parent_event_id=request.parent_event_id,
            decision_id=request.decision_id,
            position_id=request.position_id,
            event_type="zico_gate_decided",
            event_ts=request.event_ts,
            producer_id="ZicoMinimalController",
            producer_version=ZICO_CONTROL_VERSION,
            attribution_id=_stable_id("zico.attr", request.decision_id, request.position_id),
            payload_hash=payload_hash,
            source_ids=request.source_ids,
            sequence_no=sequence_no,
            metadata={
                "from_state": request.current_state.value,
                "to_state": target.value,
                "action": action,
                "idempotency_key": request.idempotency_key,
                "request_fingerprint": fingerprint,
                "evidence_ids": ",".join(request.evidence_ids),
            },
        )
        result = ZicoControlResult(
            decision_id=request.decision_id,
            position_id=request.position_id,
            from_state=request.current_state,
            to_state=target,
            action=action,
            reason_codes=reasons,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            replayed=False,
            evidence_event=event,
        )
        self.registry.record(request.idempotency_key, fingerprint, result)
        return result
