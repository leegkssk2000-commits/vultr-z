from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.engine.exact25_raw_100_lane_projection import build_projection_manifest

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_CONTRACT = json.loads(
    (ROOT / "backend/contracts/ZOS_EXACT25_RAW_100_LANE_PROJECTION_v1.json").read_text(encoding="utf-8")
)
MATRIX_CONTRACT = json.loads(
    (ROOT / "backend/contracts/ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_v1.json").read_text(encoding="utf-8")
)
STRATEGIES = tuple(f"strategy_{index:02d}" for index in range(25))
MANIFEST_SHA = "a" * 64
R71 = {
    "state": "PASS",
    "blockers": [],
    "report": {"strategy_count": 25, "raw_baseline_lane_count": 100},
}


def project(**overrides):
    values = {
        "strategy_ids": STRATEGIES,
        "exact25_manifest_sha256": MANIFEST_SHA,
        "matrix_contract": MATRIX_CONTRACT,
        "r71_status": R71,
        "projection_contract": PROJECTION_CONTRACT,
    }
    values.update(overrides)
    return build_projection_manifest(**values)


def test_projection_is_ready_and_exactly_100_templates() -> None:
    result = project()
    assert result.state == "PROJECTION_READY"
    assert result.strategy_count == 25
    assert result.exit_policy_count == 4
    assert result.lane_template_count == 100
    assert result.runtime_active is False
    assert result.source_event_subscription_allowed is False
    assert result.formal_ledger_write_allowed is False


def test_each_strategy_has_four_exit_templates_and_no_skills() -> None:
    result = project()
    counts = {strategy_id: 0 for strategy_id in STRATEGIES}
    for row in result.templates:
        counts[row.strategy_id] += 1
        assert row.skill_set == ()
        assert row.observer_only is True
        assert row.runtime_binding_allowed is False
        assert row.execution_authority == "none"
        assert row.order_authority == "blocked"
    assert set(counts.values()) == {4}


def test_projection_is_deterministic() -> None:
    first = project()
    second = project(strategy_ids=tuple(reversed(STRATEGIES)))
    assert first.projection_sha256 == second.projection_sha256
    assert tuple(row.lane_template_id for row in first.templates) == tuple(
        row.lane_template_id for row in second.templates
    )


def test_state_and_cooldown_namespaces_are_isolated() -> None:
    result = project()
    states = [row.state_namespace for row in result.templates]
    cooldowns = [row.cooldown_namespace for row in result.templates]
    assert len(states) == len(set(states)) == 100
    assert len(cooldowns) == len(set(cooldowns)) == 100
    assert not (set(states) & set(cooldowns))


def test_fixed_lanes_hold_point_seven_five_risk_cap() -> None:
    result = project()
    fixed = [row for row in result.templates if row.exit_policy_id != "EXIT_NATIVE"]
    native = [row for row in result.templates if row.exit_policy_id == "EXIT_NATIVE"]
    assert len(fixed) == 75
    assert all(row.planned_loss_r == 0.75 for row in fixed)
    assert all(row.planned_loss_r == 0.0 for row in native)


def test_r71_hold_blocks_projection() -> None:
    bad = copy.deepcopy(R71)
    bad["state"] = "HOLD"
    result = project(r71_status=bad)
    assert result.state == "HOLD"
    assert "R71_PASS_NOT_PROVEN" in result.reason_codes
    assert result.lane_template_count == 0


def test_duplicate_strategy_blocks_projection() -> None:
    bad = list(STRATEGIES)
    bad[-1] = bad[0]
    result = project(strategy_ids=tuple(bad))
    assert result.state == "HOLD"
    assert "UNIQUE_EXACT25_NOT_PROVEN" in result.reason_codes


def test_projection_authority_violation_fails_closed() -> None:
    bad = copy.deepcopy(PROJECTION_CONTRACT)
    bad["authority"]["runtime_binding_allowed"] = True
    result = project(projection_contract=bad)
    assert result.state == "HOLD"
    assert "AUTHORITY_FLAG_INVALID:runtime_binding_allowed" in result.reason_codes


def test_skill_contamination_is_impossible_in_raw_builder() -> None:
    result = project()
    assert all(row.skill_set == () for row in result.templates)
    payload = result.as_payload()
    assert all(row["skill_set"] == [] for row in payload["templates"])


def test_invalid_exit_policy_set_blocks_projection() -> None:
    bad = copy.deepcopy(MATRIX_CONTRACT)
    bad["exit_policy_lanes"] = bad["exit_policy_lanes"][:-1]
    result = project(matrix_contract=bad)
    assert result.state == "HOLD"
    assert "MATRIX_EXIT_POLICY_SET_INVALID" in result.reason_codes
