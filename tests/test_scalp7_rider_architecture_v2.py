from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_rider_architecture_v2 as rider


def bars(values: Sequence[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * 900_000,
                "close_ts_ms": (i + 1) * 900_000,
                "available_ts_ms": (i + 1) * 900_000,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1.0,
                "segment_id": "A",
            }
            for i, (o, h, low, c) in enumerate(values)
        ]
    )


def example() -> pd.DataFrame:
    return bars(
        [(100, 102, 98, 101)] * 4
        + [
            (101, 106, 100, 105),
            (105, 105.5, 99.5, 101),
            (101, 107, 100, 106),
            (106, 108, 105, 107),
        ]
    )


def test_three_distinct_completed_stages_and_real_stop() -> None:
    x = example()
    assert not rider.generate_signals({"BTC-USDT": x.iloc[:6]})
    rows = rider.generate_signals({"BTC-USDT": x})
    assert len(rows) == 1
    row = rows[0]
    assert row["side"] == 1
    assert row["signal_open_ts_ms"] == 6 * 900_000
    assert row["signal_ts_ms"] == 7 * 900_000
    assert row["stop_price"] == 99.5
    assert (
        row["meta"]["impulse_open_ts_ms"]
        < row["meta"]["pullback_open_ts_ms"]
        < row["signal_open_ts_ms"]
    )


def test_short_is_structural_mirror() -> None:
    x = example()
    mirrored = x.copy()
    mirrored["open"] = 200 - x["open"]
    mirrored["close"] = 200 - x["close"]
    mirrored["low"] = 200 - x["high"]
    mirrored["high"] = 200 - x["low"]
    rows = rider.generate_signals({"ETH-USDT": mirrored})
    assert len(rows) == 1
    assert rows[0]["side"] == -1
    assert rows[0]["stop_price"] == 100.5


def test_future_price_does_not_change_already_emitted_signal() -> None:
    x = example()
    base = rider.generate_signals({"BTC-USDT": x.iloc[:7]})
    x.loc[7, ["open", "high", "low", "close"]] = [107, 200, 1, 180]
    extended = rider.generate_signals({"BTC-USDT": x})
    assert extended[0] == base[0]


def test_previous_close_improvement_is_not_pullback_grammar() -> None:
    x = bars(
        [(100, 102, 98, 101)] * 4
        + [
            (101, 106, 100, 105),
            (105, 107, 101, 106),
            (106, 108, 102, 107),
            (107, 109, 103, 108),
        ]
    )
    assert rider.generate_signals({"BTC-USDT": x}) == []


def test_impulse_origin_loss_invalidates_setup() -> None:
    x = example()
    x.loc[5, "low"] = 97
    assert rider.generate_signals({"BTC-USDT": x}) == []


@pytest.mark.parametrize("kind", ["gap", "segment", "late_previous"])
def test_reset_across_missing_or_unavailable_context(kind: str) -> None:
    x = example()
    if kind == "gap":
        for col in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            x.loc[6:, col] += 900_000
    elif kind == "segment":
        x.loc[6:, "segment_id"] = "B"
    else:
        x.loc[5, "available_ts_ms"] += 5 * 900_000
    assert rider.generate_signals({"BTC-USDT": x}) == []


def test_setup_expiry_is_fixed_and_does_not_refresh_on_pullback() -> None:
    x = bars(
        [(100, 102, 98, 101)] * 4
        + [(101, 106, 100, 105)]
        + [(103, 105.5, 100.5, 104)] * 8
        + [(104, 105, 99.5, 101), (101, 107, 100, 106)]
    )
    assert rider.generate_signals({"BTC-USDT": x}) == []


@pytest.mark.parametrize(
    "column,value,error",
    [
        ("open_ts_ms", 1, "UTC_15M"),
        ("available_ts_ms", 1, "PREMATURE"),
        ("high", 1, "GEOMETRY"),
        ("close", float("nan"), "INVALID_PRICE"),
    ],
)
def test_invalid_source_fails_closed(column: str, value: Any, error: str) -> None:
    x = example()
    x.loc[0, column] = value
    with pytest.raises(ValueError, match=error):
        rider.generate_signals({"BTC-USDT": x})


def test_confirmed_swing_only_returns_next_bar_stop() -> None:
    h = bars([(103, 106, 102, 104), (104, 105, 101, 103), (103, 107, 102, 106)])
    p = {"entry_ts_ms": 0, "stop_price": 99, "side": 1}
    update = rider.exit_update(p, h.iloc[-1].to_dict(), h)
    assert update == {
        "exit_next_open": False,
        "reason": "RIDER_CONFIRMED_PULLBACK_PIVOT",
        "next_stop": 101.0,
    }
    assert p["stop_price"] == 99


def test_unconfirmed_pivot_never_ratchets_or_loosens_stop() -> None:
    h = bars([(103, 106, 102, 104), (104, 105, 101, 103), (103, 105, 102, 104)])
    assert "next_stop" not in rider.exit_update(
        {"entry_ts_ms": 0, "stop_price": 99, "side": 1}, h.iloc[-1].to_dict(), h
    )
    h.loc[2, ["high", "close"]] = [107, 106]
    assert "next_stop" not in rider.exit_update(
        {"entry_ts_ms": 0, "stop_price": 102, "side": 1}, h.iloc[-1].to_dict(), h
    )


def test_lifecycle_rejects_future_prefix() -> None:
    h = example()
    with pytest.raises(ValueError, match="PREFIX_MISMATCH"):
        rider.exit_update(
            {"entry_ts_ms": 0, "stop_price": 99, "side": 1}, h.iloc[-2].to_dict(), h
        )


def test_late_pivot_cannot_tighten_stop_before_availability() -> None:
    h = bars([(103, 106, 102, 104), (104, 105, 101, 103), (103, 107, 102, 106)])
    h.loc[1, "available_ts_ms"] = 10 * 900_000
    p = {"entry_ts_ms": 0, "stop_price": 99, "side": 1}
    update = rider.exit_update(p, h.iloc[-1].to_dict(), h)
    assert update["reason"] == "RIDER_PIVOT_NOT_AVAILABLE_HOLD"
    assert "next_stop" not in update
