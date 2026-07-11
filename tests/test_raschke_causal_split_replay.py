from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_causal_split_replay.py"
    spec = importlib.util.spec_from_file_location("test_raschke_causal_split_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def bar(bucket: str, *, open_: float, high: float, low: float, close: float, raw_end_idx: int):
    return pd.Series(
        {
            "bucket": pd.Timestamp(bucket),
            "complete": True,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "raw_end_idx": raw_end_idx,
            "ts": int(pd.Timestamp(bucket).timestamp() * 1000),
            "volume": 1.0,
        }
    )


def passing_metrics(*, events: int = 80, avg: float = 0.10, pf: float = 1.4, mdd: float = 3.0, symbols: int = 4):
    return {
        "events": events,
        "avg_net_R": avg,
        "profit_factor_R": pf,
        "max_drawdown_R": mdd,
        "positive_symbols": symbols,
    }


def test_utc_session_boundaries() -> None:
    for hour, expected in (
        (0, "utc_00_07"),
        (7, "utc_00_07"),
        (8, "utc_08_15"),
        (15, "utc_08_15"),
        (16, "utc_16_23"),
        (23, "utc_16_23"),
    ):
        stamp = int(pd.Timestamp(f"2026-01-01T{hour:02d}:00:00Z").timestamp() * 1000)
        assert MODULE.utc_session(stamp) == expected


def test_next_complete_bar_requires_exact_next_hour() -> None:
    signal = bar("2026-01-01T10:00:00Z", open_=100, high=102, low=99, close=101, raw_end_idx=59)
    confirm = bar("2026-01-01T11:00:00Z", open_=101, high=102, low=98, close=99, raw_end_idx=119)
    bars = pd.DataFrame([signal, confirm])
    found = MODULE.next_complete_bar(bars, end_i=1, signal_bar=signal)
    assert found is not None
    assert int(found["raw_end_idx"]) == 119

    broken = bars.copy()
    broken.loc[1, "bucket"] = pd.Timestamp("2026-01-01T12:00:00Z")
    assert MODULE.next_complete_bar(broken, end_i=1, signal_bar=signal) is None


def test_short_followthrough_requires_bearish_close_below_signal_low() -> None:
    signal = bar("2026-01-01T10:00:00Z", open_=100, high=102, low=99, close=101, raw_end_idx=59)
    passed = bar("2026-01-01T11:00:00Z", open_=100, high=101, low=97, close=98, raw_end_idx=119)
    failed = bar("2026-01-01T11:00:00Z", open_=100, high=101, low=98, close=99.5, raw_end_idx=119)
    assert MODULE.short_followthrough_pass(signal, passed) is True
    assert MODULE.short_followthrough_pass(signal, failed) is False


def test_lane_decision_blocks_short_long_only_and_link() -> None:
    signal = bar("2026-01-01T10:00:00Z", open_=100, high=102, low=99, close=101, raw_end_idx=59)
    bars = pd.DataFrame([signal])
    result = {"entry": 100.0, "sl": 101.0, "side": "short"}

    passed, entry_idx, _, reason = MODULE.lane_decision(
        "long_only_core",
        symbol="BTCUSDT",
        side="short",
        signal_ts=int(signal["ts"]),
        signal_bar=signal,
        bars=bars,
        end_i=1,
        initial_result=result,
    )
    assert passed is False
    assert entry_idx is None
    assert reason == "short_routed_to_observer"

    passed, entry_idx, _, reason = MODULE.lane_decision(
        "link_reserve",
        symbol="LINKUSDT",
        side="long",
        signal_ts=int(signal["ts"]),
        signal_bar=signal,
        bars=bars,
        end_i=1,
        initial_result=result,
    )
    assert passed is False
    assert entry_idx is None
    assert reason == "link_observer_only"


def test_utc_hold_blocks_only_first_session() -> None:
    signal = bar("2026-01-01T03:00:00Z", open_=100, high=102, low=99, close=101, raw_end_idx=59)
    bars = pd.DataFrame([signal])
    result = {"entry": 100.0, "sl": 99.0, "side": "long"}
    passed, _, _, reason = MODULE.lane_decision(
        "utc_00_07_hold",
        symbol="BTCUSDT",
        side="long",
        signal_ts=int(signal["ts"]),
        signal_bar=signal,
        bars=bars,
        end_i=1,
        initial_result=result,
    )
    assert passed is False
    assert reason == "utc_00_07_hold"


def test_reconfirm_short_uses_second_complete_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULE.V2, "WINDOW_BARS", 3)
    monkeypatch.setattr(MODULE.V2, "window_is_contiguous", lambda _window: True)
    monkeypatch.setattr(
        MODULE.V2,
        "strategy",
        lambda _frame, config: {"action": "enter", "side": "short", "entry": 100.0, "sl": 101.0},
    )
    monkeypatch.setattr(MODULE.V2, "entry_pass", lambda _candidate, _result: True)
    bars = pd.DataFrame(
        [
            bar("2026-01-01T09:00:00Z", open_=102, high=103, low=101, close=102, raw_end_idx=59),
            bar("2026-01-01T10:00:00Z", open_=102, high=102, low=100, close=101, raw_end_idx=119),
            bar("2026-01-01T11:00:00Z", open_=101, high=101, low=99, close=100, raw_end_idx=179),
            bar("2026-01-01T12:00:00Z", open_=100, high=100, low=98, close=99, raw_end_idx=239),
        ]
    )
    result = MODULE.reconfirm_short(bars, end_i=3)
    assert result is not None
    assert result["side"] == "short"


def test_long_specialist_gate_can_pass_without_general_retention() -> None:
    assessment = MODULE.assess_lane(
        "long_only_core",
        prior=passing_metrics(avg=0.20),
        second=passing_metrics(events=20, avg=-0.02),
        combined=passing_metrics(events=41, avg=0.10, pf=1.42, mdd=3.3, symbols=3),
        cost020=passing_metrics(events=41, avg=0.07),
        blocks={"nonnegative_block_ratio": 0.75},
        retention_pct=39.0,
    )
    assert assessment["pass"] is True
    assert "retention" not in assessment["checks"]


def test_general_split_requires_retention_and_second_window_floor() -> None:
    assessment = MODULE.assess_lane(
        "utc_00_07_hold",
        prior=passing_metrics(avg=0.20),
        second=passing_metrics(events=30, avg=-0.10),
        combined=passing_metrics(events=75, avg=0.12, pf=1.45, mdd=5.0, symbols=3),
        cost020=passing_metrics(events=75, avg=0.08),
        blocks={"nonnegative_block_ratio": 0.75},
        retention_pct=71.0,
    )
    assert assessment["pass"] is False
    assert "second_window" in assessment["failed_checks"]
