from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pandas as pd


def load_module():
    path = Path(os.environ["R7A4D2_SCALP_DISCOVERY_36"])
    spec = importlib.util.spec_from_file_location("scalp_discovery_36", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def structure_frame() -> pd.DataFrame:
    highs = [100.0, 101.0, 103.0, 101.5, 101.0, 102.0, 104.0, 102.5, 102.0, 101.0]
    return pd.DataFrame(
        {
            "__timestamp": [1_000 + index * 60_000 for index in range(len(highs))],
            "high": highs,
            "close": [value - 0.5 for value in highs],
        }
    )


def test_window_starts_include_final_window() -> None:
    module = load_module()
    starts = module.window_starts(1000)
    assert starts[0] == 0
    assert starts[-1] == 360
    assert len(starts) == len(set(starts))


def test_latest_confirmed_pivot_high_uses_only_prior_bars() -> None:
    module = load_module()
    frame = structure_frame()
    pivot = module.latest_confirmed_pivot_high(frame, int(frame.iloc[-1]["__timestamp"]) + 1)
    assert pivot is not None
    high, timestamp, index = pivot
    assert high == 104.0
    assert timestamp == frame.iloc[6]["__timestamp"]
    assert index == 6


def test_natural_short_distance() -> None:
    module = load_module()
    assert module.natural_short_distance(100.0, 101.0) == 1.0
    assert module.natural_short_distance(100.0, 99.0) == 0.0


def test_round_robin_selection_preserves_symbol_diversity() -> None:
    module = load_module()
    candidates = []
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for index in range(5):
            candidates.append(
                {
                    "candidate_id": f"{symbol}-{index}",
                    "symbol": symbol,
                    "timestamp": index * 10 + (0 if symbol == "BTCUSDT" else 1 if symbol == "ETHUSDT" else 2),
                }
            )
    selected = module.round_robin_select(candidates, 6)
    assert len(selected) == 6
    assert {row["symbol"] for row in selected} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


def test_assign_split_is_six_and_six() -> None:
    module = load_module()
    selected = [{"candidate_id": str(index)} for index in range(12)]
    result = module.assign_split(selected)
    assert sum(row["split"] == "discovery" for row in result) == 6
    assert sum(row["split"] == "validation" for row in result) == 6


def test_adapter_bind_validation_fail_closes() -> None:
    module = load_module()
    bind = {
        "state": "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
        "blocker_count": 0,
        "candidate_discovery_ready": True,
        "bound_source_count": 5,
        "bound_symbol_count": 5,
        "layout_signature": [6, 0, 1, 2, 3, 4],
        "next_stage": "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36",
        "source_allowlist": [{}] * 5,
    }
    assert len(module.validate_bind(bind)) == 5
    bind["layout_signature"] = [6, 0, 1, 5, 3, 4]
    try:
        module.validate_bind(bind)
    except ValueError as exc:
        assert "BOUND_LAYOUT_SIGNATURE_INVALID" in str(exc)
    else:
        raise AssertionError("invalid layout must fail")
