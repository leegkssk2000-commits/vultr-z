from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v2_entry_exit_tournament.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v2_tournament", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def signal(**overrides):
    row = {
        "side": "long",
        "ema_distance_atr": 1.0,
        "ema_slope_atr": 0.02,
        "macd_signal_spread_atr": 0.02,
    }
    row.update(overrides)
    return row


def raw_frame(highs, lows, closes=None):
    closes = closes or [100.0] * len(highs)
    start = 1_700_000_000_000
    rows = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes)):
        rows.append(
            {
                "ts": start + index * MODULE.MINUTE_MS,
                "ts_dt": pd.to_datetime(start + index * MODULE.MINUTE_MS, unit="ms", utc=True),
                "open": 100.0,
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": 1.0,
                "raw_idx": index,
            }
        )
    return pd.DataFrame(rows)


def test_entry_candidates_are_single_delta_and_deterministic() -> None:
    assert MODULE.entry_pass("baseline_candle_direction", signal()) is True
    assert MODULE.entry_pass("v2_proximity_guard", signal(ema_distance_atr=0.75)) is False
    assert MODULE.entry_pass("v2_proximity_guard", signal(ema_distance_atr=0.751)) is True
    assert MODULE.entry_pass("v2_direction_alignment", signal(side="long", ema_slope_atr=-0.01)) is False
    assert MODULE.entry_pass("v2_direction_alignment", signal(side="short", ema_slope_atr=-0.01)) is True
    assert MODULE.entry_pass("v2_macd_strength", signal(macd_signal_spread_atr=0.015)) is False
    assert MODULE.entry_pass("v2_macd_strength", signal(macd_signal_spread_atr=0.016)) is True


def test_fixed_2r_reaches_target() -> None:
    raw = raw_frame([100.2, 102.1], [99.8, 99.8], [100.0, 102.0])
    trade = MODULE.simulate_policy(
        raw,
        entry_idx=0,
        side="long",
        signal_entry=100.0,
        native_stop=99.0,
        policy_name="fixed_2R",
    )
    assert trade is not None
    assert trade["outcome"] == "TP"
    assert trade["gross_r"] == 2.0


def test_breakeven_activates_only_after_trigger_bar() -> None:
    raw = raw_frame(
        [101.1, 100.2, 100.1],
        [99.8, 99.9, 99.8],
        [100.8, 100.0, 99.9],
    )
    trade = MODULE.simulate_policy(
        raw,
        entry_idx=0,
        side="long",
        signal_entry=100.0,
        native_stop=99.0,
        policy_name="breakeven_after_1R",
    )
    assert trade is not None
    assert trade["triggered_1R"] is True
    assert trade["outcome"] == "BE"
    assert trade["gross_r"] == 0.0


def test_partial30_be_locks_point_three_r_before_cost() -> None:
    raw = raw_frame(
        [101.1, 100.2],
        [99.8, 99.9],
        [100.8, 100.0],
    )
    trade = MODULE.simulate_policy(
        raw,
        entry_idx=0,
        side="long",
        signal_entry=100.0,
        native_stop=99.0,
        policy_name="partial30_be_after_1R",
    )
    assert trade is not None
    assert trade["outcome"] == "PARTIAL_BE"
    assert abs(trade["gross_r"] - 0.30) < 1e-12


def test_gap_crossing_trade_is_rejected() -> None:
    raw = raw_frame([100.2, 100.2, 100.2], [99.8, 99.8, 99.8])
    raw.loc[2, "ts"] += MODULE.MINUTE_MS
    trade = MODULE.simulate_policy(
        raw,
        entry_idx=0,
        side="long",
        signal_entry=100.0,
        native_stop=99.0,
        policy_name="fixed_2R",
    )
    assert trade is None


def test_gate_requires_all_predeclared_checks() -> None:
    baseline = {
        "avg_net_R": -0.03,
        "profit_factor_R": 0.90,
        "max_drawdown_R": 20.0,
    }
    combined = {
        "avg_net_R": 0.03,
        "profit_factor_R": 1.10,
        "max_drawdown_R": 15.0,
        "positive_symbols": 3,
    }
    prior = {"avg_net_R": 0.02}
    second = {"avg_net_R": 0.01}
    cost020 = {"avg_net_R": 0.01}
    assessment = MODULE.gate_assessment(
        combined=combined,
        prior=prior,
        second=second,
        baseline_combined=baseline,
        retention_pct=75.0,
        cost020_combined=cost020,
    )
    assert assessment["pass"] is True

    assessment_low_retention = MODULE.gate_assessment(
        combined=combined,
        prior=prior,
        second=second,
        baseline_combined=baseline,
        retention_pct=69.9,
        cost020_combined=cost020,
    )
    assert assessment_low_retention["pass"] is False
