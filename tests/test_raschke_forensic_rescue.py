from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(os.environ.get("Q4R3_ROUTE_A_OVERLAY_ROOT", "/tmp/q4r3-route-a-video-fidelity"))


def synthetic_frame(rows: int = 520) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    trend = 100.0 + index * 0.04
    cycle = np.sin(index / 11.0) * 1.2
    close = trend + cycle
    open_ = close - np.sin(index / 4.0) * 0.22
    high = np.maximum(open_, close) + 0.45
    low = np.minimum(open_, close) - 0.45
    volume = 1000.0 + (np.cos(index / 8.0) + 1.5) * 250.0
    return pd.DataFrame(
        {
            "ts": (index.astype(int) + 1) * 3_600_000,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.mark.parametrize(
    "mode",
    [
        "source_core",
        "candle_direction",
        "body_close",
        "trend_strength",
        "pdm_proxy_v1",
    ],
)
def test_predeclared_modes_are_deterministic_and_fail_closed(mode: str) -> None:
    module = importlib.import_module("backend.strategies.raschke_macd_ema200")
    config = module.RaschkeMacdEma200Config(confirmation_mode=mode)
    frame = synthetic_frame()
    original = frame.copy(deep=True)
    first = module.strategy(frame, config=config)
    second = module.strategy(frame, config=config)
    pd.testing.assert_frame_equal(frame, original)
    assert first == second
    assert first["action"] in {"hold", "enter"}
    assert first["strategy"] == "raschke_macd_ema200"


def test_unknown_proxy_mode_is_blocked() -> None:
    module = importlib.import_module("backend.strategies.raschke_macd_ema200")
    result = module.strategy(
        synthetic_frame(),
        config=module.RaschkeMacdEma200Config(confirmation_mode="invented_proxy"),
    )
    assert result["action"] == "hold"
    assert result["why"] == "raschke_macd_ema200_invalid_confirmation_mode"


def _load_forensic_module():
    path = ROOT / "tools" / "q4r3_route_a_raschke_forensic_rescue.py"
    spec = importlib.util.spec_from_file_location("test_raschke_forensic_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gate_boundaries_and_discovery_score() -> None:
    module = _load_forensic_module()
    passing = {
        "events": 50,
        "avg_net_R": 0.15,
        "profit_factor_R": 1.20,
        "max_drawdown_R": 8.0,
        "positive_symbols": 3,
    }
    assert module.passes_gate(passing, module.HARD_GATE)
    failing = dict(passing)
    failing["max_drawdown_R"] = 8.0001
    assert not module.passes_gate(failing, module.HARD_GATE)
    assert module.discovery_score(passing) > module.discovery_score(failing)


def test_bucket_boundaries_are_stable() -> None:
    module = _load_forensic_module()
    assert module._bucket(0.75, (0.75, 1.50), ("a", "b", "c")) == "a"
    assert module._bucket(1.50, (0.75, 1.50), ("a", "b", "c")) == "b"
    assert module._bucket(1.51, (0.75, 1.50), ("a", "b", "c")) == "c"
