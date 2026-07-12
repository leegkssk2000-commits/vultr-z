from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_job_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_continuation_partial_history_job.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_continuation_job", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


JOB = load_job_module()
BASE = JOB.BASE


def raw_frame(rows):
    start = int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp() * 1000)
    records = []
    for index, values in enumerate(rows):
        open_, high, low, close = values
        records.append(
            {
                "ts": start + index * 60_000,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1.0,
                "raw_idx": index,
            }
        )
    return pd.DataFrame(records)


def event(frame, side="long"):
    return {
        "event_id": "x",
        "window": "prior_holdout_90d",
        "symbol": "BTCUSDT",
        "side": side,
        "signal_ts": int(frame.iloc[0]["ts"]) - 60_000,
        "entry_ts": int(frame.iloc[0]["ts"]),
        "entry": 100.0,
        "base_risk": 1.0,
        "label": "TIMEOUT",
        "net_R_0.15": 0.0,
        "features": {},
    }


def test_baseline_reaches_2r() -> None:
    frame = raw_frame(
        [
            (100.0, 100.4, 99.8, 100.2),
            (100.2, 101.2, 100.0, 101.0),
            (101.0, 102.1, 100.8, 102.0),
        ]
    )
    trade = BASE.simulate_policy(frame, event(frame), "baseline_fixed_2R")
    assert trade is not None
    assert trade["outcome"] == "TP"
    assert trade["gross_R"] == 2.0


def test_partial_keep_stop_locks_point_one_r() -> None:
    frame = raw_frame(
        [
            (100.0, 100.3, 99.8, 100.1),
            (100.1, 101.6, 100.0, 101.5),
            (101.5, 101.6, 99.4, 99.5),
        ]
    )
    trade = BASE.simulate_policy(frame, event(frame), "partial30_at_1_5R_keep_stop")
    assert trade is not None
    assert trade["outcome"] == "PARTIAL_SL"
    assert round(trade["gross_R"], 8) == 0.10


def test_partial_be_locks_point_four_five_r() -> None:
    frame = raw_frame(
        [
            (100.0, 100.3, 99.8, 100.1),
            (100.1, 101.6, 100.0, 101.5),
            (101.5, 101.6, 99.9, 100.0),
        ]
    )
    trade = BASE.simulate_policy(frame, event(frame), "partial30_at_1_5R_be_runner")
    assert trade is not None
    assert trade["outcome"] == "PARTIAL_BE"
    assert round(trade["gross_R"], 8) == 0.45


def test_full_exit_15r_is_exact() -> None:
    frame = raw_frame(
        [
            (100.0, 100.3, 99.8, 100.1),
            (100.1, 101.6, 100.0, 101.5),
        ]
    )
    trade = BASE.simulate_policy(frame, event(frame), "full_exit_1_5R")
    assert trade is not None
    assert trade["outcome"] == "TP"
    assert trade["gross_R"] == 1.5


def test_continuation_stops_after_15_before_later_2r() -> None:
    frame = raw_frame(
        [
            (100.0, 100.3, 99.8, 100.1),
            (100.1, 101.6, 100.0, 101.5),
            (101.5, 101.6, 99.4, 99.5),
            (99.5, 102.2, 99.4, 102.0),
        ]
    )
    report = JOB.conservative_first_touch_analysis(frame, event(frame))
    assert report is not None
    assert report["reached_2R"] is False
    assert report["continuation_outcome"] == "SL_AFTER_1_5R"


def test_same_bar_stop_and_15r_is_rejected_conservatively() -> None:
    frame = raw_frame([(100.0, 101.6, 99.4, 100.2)])
    report = JOB.conservative_first_touch_analysis(frame, event(frame))
    assert report is None


def test_overlap_boundaries() -> None:
    assert BASE.overlap(10, 20, 20, 30) is True
    assert BASE.overlap(10, 19, 20, 30) is False


def test_metrics_month_stability() -> None:
    frame = raw_frame([(100.0, 102.1, 99.8, 102.0)])
    trade = BASE.simulate_policy(frame, event(frame), "baseline_fixed_2R")
    assert trade is not None
    report = BASE.metrics([trade], 0.15)
    assert report["events"] == 1
    assert report["positive_symbols"] == 1
    assert report["nonnegative_month_ratio"] == 1.0
