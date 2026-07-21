from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_STRESS66"])
    spec = importlib.util.spec_from_file_location("stress66", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trade(net: float = 0.2, pnl_r: float = 1.0) -> dict:
    return {
        "net_pnl_pct": net,
        "gross_pnl_pct": net + 0.02,
        "cost_pct": 0.02,
        "pnl_r": pnl_r,
        "mfe_pct": 0.3,
        "mae_pct": -0.1,
        "exit_reason": "take_profit" if net > 0 else "stop",
    }


def gate() -> dict:
    return {"profit_factor_min_exclusive": 1.25, "expectancy_r_min_exclusive": 0.15}


def cells(bucket: str, count: int, net: float = 0.2) -> list[dict]:
    rows = []
    for index in range(count):
        value = trade(net=net, pnl_r=1.0 if net > 0 else -0.75)
        rows.append({
            "bucket": bucket,
            "status": "CLOSED_TRADE",
            "cost_profile": f"cost_profile_{index % 3}",
            "perturbation": f"perturbation_{index % 2}",
            "net_pnl_pct": value["net_pnl_pct"],
            "trade": value,
        })
    return rows


def test_grid_can_be_robust_but_never_auto_promoted() -> None:
    module = load_module()
    candidates = [
        {"segment_id": f"seg{index}", "bar_index": index}
        for index in range(8)
    ]
    result = module.evaluate_bucket("grid_rebalance_range", candidates, cells("grid_rebalance_range", 48), gate())
    assert result["common_stress_gate_pass"] is True
    assert result["promotable"] is False
    assert result["classification"] == "STRESS_ROBUST_QUARANTINED_REQUIRES_RELEASE_REVIEW"


def test_axis_repeats_do_not_promote_single_candidate() -> None:
    module = load_module()
    candidates = [{"segment_id": "seg1", "bar_index": 10}]
    result = module.evaluate_bucket("scalp_snap_trend_up", candidates, cells("scalp_snap_trend_up", 6), gate())
    assert result["common_stress_gate_pass"] is True
    assert result["independent_sample_gate_pass"] is False
    assert result["promotable"] is False
    assert result["classification"] == "STRESS_ROBUST_UNDER_SAMPLED"


def test_missing_cell_is_signal_or_execution_fragility() -> None:
    module = load_module()
    candidates = [{"segment_id": "seg1", "bar_index": 10}]
    rows = cells("scalp_snap_trend_up", 5)
    result = module.evaluate_bucket("scalp_snap_trend_up", candidates, rows, gate())
    assert result["common_stress_gate_pass"] is False
    assert result["classification"] == "SIGNAL_OR_EXECUTION_NOT_ROBUST_ACROSS_AXES"


def test_negative_result_routes_to_signal_quality_repair() -> None:
    module = load_module()
    candidates = [{"segment_id": "seg1", "bar_index": 10}]
    result = module.evaluate_bucket("vol_spike_fade_shock_recovery", candidates, cells("vol_spike_fade_shock_recovery", 6, net=-0.1), gate())
    repairs = module.repair_queue([result], cells("vol_spike_fade_shock_recovery", 6, net=-0.1))
    assert result["classification"] == "NEGATIVE_SIGNAL_QUALITY"
    assert repairs[0]["actions"] == ["inspect_entry_context_and_regime_binding", "test_cooldown_and_duplicate_suppression"]
