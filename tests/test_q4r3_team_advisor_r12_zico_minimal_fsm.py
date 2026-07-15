from __future__ import annotations

import pytest

from canonical.zico import (
    IdempotencyConflict,
    InMemoryIdempotencyRegistry,
    ZicoControlRequest,
    ZicoMinimalController,
    ZicoState,
)


def request(**changes: object) -> ZicoControlRequest:
    value = {
        "decision_id": "decision.r12",
        "position_id": "position.r12",
        "event_id": "event.r12",
        "parent_event_id": "event.parent",
        "event_ts": "2026-07-15T00:00:00+00:00",
        "current_state": ZicoState.RECEIVED,
        "target_state": ZicoState.EVIDENCE_BOUND,
        "action": "hold",
        "reason_codes": ("EVIDENCE_ACCEPTED",),
        "evidence_ids": ("evidence:r12",),
        "source_ids": ("src:r12",),
        "idempotency_key": "idem.r12.1",
        "integrity_ok": True,
        "data_fresh": True,
    }
    value.update(changes)
    return ZicoControlRequest(**value)


def test_valid_transition_emits_zlice_evidence() -> None:
    result = ZicoMinimalController().decide(request(), sequence_no=1)
    assert result.to_state is ZicoState.EVIDENCE_BOUND
    assert result.replayed is False
    assert result.evidence_event is not None
    assert result.evidence_event.event_type == "zico_gate_decided"
    assert result.evidence_event.execution_authority == "none"


def test_same_key_same_payload_is_idempotent() -> None:
    controller = ZicoMinimalController()
    first = controller.decide(request(), sequence_no=1)
    second = controller.decide(request(), sequence_no=2)
    assert first.request_fingerprint == second.request_fingerprint
    assert second.replayed is True
    assert second.evidence_event is None
    assert controller.registry.size == 1


def test_same_key_different_payload_is_conflict() -> None:
    controller = ZicoMinimalController()
    controller.decide(request(), sequence_no=1)
    with pytest.raises(IdempotencyConflict):
        controller.decide(request(action="block"), sequence_no=2)


def test_missing_evidence_fails_closed() -> None:
    result = ZicoMinimalController().decide(request(evidence_ids=()), sequence_no=1)
    assert result.to_state is ZicoState.HELD
    assert result.action == "hold"
    assert "EVIDENCE_MISSING_FAIL_CLOSED" in result.reason_codes


def test_stale_data_fails_closed() -> None:
    result = ZicoMinimalController().decide(request(data_fresh=False), sequence_no=1)
    assert result.to_state is ZicoState.HELD
    assert result.action == "hold"
    assert "DATA_STALE_FAIL_CLOSED" in result.reason_codes


def test_integrity_failure_fails_closed() -> None:
    result = ZicoMinimalController().decide(request(integrity_ok=False), sequence_no=1)
    assert result.to_state is ZicoState.HELD
    assert result.action == "hold"
    assert "INTEGRITY_FAIL_CLOSED" in result.reason_codes


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="ZICO_TRANSITION_INVALID"):
        ZicoMinimalController().decide(
            request(target_state=ZicoState.OPEN_CONFIRMED), sequence_no=1
        )


def test_terminal_state_cannot_transition() -> None:
    with pytest.raises(ValueError, match="ZICO_TRANSITION_INVALID"):
        ZicoMinimalController().decide(
            request(
                current_state=ZicoState.CLOSED_VERIFIED,
                target_state=ZicoState.EVIDENCE_BOUND,
            ),
            sequence_no=1,
        )


def test_registry_can_be_injected() -> None:
    registry = InMemoryIdempotencyRegistry()
    controller = ZicoMinimalController(registry)
    controller.decide(request(), sequence_no=1)
    assert registry.size == 1
