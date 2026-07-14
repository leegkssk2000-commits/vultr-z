from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_risk_scenario_grid_observer.py"
spec = importlib.util.spec_from_file_location("risk_grid", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_grid_has_twelve_scenarios() -> None:
    grid, missing = module.build_grid([])
    assert len(grid) == 12
    assert missing == []
    assert {row["position_size_pct"] for row in grid} == {5, 10, 15, 20}
    assert {row["leverage_x"] for row in grid} == {10, 15, 20}


def test_grid_waits_without_exact_pairs() -> None:
    grid, _ = module.build_grid([{"pair_state": "OPEN_PENDING_CLOSE", "exact_join": False}])
    assert all(row["exact_pair_count"] == 0 for row in grid)
    assert all(row["decision_eligible"] is False for row in grid)


def test_grid_aggregates_forward_pair_metrics() -> None:
    pairs = [
        {
            "pair_state": "EXACT_CLOSE_JOINED",
            "exact_join": True,
            "realized_r": 2.0,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "mfe_r": 2.4,
            "mae_r": -0.3,
            "exposure_time_min": 30.0,
        },
        {
            "pair_state": "EXACT_CLOSE_JOINED",
            "exact_join": True,
            "realized_r": -0.75,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "mfe_r": 0.3,
            "mae_r": -0.8,
            "exposure_time_min": 15.0,
        },
    ]
    grid, missing = module.build_grid(pairs)
    assert missing == []
    first = grid[0]
    assert first["scenario_id"] == "P5_L10"
    assert first["notional_exposure_pct"] == 50.0
    assert first["net_r"] == 1.25
    assert first["max_drawdown_r"] == 0.75
    assert first["risk_context_ready"] is True


def test_missing_context_is_explicit() -> None:
    grid, missing = module.build_grid([
        {
            "pair_state": "EXACT_CLOSE_JOINED",
            "exact_join": True,
            "realized_r": 1.0,
        }
    ])
    assert "fee_bps" in missing
    assert "slippage_bps" in missing
    assert all(row["risk_context_ready"] is False for row in grid)
