from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "q4r3_route_a_a2_forensic_decomposition.py"
)
SPEC = importlib.util.spec_from_file_location("a2_forensic", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
FORENSIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FORENSIC)


def test_efficiency_ratio_is_one_for_monotonic_series() -> None:
    close = pd.Series([float(value) for value in range(1, 25)])
    assert FORENSIC.efficiency_ratio(close, 20) == 1.0


def test_directional_persistence_tracks_requested_side() -> None:
    rising = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert FORENSIC.directional_persistence(rising, "long", 4) == 1.0
    assert FORENSIC.directional_persistence(rising, "short", 4) == 0.0


def test_multi_speed_ensemble_votes_on_clean_uptrend() -> None:
    close = pd.Series([100.0 + value * 0.5 for value in range(180)])
    assert FORENSIC.ensemble_votes(close, "long") == 3
    assert FORENSIC.ensemble_votes(close, "short") == 0


def test_regime_marks_clean_trend_persistent() -> None:
    close = pd.Series([100.0 + value * 0.4 for value in range(180)])
    frame = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1.0,
        }
    )
    result = FORENSIC.classify_regime(frame, "long", votes=3)
    assert result["regime"] == "TREND_PERSISTENT"
