from __future__ import annotations

import json
from pathlib import Path

import pytest

from canonical.performance import AttributionEnvelope, ComponentRef
from canonical.zlice.outcome_join import build_outcome_join_event, parse_formal_ledger_row, read_formal_ledger


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "event_id": "close.1",
        "position_id": "position.1",
        "symbol": "BTCUSDT",
        "side": "long",
        "strategy_id": "strategy.1",
        "method_id": "method.1",
        "skill_id": "skill.1",
        "pnl_r": 1.25,
        "fee_bps": 3.0,
        "slippage_bps": 1.0,
        "exit_ts": "2026-07-15T18:00:00+00:00",
    }
    value.update(changes)
    return value


def attr(position_id: str = "position.1") -> AttributionEnvelope:
    refs = (
        ComponentRef("strategy", "strategy.1", "v1", "trace.s", "baseline"),
        ComponentRef("method", "method.1", "v1", "trace.m", "baseline"),
        ComponentRef("skill", "skill.1", "v1", "trace.k", "baseline"),
        ComponentRef("team", "AlphaTeam", "v1", "trace.t", "observer"),
    )
    return AttributionEnvelope(
        attribution_id="attr.1",
        decision_id="decision.1",
        position_id=position_id,
        event_id="team.event.1",
        strategy_id="strategy.1",
        method_id="method.1",
        skill_id="skill.1",
        team_id="AlphaTeam",
        policy_variant_id="team-core",
        counterfactual_cohort_id="cohort.1",
        component_refs=refs,
    )


def test_row_normalization_is_stable() -> None:
    source = row()
    before = dict(source)
    one = parse_formal_ledger_row(source, line_no=1, source_path="/tmp/formal.jsonl")
    two = parse_formal_ledger_row(source, line_no=1, source_path="/tmp/formal.jsonl")
    assert source == before
    assert one.ledger_row_hash == two.ledger_row_hash
    assert one.position_id == "position.1"
    assert one.realized_r == 1.25
    assert one.lineage_complete is True


def test_aliases_are_supported() -> None:
    parsed = parse_formal_ledger_row(
        row(event_id=None, close_event_id="close.alias", position_id=None, positionId="position.alias", pnl_r=None, realized_r=-0.75, exit_ts=None, closed_at="2026-07-15T19:00:00+00:00"),
        line_no=2,
        source_path="/tmp/formal.jsonl",
    )
    assert parsed.close_event_id == "close.alias"
    assert parsed.position_id == "position.alias"
    assert parsed.realized_r == -0.75


def test_reader_detects_duplicate_and_invalid_lines(tmp_path: Path) -> None:
    path = tmp_path / "formal.jsonl"
    path.write_text(json.dumps(row()) + "\n" + json.dumps(row(position_id="position.2")) + "\n{bad}\n", encoding="utf-8")
    result = read_formal_ledger(path)
    assert result.join_ready is False
    assert result.duplicate_close_event_ids == ("close.1",)
    assert len(result.parse_errors) == 1
    assert len(result.file_sha256) == 64


def test_missing_identity_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "formal.jsonl"
    path.write_text(json.dumps(row(event_id=None, position_id=None)) + "\n", encoding="utf-8")
    result = read_formal_ledger(path)
    assert result.outcomes == ()
    assert len(result.rejected_rows) == 1


def test_event_keeps_formal_row_reference() -> None:
    outcome = parse_formal_ledger_row(row(), line_no=1, source_path="/tmp/formal.jsonl")
    event = build_outcome_join_event(
        outcome=outcome,
        attribution=attr(),
        parent_event_id="position.closed.1",
        event_ts="2026-07-15T18:00:01+00:00",
        sequence_no=3,
    )
    assert event.event_type == "outcome_joined"
    assert event.metadata["ledger_row_hash"] == outcome.ledger_row_hash
    assert event.metadata["formal_ledger_is_pnl_ssot"] == "true"


def test_mismatched_position_is_rejected() -> None:
    outcome = parse_formal_ledger_row(row(), line_no=1, source_path="/tmp/formal.jsonl")
    with pytest.raises(ValueError, match="OUTCOME_ATTRIBUTION_POSITION_MISMATCH"):
        build_outcome_join_event(
            outcome=outcome,
            attribution=attr("position.other"),
            parent_event_id="position.closed.1",
            event_ts="2026-07-15T18:00:01+00:00",
            sequence_no=3,
        )
