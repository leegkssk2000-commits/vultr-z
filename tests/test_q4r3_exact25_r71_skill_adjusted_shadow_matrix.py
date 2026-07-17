from __future__ import annotations

import json
from pathlib import Path

from backend.engine.exact25_skill_shadow_matrix_candidate import (
    SourceEntry,
    build_raw_baseline_plan,
    validate_contract,
    validate_planned_loss,
    validate_skill_set,
)

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "backend/contracts/ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_v1.json"
REGISTRY_PATH = ROOT / "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def entries(count: int = 25) -> list[SourceEntry]:
    return [
        SourceEntry(
            matrix_epoch_id="q4.shadow.skill-matrix.001",
            source_position_id=f"paper.source.{index:03d}",
            source_entry_event_id=f"entry.source.{index:03d}",
            strategy_id=f"strategy_{index:02d}",
            strategy_source_sha256="sha256:" + f"{index + 1:064x}"[-64:],
            method_id="intraday/breakout_probe",
            symbol="BTCUSDT" if index % 2 == 0 else "ETHUSDT",
            side="long" if index % 3 else "short",
            entry_ts=10000 + index,
            entry_price=100.0 + index,
            market_path_id="market.path.shared.001",
        )
        for index in range(count)
    ]


def test_contract_partitions_all_eighteen_skills() -> None:
    contract = load(CONTRACT_PATH)
    registry = load(REGISTRY_PATH)
    assert validate_contract(contract, registry) == ()
    partitions = contract["skill_partitions"]
    combined = (
        set(partitions["entry_ablation_skills"])
        | set(partitions["single_skill_management_candidates"])
        | set(partitions["mandatory_guardrail_skills"])
    )
    assert len(combined) == 18


def test_raw_plan_builds_exactly_one_hundred_isolated_lanes() -> None:
    plan = build_raw_baseline_plan(entries(), load(CONTRACT_PATH), load(REGISTRY_PATH))
    assert plan.state == "PLAN_READY"
    assert plan.strategy_count == 25
    assert plan.exit_policy_count == 4
    assert plan.lane_count == 100
    assert len({lane.lane_position_id for lane in plan.lanes}) == 100
    assert all(lane.skill_set == () for lane in plan.lanes)
    assert all(lane.observer_only is True for lane in plan.lanes)
    assert all(lane.execution_authority == "none" for lane in plan.lanes)
    assert all(lane.order_authority == "blocked" for lane in plan.lanes)


def test_each_strategy_keeps_same_entry_identity_across_exit_lanes() -> None:
    source = entries()
    plan = build_raw_baseline_plan(source, load(CONTRACT_PATH), load(REGISTRY_PATH))
    for entry in source:
        rows = [lane for lane in plan.lanes if lane.strategy_id == entry.strategy_id]
        assert len(rows) == 4
        assert {row.source_position_id for row in rows} == {entry.source_position_id}
        assert {row.source_entry_event_id for row in rows} == {entry.source_entry_event_id}
        assert len({row.lane_position_id for row in rows}) == 4


def test_source_entry_count_must_be_exactly_twenty_five() -> None:
    plan = build_raw_baseline_plan(entries(24), load(CONTRACT_PATH), load(REGISTRY_PATH))
    assert plan.state == "HOLD"
    assert "SOURCE_ENTRY_COUNT_NOT_25" in plan.reason_codes
    assert plan.lane_count == 0


def test_duplicate_strategy_entry_fails_closed() -> None:
    source = entries()
    source[-1] = SourceEntry(**{**source[-1].__dict__, "strategy_id": source[0].strategy_id})
    plan = build_raw_baseline_plan(source, load(CONTRACT_PATH), load(REGISTRY_PATH))
    assert plan.state == "HOLD"
    assert "DUPLICATE_STRATEGY_ENTRY" in plan.reason_codes


def test_fixed_exit_lanes_use_declared_targets_and_loss_cap() -> None:
    plan = build_raw_baseline_plan(entries(), load(CONTRACT_PATH), load(REGISTRY_PATH))
    fixed = {lane.exit_policy_id: lane for lane in plan.lanes if lane.strategy_id == "strategy_00"}
    assert fixed["EXIT_FIXED_1P5_L0P75"].target_r == 1.5
    assert fixed["EXIT_FIXED_2P0_L0P75"].target_r == 2.0
    assert fixed["EXIT_FIXED_2P5_L0P75"].target_r == 2.5
    assert fixed["EXIT_FIXED_2P0_L0P75"].loss_cap_r == -0.75
    assert fixed["EXIT_FIXED_2P0_L0P75"].planned_loss_r == 0.75


def test_single_skill_and_max_two_skill_contract() -> None:
    contract = load(CONTRACT_PATH)
    assert validate_skill_set(("SK_EXIT_PARTIAL_30",), contract) == ()
    assert validate_skill_set(("SK_EXIT_PARTIAL_30", "SK_EXIT_MFE_RUNNER"), contract) == ()
    assert "SKILL_COMBINATION_TOO_LARGE" in validate_skill_set(
        ("SK_EXIT_PARTIAL_30", "SK_EXIT_MFE_RUNNER", "SK_EXIT_TIME_STOP"), contract
    )


def test_loss_adds_and_profit_adds_cannot_be_mixed() -> None:
    contract = load(CONTRACT_PATH)
    assert "LOSS_DIRECTION_ADDS_MUTUALLY_EXCLUSIVE" in validate_skill_set(
        ("SK_ADD_DCA", "SK_ADD_AVG_DOWN"), contract
    )
    assert "LOSS_AND_PROFIT_ADD_COMBINATION_FORBIDDEN" in validate_skill_set(
        ("SK_ADD_DCA", "SK_ADD_PYRAMIDING"), contract
    )


def test_aggregate_loss_budget_is_fail_closed() -> None:
    contract = load(CONTRACT_PATH)
    assert validate_planned_loss(0.75, contract) == ()
    assert validate_planned_loss(0.751, contract) == ("AGGREGATE_PLANNED_LOSS_CAP_EXCEEDED",)
    assert validate_planned_loss(-0.1, contract) == ("PLANNED_LOSS_R_NEGATIVE",)


def test_external_provider_canary_is_not_shadow_matrix_dependency() -> None:
    contract = load(CONTRACT_PATH)
    assert contract["dependency_contract"]["r63_context_required"] is True
    assert contract["dependency_contract"]["r64_external_canary_required_for_shadow_matrix"] is False
    assert contract["authority"]["provider_invocation_enabled"] is False
