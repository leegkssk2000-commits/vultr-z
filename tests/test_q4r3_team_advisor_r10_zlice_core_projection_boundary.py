from __future__ import annotations

import json
from pathlib import Path

import pytest

from canonical.performance.evaluator import FormalLedgerOutcomeView, ReadOnlyPerformanceEvaluator
from canonical.zlice.contracts import ZliceEvent
from canonical.zlice.ledger import ZliceLedger
from canonical.zlice.projection import ZliceProjection

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "config/q4r3_zlice_architecture_v1.json"


def event(
    sequence_no: int,
    event_id: str,
    event_type: str,
    parent_event_id: str,
    *,
    position_id: str = "position.r10",
) -> ZliceEvent:
    return ZliceEvent(
        event_id=event_id,
        parent_event_id=parent_event_id,
        decision_id="decision.r10",
        position_id=position_id,
        event_type=event_type,
        event_ts=f"2026-07-15T00:00:0{sequence_no}+00:00",
        producer_id="R10TestProducer",
        producer_version="r10-test/1.0.0",
        attribution_id="attr.r10",
        payload_hash=str(sequence_no) * 64,
        source_ids=("src:r10",),
        sequence_no=sequence_no,
        metadata={"mode": "test"},
    )


def ledger() -> ZliceLedger:
    value = ZliceLedger()
    value.append(event(0, "event.strategy", "strategy_selected", ""))
    value.append(event(1, "event.team", "team_proposal_emitted", "event.strategy"))
    value.append(event(2, "event.closed", "position_closed", "event.team"))
    return value


def test_architecture_preserves_existing_ui_and_new_core() -> None:
    architecture = json.loads(ARCHITECTURE.read_text(encoding="utf-8"))
    assert architecture["layers"]["core"]["role"] == "append_only_evidence_hash_chain_lineage_and_replay_source"
    assert architecture["layers"]["projection"]["role"] == "read_only_proof_capsule_receipt_archive_and_replay_drawer"
    assert architecture["layers"]["performance_evaluator"]["zlice_member"] is False
    assert architecture["ui_contract"]["existing_surface_preserved"] is True
    assert architecture["ssot_contract"]["formal_ledger_remains_pnl_ssot"] is True
    assert architecture["ssot_contract"]["zlice_is_second_pnl_ledger"] is False


def test_append_only_hash_chain_and_replay() -> None:
    value = ledger()
    snapshot = value.snapshot()
    assert value.verify() is True
    assert len(snapshot.records) == 3
    assert snapshot.records[0].previous_hash == "0" * 64
    assert snapshot.records[1].previous_hash == snapshot.records[0].record_hash
    assert snapshot.records[2].previous_hash == snapshot.records[1].record_hash
    assert snapshot.head_hash == snapshot.records[-1].record_hash


def test_duplicate_event_is_blocked() -> None:
    value = ledger()
    with pytest.raises(ValueError, match="ZLICE_DUPLICATE_EVENT_ID"):
        value.append(event(3, "event.closed", "outcome_joined", "event.closed"))


def test_sequence_gap_is_blocked() -> None:
    value = ZliceLedger()
    with pytest.raises(ValueError, match="ZLICE_SEQUENCE_NOT_MONOTONIC"):
        value.append(event(1, "event.strategy", "strategy_selected", ""))


def test_missing_parent_is_blocked() -> None:
    value = ZliceLedger()
    value.append(event(0, "event.strategy", "strategy_selected", ""))
    with pytest.raises(ValueError, match="ZLICE_PARENT_EVENT_MISSING"):
        value.append(event(1, "event.team", "team_proposal_emitted", "event.missing"))


def test_projection_is_read_only_and_preserves_ui_functions() -> None:
    projection = ZliceProjection(ledger().snapshot())
    capsule = projection.proof_capsule("event.team")
    receipt = projection.receipt_archive("position.r10")
    replay = projection.replay_drawer("decision.r10")
    integrity = projection.integrity_summary()
    assert capsule.event_type == "team_proposal_emitted"
    assert receipt.record_count == 3
    assert len(replay.records) == 3
    assert replay.chain_valid is True
    assert integrity.chain_valid is True
    assert integrity.duplicate_event_count == 0
    assert not hasattr(projection, "append")
    assert not hasattr(projection, "delete")


def test_external_evaluator_reads_snapshot_and_outcome_view_only() -> None:
    snapshot = ledger().snapshot()
    outcome = FormalLedgerOutcomeView(
        ledger_row_id="ledger.row.r10",
        ledger_row_hash="a" * 64,
        position_id="position.r10",
        pnl_r=1.25,
        fee_r=0.02,
        slippage_r=0.01,
        closed_at="2026-07-15T00:01:00+00:00",
    )
    evaluator = ReadOnlyPerformanceEvaluator(snapshot, {outcome.position_id: outcome})
    report = evaluator.boundary_report()
    assert report.outcome_join_candidate_count == 1
    assert report.joined_position_count == 1
    assert report.missing_outcome_position_ids == ()
    assert report.read_only is True
    assert report.execution_authority == "none"
    assert not hasattr(evaluator, "append")
    assert not hasattr(evaluator, "write")
