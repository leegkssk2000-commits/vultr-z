from pathlib import Path
import importlib.util
import sys

import numpy as np
import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "strategies"
    / "ema_ribbon_beam.py"
)

SPEC = importlib.util.spec_from_file_location(
    "ema_ribbon_beam_under_test",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

EmaRibbonBeamConfig = MODULE.EmaRibbonBeamConfig
strategy = MODULE.strategy


def _frame_from_close(close: np.ndarray) -> pd.DataFrame:
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.12
    low = np.minimum(open_, close) - 0.12

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(len(close), 100.0),
        }
    )


def _bullish_expansion_frame() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    prices = []
    price = 100.0

    for index in range(160):
        if index < 90:
            price += 0.06 + rng.normal(0.0, 0.015)
        elif index < 150:
            price += 0.015 + rng.normal(0.0, 0.010)
        else:
            price += 0.30 + rng.normal(0.0, 0.030)

        prices.append(price)

    close = np.asarray(prices)
    frame = _frame_from_close(close)

    frame.loc[frame.index[-1], "open"] = close[-2] - 0.02
    frame.loc[frame.index[-1], "close"] = close[-2] + 0.80
    frame.loc[frame.index[-1], "high"] = close[-2] + 0.88
    frame.loc[frame.index[-1], "low"] = close[-2] - 0.12

    return frame


def test_invalid_input_holds() -> None:
    result = strategy(pd.DataFrame())

    assert result["action"] == "hold"
    assert result["why"] == "ema_ribbon_beam_invalid_input"


def test_open_position_blocks_new_entry() -> None:
    frame = _bullish_expansion_frame()
    result = strategy(
        frame,
        state={"position_side": "long"},
    )

    assert result["action"] == "hold"
    assert result["why"] == "ema_ribbon_beam_position_already_open"


def test_flat_market_holds() -> None:
    close = np.full(180, 100.0)
    frame = _frame_from_close(close)
    result = strategy(frame)

    assert result["action"] == "hold"
    assert result["why"] in {
        "ema_ribbon_beam_volatility_out_of_range",
        "ema_ribbon_beam_indicator_nan",
        "ema_ribbon_beam_ribbon_width_out_of_range",
        "ema_ribbon_beam_trend_not_aligned",
    }


def test_bullish_beam_contract_and_risk_levels() -> None:
    frame = _bullish_expansion_frame()
    config = EmaRibbonBeamConfig(
        max_ribbon_width_atr=10.0,
        min_fast_slope_atr=0.01,
        min_mid_slope_atr=0.005,
        min_expansion_ratio=1.02,
        beam_body_atr=0.50,
        beam_range_atr=0.70,
        max_chase_dist_atr=10.0,
    )

    result = strategy(frame, config=config)

    assert result["action"] == "enter"
    assert result["side"] == "long"
    assert result["why"] == "ema_ribbon_beam_long_beam"
    assert result["sl"] < result["entry"] < result["tp"]
    assert result["rr"] == config.beam_rr
    assert result["risk_pct"] > 0.0
    assert result["family"] == "trend_expansion"


def test_risk_action_blocks_entry() -> None:
    frame = _bullish_expansion_frame()
    result = strategy(frame, risk_action="block")

    assert result["action"] == "hold"
    assert result["why"] == "ema_ribbon_beam_risk_blocked"
