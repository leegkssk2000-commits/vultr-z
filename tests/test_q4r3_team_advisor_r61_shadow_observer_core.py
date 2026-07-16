from __future__ import annotations

import json
from pathlib import Path

from canonical import zbot
from policy.zbot_shadow_router import build_shadow_observer_plan
from policy.zbot_shadow_types import ShadowObserverPolicy, ShadowSnapshot

ROOT = Path(__file__).parents[1]


def gate_policy() -> ShadowObserverPolicy:
    return ShadowObserverPolicy(1000, 50, 200, "sheets:zbot:shadow_observer_policy")


def snap(
    snapshot_id: str,
    observed_at_ms: int,
    closed_count: int,
    ledger_row_count: int,
    open_count: int = 1,
) -> ShadowSnapshot:
    return ShadowSnapshot(
        snapshot_id=snapshot_id,
        epoch_id="q4.shadow.001",
        observed_at_ms=observed_at_ms,
        schema_version="r61-test",
        shadow_source_ref="cf:shadow:status",
        market_source_ref="cf:market:snapshot",
        position_source_ref="cf:paper:position",
        ledger_source_ref="cf:formal:ledger",
        candidate_count=5,
        open_count=open_count,
        closed_count=closed_count,
        pnl_r=10.5,
        ledger_row_count=ledger_row_count,
        ledger_sha256="sha256:" + "a" * 64,
    )


def test_complete_snapshot_builds_read_only_event_routes() -> None:
    previous = snap("shadow.r61.001", 9900, 199, 299)
    current = snap("shadow.r61.002", 10000, 200, 300)
    result = build_shadow_observer_plan(
        current,
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
        previous_snapshot=previous,
    )
    assert result.state == "PLAN_READY"
    assert result.action == "hold"
    assert result.closed_delta == 1
    assert {row.task_kind for row in result.route_plans} == {
        "market_context_review",
        "risk_review",
        "post_trade_explanation",
        "optimization_candidate_review",
    }
    assert all(row.task_kind in zbot.ROUTE_POLICY for row in result.route_plans)
    assert all(row.proposed_action == "hold" for row in result.route_plans)
    assert all(row.provider_invocation_enabled is False for row in result.route_plans)
    assert result.provider_invocation_enabled is False
    assert result.runtime_binding_enabled is False
    assert result.shadow_state_mutation_enabled is False
    assert result.ledger_write_enabled is False
    assert result.execution_authority == "none"
    assert result.order_authority == "none"


def test_initial_snapshot_does_not_replay_closed_history() -> None:
    result = build_shadow_observer_plan(
        snap("shadow.r61.001", 10000, 200, 300),
        now_ms=10020,
        policy=gate_policy(),
        sgrade_ready=True,
    )
    assert result.state == "PLAN_READY"
    assert result.closed_delta == 0
    assert {row.task_kind for row in result.route_plans} == {
        "market_context_review",
        "risk_review",
    }


def test_contract_keeps_write_and_execution_paths_disabled() -> None:
    contract = json.loads(
        (ROOT / "config/q4r3_zbot_shadow_observer_integration_gate_v1.json").read_text(encoding="utf-8")
    )
    authority = contract["authority"]
    assert authority["provider_invocation_enabled"] is False
    assert authority["runtime_binding_enabled"] is False
    assert authority["shadow_state_mutation_enabled"] is False
    assert authority["ledger_write_enabled"] is False
    assert authority["execution_authority"] == "none"
    assert authority["order_authority"] == "none"
    assert contract["output"]["action"] == "hold"
