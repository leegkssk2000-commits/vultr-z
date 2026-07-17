from __future__ import annotations

import copy

from backend.engine.exact25_r73a_source_entry_bridge import build_lane_events


def projection() -> dict:
    return {
        "templates": [
            {
                "strategy_id": "alpha_combo",
                "exit_policy_id": exit_id,
                "lane_template_id": "template." + str(index),
                "state_namespace": "state." + str(index),
                "cooldown_namespace": "cooldown." + str(index),
                "cost_model_ref": "q4r3.shared.execution_cost_model.v1",
                "skill_set": [],
            }
            for index, exit_id in enumerate(("NATIVE", "P15", "P20", "P25"), 1)
        ]
    }


def source() -> dict:
    return {
        "source_event_id": "entry.001",
        "source_position_id": "position.001",
        "source_sequence": 1,
        "strategy_id": "alpha_combo",
        "strategy_source_sha256": "sha256:" + "a" * 64,
        "method_id": "method.alpha",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_ts_ms": 1800000000000,
        "observed_at_ms": 1800000001000,
        "entry_price": 100000.0,
        "market_path_id": "market.001",
        "cost_model_ref": "q4r3.shared.execution_cost_model.v1",
        "source_ref": "runtime:r73a.synthetic",
    }


def test_valid_source_fans_out_to_four_isolated_lanes() -> None:
    result = build_lane_events(source(), projection())
    assert result["state"] == "BRIDGE_READY"
    assert result["lane_event_count"] == 4
    rows = result["lane_events"]
    assert len({row["lane_event_id"] for row in rows}) == 4
    assert len({row["lane_position_id"] for row in rows}) == 4
    assert len({row["state_namespace"] for row in rows}) == 4
    assert len({row["cooldown_namespace"] for row in rows}) == 4
    assert {row["source_event_id"] for row in rows} == {"entry.001"}
    assert {row["market_path_id"] for row in rows} == {"market.001"}
    assert all(row["skill_set"] == [] for row in rows)
    assert result["runtime_binding_allowed"] is False
    assert result["source_event_subscription_allowed"] is False
    assert result["formal_ledger_write_allowed"] is False


def test_bridge_is_deterministic() -> None:
    assert build_lane_events(source(), projection()) == build_lane_events(source(), projection())


def test_missing_identity_holds() -> None:
    bad = source(); bad["source_event_id"] = ""
    result = build_lane_events(bad, projection())
    assert result["state"] == "HOLD"
    assert "SOURCE_FIELD_MISSING:source_event_id" in result["reason_codes"]


def test_invalid_side_holds() -> None:
    bad = source(); bad["side"] = "flat"
    assert "SOURCE_SIDE_INVALID" in build_lane_events(bad, projection())["reason_codes"]


def test_invalid_price_holds() -> None:
    bad = source(); bad["entry_price"] = 0
    assert "ENTRY_PRICE_INVALID" in build_lane_events(bad, projection())["reason_codes"]


def test_unknown_strategy_holds() -> None:
    bad = source(); bad["strategy_id"] = "unknown"
    assert "FOUR_EXIT_TEMPLATES_NOT_FOUND" in build_lane_events(bad, projection())["reason_codes"]


def test_skill_contamination_holds() -> None:
    bad = copy.deepcopy(projection()); bad["templates"][0]["skill_set"] = ["SK_EXIT_PARTIAL_30"]
    assert "RAW_SKILL_CONTAMINATION" in build_lane_events(source(), bad)["reason_codes"]


def test_cost_model_mismatch_holds() -> None:
    bad = source(); bad["cost_model_ref"] = "other"
    assert "COST_MODEL_MISMATCH" in build_lane_events(bad, projection())["reason_codes"]
