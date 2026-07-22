from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_STRESS168"])
    spec = importlib.util.spec_from_file_location("stress168", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidates(bucket: str, strategy: str, regime: str, count: int, unique_segments: int) -> list[dict]:
    return [
        {
            "candidate_id": f"{bucket}:{index}",
            "bucket": bucket,
            "strategy_id": strategy,
            "regime": regime,
            "segment_id": f"segment{index % unique_segments}",
            "source_path": f"data/source{index % 4}.json",
            "bar_index": 320 + index,
        }
        for index in range(count)
    ]


def positive_trade() -> dict:
    return {
        "net_pnl_pct": 0.2,
        "gross_pnl_pct": 0.22,
        "cost_pct": 0.02,
        "pnl_r": 2.0,
        "mfe_pct": 0.4,
        "mae_pct": -0.1,
        "exit_reason": "take_profit",
    }


def cells_for(rows: list[dict], closed: bool = True, positive: bool = True) -> list[dict]:
    output: list[dict] = []
    for candidate in rows:
        for cost in ("cost_profile_0", "cost_profile_1", "cost_profile_2"):
            for perturbation in ("perturbation_0", "perturbation_1"):
                trade = positive_trade() if closed else None
                if trade is not None and not positive:
                    trade = dict(trade)
                    trade.update({"net_pnl_pct": -0.1, "gross_pnl_pct": -0.08, "pnl_r": -0.75, "exit_reason": "stop"})
                output.append({
                    "candidate_id": candidate["candidate_id"],
                    "bucket": candidate["bucket"],
                    "segment_id": candidate["segment_id"],
                    "cost_profile": cost,
                    "perturbation": perturbation,
                    "status": "CLOSED_TRADE" if closed else "NO_CLOSED_TRADE",
                    "target_match_count": 1,
                    "invalid_geometry_count": 0,
                    "net_pnl_pct": trade["net_pnl_pct"] if trade else 0.0,
                    "trade": trade,
                })
    return output


def gate() -> dict:
    return {"profit_factor_min_exclusive": 1.25, "expectancy_r_min_exclusive": 0.15}


def test_scalp_robust_bucket_is_promotable() -> None:
    module = load_module()
    rows = candidates("scalp_snap_trend_up", "scalp_snap", "trend_up", 12, 10)
    result = module.evaluate_bucket("scalp_snap_trend_up", rows, cells_for(rows), gate())
    assert result["common_stress_gate_pass"] is True
    assert result["diversity_gate_pass"] is True
    assert result["promotable"] is True
    assert result["classification"] == "STRESS_ROBUST_PROMOTION_CANDIDATE"


def test_grid_trend_down_stays_quarantined_when_robust() -> None:
    module = load_module()
    rows = candidates("baseline_trend_down", "grid_rebalance", "trend_down", 12, 12)
    result = module.evaluate_bucket("baseline_trend_down", rows, cells_for(rows), gate())
    assert result["common_stress_gate_pass"] is True
    assert result["promotable"] is False
    assert result["quarantined"] is True
    assert result["classification"] == "STRESS_ROBUST_GRID_STRATEGY_QUARANTINED"


def test_vol_positive_remains_under_sampled() -> None:
    module = load_module()
    rows = candidates("vol_spike_fade_shock_recovery", "vol_spike_fade", "shock_recovery", 4, 4)
    result = module.evaluate_bucket("vol_spike_fade_shock_recovery", rows, cells_for(rows), gate())
    assert result["common_stress_gate_pass"] is True
    assert result["promotable"] is False
    assert result["classification"] == "DIAGNOSTIC_POSITIVE_UNDER_SAMPLED"


def test_missing_close_is_fill_window_failure() -> None:
    module = load_module()
    rows = candidates("scalp_snap_trend_up", "scalp_snap", "trend_up", 12, 10)
    result = module.evaluate_bucket("scalp_snap_trend_up", rows, cells_for(rows, closed=False), gate())
    assert result["common_stress_gate_pass"] is False
    assert result["classification"] == "FILL_OR_CLOSE_WINDOW_NOT_ROBUST"


def test_negative_trades_are_negative_signal_quality() -> None:
    module = load_module()
    rows = candidates("scalp_snap_trend_up", "scalp_snap", "trend_up", 12, 10)
    result = module.evaluate_bucket("scalp_snap_trend_up", rows, cells_for(rows, positive=False), gate())
    assert result["common_stress_gate_pass"] is False
    assert result["classification"] == "NEGATIVE_SIGNAL_QUALITY"
