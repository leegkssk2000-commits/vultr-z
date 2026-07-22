from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_tool():
    path = Path(os.environ["R7A4D2_CF_EXPANSION_TOOL"])
    spec = importlib.util.spec_from_file_location("cf_expansion", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner():
    path = Path(os.environ["R7A4D2_FILL_REBASE_RUNNER"])
    spec = importlib.util.spec_from_file_location("fill_rebase_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trade(gross_r: float, net_r: float, exit_reason: str, mfe_r: float = 3.0, mae_r: float = -0.8) -> dict:
    risk_pct = 1.0
    return {
        "gross_pnl_pct": gross_r * risk_pct,
        "net_pnl_pct": net_r * risk_pct,
        "raw_r_distance_pct": risk_pct,
        "mfe_pct": mfe_r * risk_pct,
        "mae_pct": mae_r * risk_pct,
        "exit_reason": exit_reason,
    }


def test_fill_rebase_geometry_preserves_return_space_rr() -> None:
    runner = load_runner()
    stop, tp, raw_fraction = runner.short_fill_rebased_geometry(
        fill=97.5,
        signal_entry=100.0,
        raw_stop=101.0,
        loss_cap_r=0.75,
        full_tp_r=2.5,
    )
    assert 0 < tp < 97.5 < stop
    assert abs((97.5 / stop - 1.0) - (-0.75 * raw_fraction)) < 1e-12
    assert abs((97.5 / tp - 1.0) - (2.5 * raw_fraction)) < 1e-12


def test_gross_loss_cap_is_separate_from_net_payoff() -> None:
    module = load_tool()
    trades = [trade(2.5, 2.4, "take_profit"), trade(-0.75, -0.85, "stop")]
    cells = [
        {"cost_profile": "cost_profile_0", "perturbation": "perturbation_0", "net_pnl_pct": 2.4},
        {"cost_profile": "cost_profile_0", "perturbation": "perturbation_0", "net_pnl_pct": -0.85},
    ]
    metrics = module.realized_rr_metrics(trades, cells)
    assert metrics["gross_max_realized_loss_r_abs"] == 0.75
    assert metrics["net_max_realized_loss_r_abs"] == 0.85
    assert metrics["net_realized_payoff_ratio"] > 1.5
    assert module.economic_gate(metrics, invalid=0, closed=2, target=2) is True


def test_symbol_normalization_and_target_shape() -> None:
    module = load_tool()
    assert module.normalize_symbol("BTC-USDT-PERP") == "BTCUSDT"
    assert module.normalize_symbol("eth_usdt") == "ETHUSDT"
    assert sum(module.BASELINE_TARGETS.values()) == 36
    assert module.BASELINE_TARGETS == {
        "ETHUSDT": 12,
        "SOLUSDT": 12,
        "BTCUSDT": 4,
        "LINKUSDT": 4,
        "XRPUSDT": 4,
    }


def test_four_candidates_cannot_be_called_s_grade() -> None:
    module = load_tool()
    metrics = {
        "profit_factor": 10.0,
        "expectancy_r": 2.0,
        "net_realized_payoff_ratio": 5.0,
    }
    assert module.s_grade_observer_gate(metrics, independent_count=4, unique_segments=4) is False
