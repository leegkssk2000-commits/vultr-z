from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "backend/tools/zel_historical_oos_data_collector_v1.py"
    spec = importlib.util.spec_from_file_location("zel_historical_oos", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_window_plan_is_non_overlapping_and_pre_authority():
    module = load_module()
    windows = module.build_windows()
    assert len(windows) == 6
    assert {item.interval for item in windows} == {"1m", "15m"}
    for interval in ("1m", "15m"):
        group = [item for item in windows if item.interval == interval]
        assert len(group) == 3
        interval_ms = module.INTERVALS[interval]["ms"]
        assert group[-1].end_ms < module.AUTHORITY_END_MS
        for left, right in zip(group, group[1:]):
            assert left.end_ms + interval_ms == right.start_ms


def test_expected_total_market_rows():
    module = load_module()
    total = 0
    for item in module.build_windows():
        interval_ms = module.INTERVALS[item.interval]["ms"]
        total += ((item.end_ms - item.start_ms) // interval_ms + 1) * len(module.SYMBOLS)
    assert total == 302_400


def test_validate_frame_rejects_gaps_and_accepts_exact_sequence():
    module = load_module()
    interval_ms = 60_000
    start = 1_800_000
    end = start + 2 * interval_ms
    frame = pd.DataFrame(
        [
            [start, 100.0, 101.0, 99.0, 100.5, 10.0],
            [start + interval_ms, 100.5, 102.0, 100.0, 101.0, 11.0],
            [end, 101.0, 103.0, 100.5, 102.0, 12.0],
        ],
        columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
    )
    module.validate_frame(frame.copy(), start, end, interval_ms)
    broken = frame.drop(index=1).reset_index(drop=True)
    try:
        module.validate_frame(broken, start, end, interval_ms)
    except RuntimeError as exc:
        assert str(exc).startswith("ROWS:")
    else:
        raise AssertionError("gap was not rejected")
