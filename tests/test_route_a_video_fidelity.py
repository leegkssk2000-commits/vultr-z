from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

MODULES = [
    "backend.strategies.rayner_hist_momentum",
    "backend.strategies.raschke_macd_ema200",
    "backend.strategies.fractal_triple_ema_pullback",
    "backend.strategies.alligator_trend_pullback",
]


def synthetic_frame(rows: int = 420) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    trend = 100.0 + index * 0.08
    wave = np.sin(index / 9.0) * 0.8
    close = trend + wave
    open_ = close - np.sin(index / 5.0) * 0.15
    high = np.maximum(open_, close) + 0.35
    low = np.minimum(open_, close) - 0.35
    volume = 1000.0 + (np.cos(index / 7.0) + 1.5) * 200.0
    return pd.DataFrame(
        {
            "ts": (index.astype(int) + 1) * 60_000,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.mark.parametrize("module_name", MODULES)
def test_strategy_contract_is_deterministic_and_read_only(module_name: str) -> None:
    module = importlib.import_module(module_name)
    frame = synthetic_frame()
    original = frame.copy(deep=True)
    first = module.strategy(frame)
    second = module.strategy(frame)
    pd.testing.assert_frame_equal(frame, original)
    assert first == second
    assert first["action"] in {"hold", "enter"}
    assert first["strategy"]
    assert first["family"] == "trend_pullback"
    if first["action"] == "enter":
        assert first["side"] in {"long", "short"}
        entry = float(first["entry"])
        stop = float(first["sl"])
        target = float(first["tp"])
        assert (first["side"] == "long" and stop < entry < target) or (
            first["side"] == "short" and target < entry < stop
        )


@pytest.mark.parametrize("module_name", MODULES)
def test_insufficient_data_fails_closed(module_name: str) -> None:
    module = importlib.import_module(module_name)
    result = module.strategy(synthetic_frame(20))
    assert result["action"] == "hold"
    assert result["entry"] is None
    assert result["sl"] is None
    assert result["tp"] is None


@pytest.mark.parametrize("module_name", MODULES)
def test_existing_position_blocks_new_entry(module_name: str) -> None:
    module = importlib.import_module(module_name)
    result = module.strategy(synthetic_frame(), state={"position_side": "long"})
    assert result["action"] == "hold"
    assert "position_already_open" in result["why"]


def test_video_specific_settings_are_not_replaced_by_failed_a2_hybrid() -> None:
    rayner = importlib.import_module("backend.strategies.rayner_hist_momentum")
    rayner_cfg = rayner.RaynerHistMomentumConfig()
    assert (rayner_cfg.ema_length, rayner_cfg.macd_fast, rayner_cfg.macd_slow, rayner_cfg.macd_signal) == (60, 1, 60, 9)

    raschke = importlib.import_module("backend.strategies.raschke_macd_ema200")
    raschke_cfg = raschke.RaschkeMacdEma200Config()
    assert (raschke_cfg.ema_length, raschke_cfg.macd_fast, raschke_cfg.macd_slow, raschke_cfg.macd_signal) == (200, 12, 26, 9)

    fractal = importlib.import_module("backend.strategies.fractal_triple_ema_pullback")
    fractal_cfg = fractal.FractalTripleEmaConfig()
    assert (fractal_cfg.ema_fast, fractal_cfg.ema_mid, fractal_cfg.ema_slow) == (20, 50, 100)

    alligator = importlib.import_module("backend.strategies.alligator_trend_pullback")
    alligator_cfg = alligator.AlligatorTrendConfig()
    assert (
        alligator_cfg.lips_length,
        alligator_cfg.teeth_length,
        alligator_cfg.jaw_length,
        alligator_cfg.lips_shift,
        alligator_cfg.teeth_shift,
        alligator_cfg.jaw_shift,
    ) == (5, 8, 13, 3, 5, 8)
