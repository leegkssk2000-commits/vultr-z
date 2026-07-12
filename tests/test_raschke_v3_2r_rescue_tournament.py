from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_2r_rescue_tournament.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_2r_rescue_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def raw_from_r_path(highs, lows, closes=None):
    closes = closes or [0.0] * len(highs)
    start = 1_700_000_000_000
    rows = []
    for index, (high_r, low_r, close_r) in enumerate(zip(highs, lows, closes)):
        rows.append(
            {
                "ts": start + index * 60_000,
                "open": 100.0 + (closes[index - 1] if index > 0 else 0.0),
                "high": 100.0 + high_r,
                "low": 100.0 + low_r,
                "close": 100.0 + close_r,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def signal(side="long"):
    return {
        "event_id": "E1",
        "window": "prior_holdout_90d",
        "symbol": "BTCUSDT",
        "side": side,
        "signal_ts": 1_699_999_940_000,
        "entry_idx": 0,
        "entry_ts": 1_700_000_000_000,
        "signal_entry": 100.0,
        "native_stop": 99.0,
        "features": {},
    }


def test_same_bar_stop_target_is_conservative_stop() -> None:
    raw = raw_from_r_path([2.2], [-0.6], [0.0])
    trade = MODULE.simulate_policy(raw, signal(), "baseline", {"kind": "fixed", "target_r": 2.0})
    assert trade is not None
    assert trade["outcome"] == "STOP_TARGET_AMBIGUOUS"
    assert trade["gross_r"] == -0.5
    assert trade["ambiguity"] is True


def test_partial_is_realized_before_later_stop() -> None:
    raw = raw_from_r_path([1.1, 1.2], [0.0, -0.6], [0.8, -0.4])
    policy = {"kind": "partials", "target_r": 2.0, "partials": [(1.0, 0.25)]}
    trade = MODULE.simulate_policy(raw, signal(), "partial", policy)
    assert trade is not None
    assert trade["outcome"] == "SL"
    assert round(trade["partial_realized_r"], 6) == 0.25
    assert round(trade["gross_r"], 6) == -0.125


def test_ratchet_applies_next_bar_not_same_bar() -> None:
    raw = raw_from_r_path([1.1, 1.2], [-0.2, -0.1], [0.8, 0.0])
    policy = {"kind": "ratchet", "target_r": 2.0, "ratchets": [(1.0, 0.0)]}
    trade = MODULE.simulate_policy(raw, signal(), "ratchet", policy)
    assert trade is not None
    assert trade["outcome"] == "RATCHET_STOP"
    assert trade["gross_r"] == 0.0


def test_slow_1_5r_gate_exits_at_trigger() -> None:
    highs = [0.2] * 121 + [1.6]
    lows = [-0.1] * len(highs)
    closes = [0.1] * len(highs)
    raw = raw_from_r_path(highs, lows, closes)
    policy = {
        "kind": "speed_gate",
        "trigger_r": 1.5,
        "target_r": 2.0,
        "max_trigger_min": 120,
    }
    trade = MODULE.simulate_policy(raw, signal(), "speed", policy)
    assert trade is not None
    assert trade["outcome"] == "SLOW_TRIGGER_EXIT"
    assert trade["gross_r"] == 1.5


def test_side_target_selects_short_target() -> None:
    raw = raw_from_r_path([1.6], [-0.1], [1.5])
    short_signal = signal(side="short")
    # Short favorable direction uses low prices, so invert the bar around entry.
    raw.loc[0, "high"] = 100.1
    raw.loc[0, "low"] = 98.4
    raw.loc[0, "close"] = 98.5
    short_signal["native_stop"] = 101.0
    policy = {"kind": "side_target", "target_map": {"long": 2.0, "short": 1.5}}
    trade = MODULE.simulate_policy(raw, short_signal, "side", policy)
    assert trade is not None
    assert trade["target_r"] == 1.5
    assert trade["outcome"] == "TP"


def test_metrics_and_bootstrap_contract() -> None:
    rows = []
    for index, gross in enumerate((1.0, -0.5, 0.8, -0.2, 1.2, -0.5)):
        rows.append(
            {
                "entry_ts": 1_700_000_000_000 + index * 86_400_000,
                "symbol": "BTCUSDT" if index % 2 == 0 else "ETHUSDT",
                "side": "long",
                "entry": 100.0,
                "base_risk": 10.0,
                "gross_r": gross,
                "outcome": "TP" if gross > 0 else "SL",
                "ambiguity": False,
            }
        )
    report = MODULE.metrics(rows, 0.15)
    assert report["events"] == 6
    assert report["profit_factor_R"] > 1.0
    ci = MODULE.block_bootstrap_mean_ci(rows, 0.15, 7)
    assert ci["lower_95"] is not None
    assert ci["lower_95"] <= ci["median"] <= ci["upper_95"]


def test_pbo_returns_probability_bounds() -> None:
    policy_rows = {"a": [], "b": []}
    months = ["2026-01", "2026-02", "2026-03", "2026-04"]
    for policy in policy_rows:
        for index, month in enumerate(months):
            stamp = int(pd.Timestamp(f"{month}-02T00:00:00Z").timestamp() * 1000)
            policy_rows[policy].append(
                {
                    "entry_ts": stamp,
                    "entry": 100.0,
                    "base_risk": 10.0,
                    "gross_r": (0.5 if policy == "a" else 0.3) * (1 if index < 2 else -1),
                }
            )
    report = MODULE.pbo_month_blocks(policy_rows)
    assert report["available"] is True
    assert 0.0 <= report["pbo_estimate"] <= 1.0
