from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.production.zel_production_ai_proposal_layer_v1 import (
    proposal_tick,
    validate_ai_response,
)
from backend.production.zel_production_economic_edge_router_v1 import route_tick


def proposal_policy() -> dict:
    return json.loads(Path("config/zel_production_ai_proposal_layer_v1.json").read_text())


def source_registry() -> dict:
    return json.loads(Path("config/zel_production_source_capability_registry_v1.json").read_text())


def router_policy() -> dict:
    return json.loads(Path("config/zel_production_economic_edge_router_v1.json").read_text())


def factory() -> dict:
    return json.loads(Path("config/zel_production_alpha_factory_v1.json").read_text())


def bootstrap() -> dict:
    return {
        "schema_version": "zel.production_performance_bootstrap.v1",
        "state": "HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE",
        "action": "hold",
        "exchange_order_submitted": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def proposal_item(*, family_id: str = "funding_basis_reversal", sources: list[str] | None = None) -> dict:
    return {
        "proposal_type": "NEW_ECONOMIC_FAMILY",
        "family_id": family_id,
        "economic_mechanism": "Persistent funding and basis disagreement may reflect crowded positioning that later normalizes.",
        "required_sources": sources or ["funding", "basis", "open_interest"],
        "causal_reason": "Funding pressure, derivative basis and positioning can jointly identify a crowded derivative state.",
        "falsification_test": "Freeze the event definition before scoring and require the same signed effect in untouched temporal partitions after observed costs.",
        "expected_horizon": "native funding interval",
    }


def initial_edge() -> dict:
    r = route_tick(router_policy(), factory=factory(), bootstrap=bootstrap(), ai_proposals=None, now_ms=1)
    assert r["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert r.get("explore_context_sha256")
    return r


def test_source_vocabulary_matches_verified_native_registry() -> None:
    policy = proposal_policy()
    registry = source_registry()
    verified = sorted(
        source_id
        for source_id, row in registry["sources"].items()
        if row.get("proposal_available") is True and row.get("native_read_bound") is True
    )
    assert sorted(policy["source_vocabulary"]) == verified
    assert policy["source_vocabulary_policy"] == "VERIFIED_NATIVE_ONLY_READD_AFTER_SOURCE_REGISTRY_BIND"
    assert {"liquidation", "flow", "trade_sequence"}.isdisjoint(policy["source_vocabulary"])


def test_not_triggered_does_not_call_ai() -> None:
    edge = initial_edge()
    edge["state"] = "PASS_EDGE_ACQUISITION_SOURCE_READY_QUEUE"
    called = 0

    def caller(_: str):
        nonlocal called
        called += 1
        return "fixture", {"status": "PASS", "proposals": [proposal_item()]}

    result, wrote = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=2,
    )
    assert result is None
    assert wrote is False
    assert called == 0


def test_source_ready_proposal_is_bounded_and_authority_free() -> None:
    edge = initial_edge()

    def caller(prompt: str):
        assert "Do NOT claim profitability" in prompt
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    result, wrote = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=3,
    )
    assert wrote is True
    assert result is not None
    assert result["state"] == "PASS_AI_PROPOSAL_SOURCE_READY"
    assert result["proposal_count"] == 1
    assert result["source_ready_count"] == 1
    row = result["proposals"][0]
    assert row["source_ready"] is True
    assert row["selection_authority"] is False
    assert row["promotion_authority"] is False
    assert row["execution_authority"] == "NONE"
    assert row["order_authority"] == "BLOCKED"
    assert result["order_authority"] == "BLOCKED"
    assert result["exchange_order_submitted"] is False


def test_unverified_source_proposal_is_rejected_before_routing() -> None:
    edge = initial_edge()

    def caller(_: str):
        return "models/gemini-fixture", {
            "status": "PASS",
            "proposals": [proposal_item(family_id="liquidation_reversion", sources=["liquidation", "open_interest"])],
        }

    result, _ = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=4,
    )
    assert result is not None
    assert result["state"] == "HOLD_AI_PROPOSAL_CALL_FAILED"
    assert "REQUIRED_SOURCE_OUTSIDE_VOCAB" in result["error_code"]
    assert result["proposal_count"] == 0
    assert result["source_ready_count"] == 0


def test_same_context_reuses_previous_without_new_ai_call() -> None:
    edge = initial_edge()
    called = 0

    def caller(_: str):
        nonlocal called
        called += 1
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    first, wrote = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=5,
    )
    assert first is not None and wrote is True and called == 1
    second, wrote2 = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=first, ai_caller=caller, now_ms=6,
    )
    assert second == first
    assert wrote2 is False
    assert called == 1


def test_duplicate_existing_family_is_rejected() -> None:
    edge = initial_edge()
    context_edge = copy.deepcopy(edge)

    def caller(_: str):
        return "models/gemini-fixture", {
            "status": "PASS",
            "proposals": [proposal_item(family_id="carry_flow", sources=["funding"])],
        }

    result, _ = proposal_tick(
        proposal_policy(), edge=context_edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=7,
    )
    assert result is not None
    assert result["state"] == "HOLD_AI_PROPOSAL_CALL_FAILED"
    assert "DUPLICATE_FAMILY" in result["error_code"]


def test_banned_authority_or_threshold_field_is_rejected() -> None:
    edge = initial_edge()
    base_context = {
        "explore_context_sha256": edge["explore_context_sha256"],
        "families": [{"family_id": "carry_flow"}],
        "available_sources": ["funding"],
    }
    bad = proposal_item(family_id="bad_family", sources=["funding"])
    bad["threshold"] = 1.5
    with pytest.raises(RuntimeError, match="BANNED_KEY"):
        validate_ai_response(
            {"status": "PASS", "proposals": [bad]},
            policy=proposal_policy(),
            context=base_context,
        )


def test_router_consumes_source_ready_ai_proposal_same_context() -> None:
    edge = initial_edge()

    def caller(_: str):
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    proposal_state, _ = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=8,
    )
    assert proposal_state is not None
    routed = route_tick(
        router_policy(), factory=factory(), bootstrap=bootstrap(), ai_proposals=proposal_state, now_ms=9,
    )
    assert routed["state"] == "PASS_EDGE_ACQUISITION_AI_PROPOSAL_QUEUE"
    assert len(routed["acquisition_queue"]) == 1
    assert routed["acquisition_queue"][0]["family_id"] == "funding_basis_reversal"
    assert routed["next"] == "FREEZE_AI_PROPOSAL_AND_BUILD_DETERMINISTIC_ADMISSION"
    assert routed["selection_authority"] is False
    assert routed["promotion_authority"] is False
    assert routed["execution_authority"] == "NONE"


def test_router_never_receives_unverified_source_proposal() -> None:
    edge = initial_edge()

    def caller(_: str):
        return "models/gemini-fixture", {
            "status": "PASS",
            "proposals": [proposal_item(family_id="liquidation_reversion", sources=["liquidation", "open_interest"])],
        }

    proposal_state, _ = proposal_tick(
        proposal_policy(), edge=edge, factory=factory(), pool=None, improvement=None,
        previous=None, ai_caller=caller, now_ms=10,
    )
    assert proposal_state is not None
    assert proposal_state["state"] == "HOLD_AI_PROPOSAL_CALL_FAILED"
    routed = route_tick(
        router_policy(), factory=factory(), bootstrap=bootstrap(), ai_proposals=proposal_state, now_ms=11,
    )
    assert routed["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert routed["order_authority"] == "BLOCKED"


def test_stale_ai_context_is_ignored() -> None:
    edge = initial_edge()
    stale = {
        "schema_version": "zel.production_ai_proposal_layer.v1",
        "explore_context_sha256": "0" * 64,
        "proposals": [],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    routed = route_tick(
        router_policy(), factory=factory(), bootstrap=bootstrap(), ai_proposals=stale, now_ms=12,
    )
    assert routed["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert routed["explore_context_sha256"] == edge["explore_context_sha256"]
