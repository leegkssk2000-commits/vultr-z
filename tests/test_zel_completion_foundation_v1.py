from __future__ import annotations

import copy
from pathlib import Path

import pytest

from backend.contracts.zel_event_sourced_shadow_v1 import AppendOnlyShadowEventStore, ShadowEventError, deterministic_event_id
from backend.contracts.zel_strategy_lifecycle_v1 import StrategyLifecycleError, transition, validate_registry
from backend.research.zel_oms_state_machine_v1 import OmsStateError, SqliteOmsStore
from backend.research.zel_promotion_gates_v1 import PromotionGateError, evaluate_completion, fixture_evidence
from backend.research.zel_strategy_lifecycle_registry_v1 import REGISTRY


def shadow_event(position_id: str, sequence: int, event_type: str, parent: str) -> dict:
    return {
        "event_id": deterministic_event_id(position_id, sequence, event_type),
        "parent_event_id": parent,
        "decision_id": "decision.test",
        "position_id": position_id,
        "strategy_id": "alpha_combo",
        "strategy_source_sha256": "2cdf64e5e66cf9e2151fbf6d82546d2a9b65a024d1acb1d53bd3d4a62fac30e3",
        "method_id": "TEST_METHOD",
        "skill_set": [],
        "team_id": "ALPHA",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "market_snapshot_sha256": "1" * 64,
        "risk_snapshot_sha256": "2" * 64,
        "sequence_no": sequence,
        "event_ts": f"2026-07-31T17:{sequence:02d}:00Z",
        "idempotency_key": f"test:{position_id}:{sequence}:{event_type}",
        "event_type": event_type,
        "payload": {"test": True},
        "source_ids": ["runtime:test"],
    }


def oms_command(target: str, sequence: int, filled: float = 0.0, mode: str = "SIMULATION") -> dict:
    return {
        "order_intent_id": "order.test",
        "client_order_id": "client.test",
        "decision_id": "decision.test",
        "position_id": "position.test",
        "strategy_id": "alpha_combo",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mode": mode,
        "target_state": target,
        "quantity": 1.0,
        "filled_quantity": filled,
        "reduce_only": target in {"CLOSE_SENT", "CLOSED"},
        "risk_snapshot_sha256": "2" * 64,
        "event_ts": f"2026-07-31T18:{sequence:02d}:00Z",
        "idempotency_key": f"oms:test:{sequence}:{target}",
        "reason_codes": ["TEST"],
    }


def test_registry_is_exact25_and_capital_blocked() -> None:
    registry = validate_registry(REGISTRY)
    assert registry["strategy_count"] == 25
    assert len({row["strategy_id"] for row in registry["entries"]}) == 25
    assert all(row["observer_allowed"] for row in registry["entries"])
    assert not any(row["capital_allowed"] for row in registry["entries"])


def test_registry_shadow_transition_requires_complete_lineage() -> None:
    research = transition(
        REGISTRY,
        "anchor_vwap_trend",
        "RESEARCH_ACTIVE",
        {"source_sha_verified": True, "behavioral_fidelity_pass": True, "evidence_refs": ["artifact:test"]},
    )
    candidate = transition(
        research,
        "anchor_vwap_trend",
        "SHADOW_CANDIDATE",
        {"failure_fingerprint": "TEST", "single_axis_change": True, "parent_immutable": True, "current_child_sha256": "3" * 64},
    )
    with pytest.raises(StrategyLifecycleError, match="LINEAGE_NOT_COMPLETE"):
        transition(candidate, "anchor_vwap_trend", "SHADOW_ACTIVE", {"lineage_coverage_pct": 99.0, "duplicate_event_count": 0, "cross_lane_leak_count": 0})


def test_event_store_complete_chain_and_idempotency() -> None:
    store = AppendOnlyShadowEventStore()
    position = "shadow.test"
    parent = ""
    types = [
        "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
        "shadow_open_confirmed", "shadow_close_requested", "shadow_closed", "formal_ledger_joined",
    ]
    first_raw = None
    for sequence, event_type in enumerate(types):
        raw = shadow_event(position, sequence, event_type, parent)
        if first_raw is None:
            first_raw = copy.deepcopy(raw)
        result = store.append(raw)
        parent = result.event["event_id"]
    assert store.validate()["pass"] is True
    replay = AppendOnlyShadowEventStore()
    assert replay.append(first_raw).replayed is False
    assert replay.append(first_raw).replayed is True
    conflicting = copy.deepcopy(first_raw)
    conflicting["payload"] = {"changed": True}
    with pytest.raises(ShadowEventError, match="IDEMPOTENCY_PAYLOAD_CONFLICT"):
        replay.append(conflicting)


def test_event_store_rejects_sequence_gap() -> None:
    store = AppendOnlyShadowEventStore()
    with pytest.raises(ShadowEventError, match="SEQUENCE_GAP"):
        store.append(shadow_event("shadow.gap", 1, "strategy_signal_emitted", ""))


def test_oms_persists_and_replays(tmp_path: Path) -> None:
    path = tmp_path / "oms.sqlite3"
    store = SqliteOmsStore(path)
    first = oms_command("INTENT_CREATED", 0)
    assert store.apply(first)["to_state"] == "INTENT_CREATED"
    assert store.apply(first)["replayed"] is True
    store2 = SqliteOmsStore(path)
    assert store2.status("order.test")["state"] == "INTENT_CREATED"
    assert store2.event_count("order.test") == 1


def test_oms_blocks_live_mode(tmp_path: Path) -> None:
    store = SqliteOmsStore(tmp_path / "oms.sqlite3")
    with pytest.raises(OmsStateError, match="MODE_FORBIDDEN"):
        store.apply(oms_command("INTENT_CREATED", 0, mode="LIVE_MICRO"))


def test_completion_fixture_cannot_claim_real_completion() -> None:
    with pytest.raises(PromotionGateError, match="REAL_EVIDENCE_REQUIRED"):
        evaluate_completion(fixture_evidence())


def test_completion_real_evidence_fails_closed_on_one_defect() -> None:
    evidence = fixture_evidence()
    evidence["fixture_only"] = False
    evidence["phases"]["P1"]["duplicate_event_count"] = 1
    result = evaluate_completion(evidence)
    assert result["claim_100_allowed"] is False
    assert result["completion_pct"] == 0.0
    assert result["phase_results"]["P1"]["pass"] is False
    assert result["phase_results"]["P2"]["blockers"][0] == "UPSTREAM_PHASE_NOT_PASS"
