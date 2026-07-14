from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_method_scoreboard_observer.py"
spec = importlib.util.spec_from_file_location("method_scoreboard", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def empty_projection() -> dict:
    return {
        "rows": [
            {
                "method_id": method_id,
                "trigger_count": 0,
                "blocked_count": 0,
                "outcome_join_count": 0,
                "unique_position_count": 0,
            }
            for method_id in module.METHODS
        ]
    }


def empty_risk_grid() -> dict:
    return {
        "scenario_count": 12,
        "exact_pair_count": 0,
        "missing_risk_fields": [],
    }


def test_scoreboard_has_six_methods() -> None:
    rows = module.build_scoreboard(empty_projection(), empty_risk_grid())
    assert len(rows) == 6
    assert [row["method_id"] for row in rows] == list(module.METHODS)


def test_empty_scoreboard_waits_for_trigger() -> None:
    rows = module.build_scoreboard(empty_projection(), empty_risk_grid())
    assert all(row["evidence_state"] == "WAITING_FORWARD_TRIGGER" for row in rows)
    assert all(row["comparison_eligible"] is False for row in rows)
    assert all(row["rank"] is None for row in rows)


def test_trigger_without_close_waits_for_outcome() -> None:
    projection = empty_projection()
    projection["rows"][0].update({"trigger_count": 2, "unique_position_count": 2})
    rows = module.build_scoreboard(projection, empty_risk_grid())
    assert rows[0]["evidence_state"] == "WAITING_CLOSE_OUTCOME"
    assert rows[0]["trigger_count"] == 2


def test_complete_metrics_remain_decision_locked() -> None:
    projection = empty_projection()
    projection["rows"][0].update({
        "trigger_count": 3,
        "outcome_join_count": 3,
        "unique_position_count": 3,
        "net_r": 2.5,
        "avg_r": 0.83333333,
        "positive_rate_pct": 66.66666667,
        "profit_factor": 2.0,
        "max_drawdown_r": 0.75,
        "avg_fee_bps": 4.0,
        "avg_slippage_bps": 2.0,
        "avg_mfe_r": 1.2,
        "avg_mae_r": -0.4,
        "avg_hold_min": 18.0,
    })
    risk = {
        "scenario_count": 12,
        "exact_pair_count": 3,
        "missing_risk_fields": [],
    }
    rows = module.build_scoreboard(projection, risk)
    first = rows[0]
    assert first["evidence_state"] == "FORWARD_EVIDENCE_ACTIVE"
    assert first["return_to_drawdown_ratio"] == 3.33333333
    assert first["mfe_capture_ratio"] == 0.69444444
    assert first["risk_context_ready"] is True
    assert first["comparison_eligible"] is False
    assert first["promotion_enabled"] is False
