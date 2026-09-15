from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from backend.research.rebuild import scalp7_rolling_context_v2 as context

DAY = context.DAY
HOUR = context.HOUR


def frame(n: int = 240, start: int = 0) -> pd.DataFrame:
    t = np.arange(n, dtype=np.int64) * (HOUR // 2) + start
    close = 100 + np.arange(n) * 0.01 + np.sin(np.arange(n) / 7)
    return pd.DataFrame(
        {
            "open_ts_ms": t,
            "close_ts_ms": t + HOUR // 2,
            "available_ts_ms": t + HOUR // 2,
            "open": close,
            "close": close,
            "high": close + 1,
            "low": close - 1,
            "segment_id": "A",
        }
    )


def features(n: int = 100, start: int = 0) -> pd.DataFrame:
    t = np.arange(n, dtype=np.int64) * HOUR + start
    return pd.DataFrame(
        {
            "context_open_ts_ms": t,
            "regime_available_ts_ms": t + HOUR,
            "dispersion24": np.arange(n) / 1000 + 0.01,
            "mean_abs24": np.arange(n) / 1000 + 0.02,
            "breadth": np.where(np.arange(n) % 2, 4, -2),
            "vol_ratio": np.arange(n) / 100 + 1,
        }
    )


def first_window() -> dict[str, Any]:
    return context.windows(0, 365 * DAY)[0]


def test_calendar_has_initial90days_then_nonoverlapping30day_windows() -> None:
    rows = context.windows(0, 365 * DAY)
    assert len(rows) == 10
    assert rows[0]["start_ms"] == 90 * DAY
    assert rows[0]["partition"] == "validation"
    assert rows[1]["partition"] == "rolling"
    assert rows[-1]["end_ms"] == 365 * DAY
    assert rows[-1]["partial_window"] is True
    assert all(
        r["train_end_ms"] == r["start_ms"]
        and r["train_start_ms"] == r["start_ms"] - 90 * DAY
        for r in rows
    )
    assert all(
        rows[i]["start_ms"] == rows[i - 1]["end_ms"] for i in range(1, len(rows))
    )


def test_hourly_requires_two_exact_completed_bars_and_string_segments() -> None:
    x = frame(5)
    result = context.hourly({"BTC-USDT": x})["BTC-USDT"]
    assert result.index.tolist() == [0, HOUR]
    assert result.iloc[0]["close"] == x.iloc[1]["close"]
    assert result.iloc[0]["available_ts_ms"] == HOUR
    x.loc[1, "segment_id"] = "B"
    assert 0 not in context.hourly({"BTC-USDT": x})["BTC-USDT"].index
    assert context.hourly({"BTC-USDT": frame(1)})["BTC-USDT"].empty


def test_hourly_gap_resets_feature_warmup() -> None:
    x = frame(200)
    x = x.drop(index=[100, 101]).reset_index(drop=True)
    result = context.hourly({"BTC-USDT": x})["BTC-USDT"]
    assert np.isnan(result.loc[51 * HOUR, "r24"])
    assert np.isnan(result.loc[51 * HOUR, "vr"])


def test_hourly_features_inherit_every_earlier_input_availability() -> None:
    x = frame(100)
    x.loc[0, "available_ts_ms"] = 500 * HOUR
    result = context.hourly({"BTC-USDT": x})["BTC-USDT"]
    assert (result["available_ts_ms"] == 500 * HOUR).all()


def test_cross_features_prefix_identical_when_future_prices_change() -> None:
    frames = {symbol: frame() for symbol in context.SYMBOLS}
    first = context.cross_features({k: v.iloc[:160] for k, v in frames.items()})
    for value in frames.values():
        value.loc[160:, ["open", "high", "low", "close"]] *= 2
    full = context.cross_features(frames)
    pd.testing.assert_frame_equal(
        first.reset_index(drop=True),
        full[full["context_open_ts_ms"] < 80 * HOUR].reset_index(drop=True),
    )


def test_fit_is_prior_only_and_source_hashed() -> None:
    train = features(100, start=80 * DAY)
    future = features(100, start=90 * DAY)
    full = pd.concat([train, future], ignore_index=True)
    fit = context.fit_context(full, first_window())
    full.loc[100:, "dispersion24"] = 999
    assert context.fit_context(full, first_window()) == fit
    assert context.fit_context(train, first_window()) == fit
    changed = train.copy()
    changed.loc[0, "breadth"] += 1
    assert (
        context.fit_context(changed, first_window())["training_feature_sha256"]
        != fit["training_feature_sha256"]
    )
    assert fit["last_fit_observation_ms"] < 90 * DAY


def test_exact_train_end_and_stale_late_observation_excluded() -> None:
    train = features(100, start=80 * DAY)
    extra = features(2, start=90 * DAY - HOUR)
    extra.loc[1, "context_open_ts_ms"] = 70 * DAY
    extra.loc[1, "regime_available_ts_ms"] = 89 * DAY
    full = pd.concat([train, extra], ignore_index=True)
    assert context.fit_context(full, first_window()) == context.fit_context(
        train, first_window()
    )


def test_asof_context_never_uses_unfinished_hour_and_restores_open_order() -> None:
    train = features(100, start=80 * DAY)
    test = features(4, start=90 * DAY)
    feats = pd.concat([train, test], ignore_index=True)
    x = frame(8, start=90 * DAY)
    bound, fits = context.bind_context({"BTC-USDT": x}, feats, [first_window()])
    b = bound["BTC-USDT"]
    assert b.iloc[0]["regime"] == "NO_CONTEXT"
    assert b.iloc[1]["context_open_ts_ms"] == 90 * DAY
    assert b.iloc[1]["regime_available_ts_ms"] <= b.iloc[1]["available_ts_ms"]
    assert b["open_ts_ms"].is_monotonic_increasing
    assert fits[0]["train_end_ms"] == 90 * DAY


def test_late_old_context_does_not_look_fresh_when_it_arrives() -> None:
    train = features(100, start=80 * DAY)
    late = features(1, start=85 * DAY)
    late["regime_available_ts_ms"] = 90 * DAY + HOUR
    feats = pd.concat([train, late], ignore_index=True)
    b, _ = context.bind_context(
        {"BTC-USDT": frame(6, start=90 * DAY)}, feats, [first_window()]
    )
    assert (b["BTC-USDT"]["regime"] == "NO_CONTEXT").all()


def test_bind_enforces_next_window_fit_and_open_order_with_delay() -> None:
    features_all = features(24 * 151)
    windows = context.windows(0, 151 * DAY)
    x = frame(6, start=120 * DAY - HOUR)
    x.loc[0, "available_ts_ms"] += 2 * HOUR
    bound, fits = context.bind_context({"BTC-USDT": x}, features_all, windows)
    b = bound["BTC-USDT"]
    assert b["open_ts_ms"].is_monotonic_increasing
    next_window = b[b["available_ts_ms"] >= 120 * DAY]
    assert all(next_window["regime_spec_sha256"] == fits[1]["sha256"])


@pytest.mark.parametrize(
    "kind", ["duplicate", "premature", "wrongclose", "fractional", "badprice"]
)
def test_context_source_integrity_rejected(kind: str) -> None:
    x = frame(10)
    if kind == "duplicate":
        x.loc[1, "open_ts_ms"] = 0
    elif kind == "premature":
        x.loc[0, "available_ts_ms"] = 0
    elif kind == "wrongclose":
        x.loc[0, "close_ts_ms"] = HOUR
    elif kind == "fractional":
        x["open_ts_ms"] = x["open_ts_ms"].astype(float)
        x.loc[0, "open_ts_ms"] = 0.5
    else:
        x.loc[0, "low"] = -1
    with pytest.raises(ValueError):
        context.hourly({"BTC-USDT": x})


def test_window_overlap_and_train_leak_rejected() -> None:
    win = first_window()
    win["train_end_ms"] += DAY
    with pytest.raises(ValueError, match="90D_TRAIN"):
        context.fit_context(features(100), win)
    windows = context.windows(0, 365 * DAY)[:2]
    windows[1]["start_ms"] -= DAY
    with pytest.raises(ValueError, match="NONOVERLAPPING"):
        context.bind_context({"BTC-USDT": frame()}, features(100), windows)
