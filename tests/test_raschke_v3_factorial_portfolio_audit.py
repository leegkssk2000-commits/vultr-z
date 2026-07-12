from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_factorial_portfolio_audit.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_factorial_portfolio_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def raw_frame(length: int = 500, step: float = 0.1) -> pd.DataFrame:
    start = 1_700_000_000_000
    rows = []
    for index in range(length):
        close = 100.0 + index * step
        rows.append(
            {
                "ts": start + index * 60_000,
                "open": close - 0.02,
                "high": close + 0.05,
                "low": close - 0.05,
                "close": close,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def signal(entry_idx: int = 300, side: str = "long", symbol: str = "BTCUSDT"):
    raw = raw_frame()
    entry = float(raw.iloc[entry_idx]["open"])
    stop = entry - 1.0 if side == "long" else entry + 1.0
    return {
        "event_id": "E1",
        "window": "prior_holdout_90d",
        "symbol": symbol,
        "side": side,
        "signal_ts": int(raw.iloc[entry_idx - 1]["ts"]),
        "entry_idx": entry_idx,
        "entry_ts": int(raw.iloc[entry_idx]["ts"]),
        "signal_entry": entry,
        "native_stop": stop,
    }


def test_pb8_columns_are_balanced_and_pairwise_orthogonal() -> None:
    design = MODULE.hadamard_screening_design()
    names = MODULE.FACTOR_NAMES + MODULE.DUMMY_NAMES
    assert len(design) == 8
    for name in names:
        values = [row["levels"][name] for row in design]
        assert sum(values) == 0
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            dot = sum(row["levels"][left] * row["levels"][right] for row in design)
            assert dot == 0


def test_regime_alignment_uses_only_pre_entry_path() -> None:
    rising = raw_frame(step=0.1)
    falling = raw_frame(step=-0.1)
    assert MODULE.regime_aligned(rising, 300, "long") is True
    assert MODULE.regime_aligned(rising, 300, "short") is False
    assert MODULE.regime_aligned(falling, 300, "short") is True
    assert MODULE.regime_aligned(falling, 300, "long") is False


def test_long_only_and_link_reserve_filters() -> None:
    raw = raw_frame()
    short_signal = signal(side="short")
    link_signal = signal(side="long", symbol="LINKUSDT")
    factors = {name: False for name in MODULE.FACTOR_NAMES}
    factors["long_only"] = True
    assert MODULE.signal_allowed(raw, short_signal, factors) is False
    factors["long_only"] = False
    factors["link_reserve"] = True
    assert MODULE.signal_allowed(raw, link_signal, factors) is False


def test_same_bar_target_stop_is_conservative_stop() -> None:
    raw = raw_frame(length=400, step=0.0)
    trade_signal = signal(entry_idx=300)
    raw.loc[300, "open"] = 100.0
    raw.loc[300, "high"] = 102.2
    raw.loc[300, "low"] = 99.4
    raw.loc[300, "close"] = 100.0
    trade_signal["signal_entry"] = 100.0
    trade_signal["native_stop"] = 99.0
    factors = {name: False for name in MODULE.FACTOR_NAMES}
    trade = MODULE.simulate_factorial(raw, trade_signal, factors, {"long": 1.75, "short": 1.25}, "test")
    assert trade is not None
    assert trade["outcome"] == "STOP_TARGET_AMBIGUOUS"
    assert trade["gross_r"] == -0.5


def test_time_stop_closes_when_one_r_not_reached() -> None:
    raw = raw_frame(length=500, step=0.0)
    trade_signal = signal(entry_idx=300)
    raw.loc[300:, "open"] = 100.0
    raw.loc[300:, "high"] = 100.2
    raw.loc[300:, "low"] = 99.8
    raw.loc[300:, "close"] = 100.1
    trade_signal["signal_entry"] = 100.0
    trade_signal["native_stop"] = 99.0
    factors = {name: False for name in MODULE.FACTOR_NAMES}
    factors["time_stop_120m_unless_1R"] = True
    trade = MODULE.simulate_factorial(raw, trade_signal, factors, {"long": 1.75, "short": 1.25}, "test")
    assert trade is not None
    assert trade["outcome"] == "TIME_STOP_120"
    assert trade["duration_min"] == 120


def test_explicit_strategy_records_are_extracted() -> None:
    payload = {
        "trades": [
            {"strategy": "alpha", "exit_ts": 1_700_000_000_000, "symbol": "BTCUSDT", "pnl_r": 0.5},
            {"strategy_name": "beta", "closed_at": "2026-01-01T00:00:00Z", "realized_r": -0.25},
        ]
    }
    rows = list(MODULE.iter_json_records(payload))
    assert {row["strategy"] for row in rows} == {"alpha", "beta"}
    assert sorted(row["pnl_r"] for row in rows) == [-0.25, 0.5]


def test_strategy_map_records_inherit_strategy_name() -> None:
    payload = {
        "trades_by_strategy": {
            "alpha": [{"exit_ts": 1_700_000_000_000, "pnl_r": 0.5}],
            "beta": [{"exit_ts": 1_700_000_060_000, "pnl_r": -0.2}],
        }
    }
    rows = list(MODULE.iter_json_records(payload))
    assert {row["strategy"] for row in rows} == {"alpha", "beta"}


def test_confirmation_configs_are_deduplicated() -> None:
    screen = {
        "selected_positive_factors": ["side_specific_target", "time_stop_120m_unless_1R"],
        "best_prior_run": "PB8_R1",
        "best_prior_factors": {name: True for name in MODULE.FACTOR_NAMES},
    }
    configs = MODULE.confirmation_configs(screen)
    keys = [tuple(sorted(config["factors"].items())) for config in configs]
    assert len(keys) == len(set(keys))
    assert any(config["candidate"] == "confirm_baseline" for config in configs)
