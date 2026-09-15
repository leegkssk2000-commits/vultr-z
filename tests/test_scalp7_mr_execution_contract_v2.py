"""Artificial execution-contract tests only; not a historical economic run."""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild.scalp7_execution_v2 import replay

TF = 1_800_000
BTC, ETH = "BTC-USDT", "ETH-USDT"


def bars() -> dict[str, pd.DataFrame]:
    result = {}
    for symbol, prices, segment in [
        (BTC, [100, 100, 102, 101], 0),
        (ETH, [100, 100, 99, 100], 4),
    ]:
        result[symbol] = pd.DataFrame(
            [
                {
                    "open_ts_ms": i * TF,
                    "close_ts_ms": (i + 1) * TF,
                    "available_ts_ms": (i + 1) * TF,
                    "segment_id": segment,
                    "open": px,
                    "high": px + 1,
                    "low": px - 1,
                    "close": px,
                }
                for i, px in enumerate(prices)
            ]
        )
    return result


def signal() -> dict[str, Any]:
    return {
        "identity": "UNIT_TEST_PAIR_ONLY",
        "lane": "cross_sectional_mean_reversion",
        "symbol": BTC + "|" + ETH,
        "timeframe_min": 30,
        "signal_open_ts_ms": 0,
        "signal_ts_ms": TF,
        "segment_id": "0",
        "max_hold_bars": 1,
        "legs": [
            {"symbol": BTC, "side": 1, "weight": 0.5},
            {"symbol": ETH, "side": -1, "weight": 0.5},
        ],
        "meta": {"pair_segment_ids": {BTC: "0", ETH: "4"}},
    }


def close_exit(position: dict[str, Any], bar: Any, history: Any) -> dict[str, Any]:
    del position, bar, history
    return {"exit_next_open": True, "reason": "UNIT_TEST_CLOSE"}


def test_canonical_pair_segment_binding_and_next_open_arithmetic() -> None:
    result = replay([signal()], bars(), {BTC: 14.0, ETH: 14.0}, exit_update=close_exit)
    row = result["trades"][0]
    assert row["entry_ts_ms"] == TF
    assert row["exit_ts_ms"] == row["outcome_available_ts_ms"] == 2 * TF
    assert row["gross_bps"] == pytest.approx(150.0)
    assert row["cost_bps"] == pytest.approx(14.0)
    assert row["net_bps"] == pytest.approx(136.0)
    assert row["entry_prices"] == {BTC: 100.0, ETH: 100.0}
    assert row["exit_prices"] == {BTC: 102.0, ETH: 99.0}


def test_pair_rejects_wrong_canonical_segment_binding() -> None:
    item = signal()
    item["meta"]["pair_segment_ids"][ETH] = "5"
    result = replay([item], bars(), {BTC: 14.0, ETH: 14.0}, exit_update=close_exit)
    assert result["trades"] == []
    assert result["rejections"]["PAIR_SIGNAL_SEGMENT_MISMATCH"] == 1


def test_pair_delayed_close_cannot_exit_at_earlier_open() -> None:
    frames = bars()
    frames[ETH].loc[1, "available_ts_ms"] = 2 * TF + 1
    result = replay([signal()], frames, {BTC: 14.0, ETH: 14.0}, exit_update=close_exit)
    assert result["trades"] == []
    assert (
        result["unresolved"][0]["position"]["unresolved_reason"]
        == "LATE_BAR_AVAILABILITY"
    )


def test_pair_gap_cannot_manufacture_a_common_exit() -> None:
    frames = bars()
    frames[ETH] = frames[ETH].drop(index=2)
    result = replay([signal()], frames, {BTC: 14.0, ETH: 14.0}, exit_update=close_exit)
    assert result["trades"] == []
    assert len(result["unresolved"]) == 1


def test_negative_leg_cost_cannot_hide_in_positive_weighted_sum() -> None:
    with pytest.raises(ValueError, match="LEG_COST"):
        replay([signal()], bars(), {BTC: 30.0, ETH: -1.0}, exit_update=close_exit)


def test_late_observed_signal_is_not_filled_at_earlier_historical_open() -> None:
    item = signal()
    frames = bars()
    for frame in frames.values():
        frame["available_ts_ms"] += 1000
    item["signal_ts_ms"] += 1000
    result = replay([item], frames, {BTC: 14.0, ETH: 14.0}, exit_update=close_exit)
    assert result["trades"] == []
    assert result["rejections"]["LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"] == 1
