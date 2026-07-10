from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "q4r3_route_a_a2_frozen_holdout.py"
)
SPEC = importlib.util.spec_from_file_location("a2_frozen_holdout", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_efficiency_ratio_monotonic_is_one() -> None:
    close = pd.Series([float(value) for value in range(1, 30)])
    assert MOD.efficiency_ratio(close, 20) == 1.0


def test_ensemble_votes_clean_uptrend() -> None:
    close = pd.Series([100.0 + value * 0.5 for value in range(180)])
    assert MOD.ensemble_votes(close, "long") == 3
    assert MOD.ensemble_votes(close, "short") == 0


def test_transition_regime_is_causal_and_directional() -> None:
    close = pd.Series([100.0 + value * 0.4 for value in range(180)])
    frame = pd.DataFrame({"close": close})
    ordered = MOD.transition_regime(
        frame,
        "long",
        votes=3,
        expansion_ratio=1.20,
    )
    assert ordered["regime"] == "ORDERED_EXPANSION"

    reversal = MOD.transition_regime(
        frame,
        "long",
        votes=1,
        expansion_ratio=1.20,
    )
    assert reversal["regime"] == "REVERSAL_RISK"


def test_progress_reduce_is_partial_not_full_stop() -> None:
    rows = []
    for index in range(60):
        close = 99.8 if index < 40 else 100.2
        high = 100.1
        low = 99.5
        if index == 40:
            high = 102.1
            close = 102.0
        rows.append(
            {
                "ts_dt": pd.Timestamp("2026-01-01", tz="UTC")
                + pd.Timedelta(minutes=index),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
            }
        )

    frame = pd.DataFrame(rows)
    signal = {
        "entry_i": 0,
        "entry": 100.0,
        "sl": 99.0,
        "tp": 102.0,
        "side": "long",
        "trigger": "beam",
        "risk_pct": 1.0,
        "rr": 2.0,
        "reward_pct": 2.0,
    }

    trade = MOD.simulate_one(
        frame,
        signal,
        cost_pct=0.10,
        progress_reduce=True,
    )

    assert trade["partial_taken"] is True
    assert trade["result"] == "TP"
    assert trade["net_R"] == 0.7
