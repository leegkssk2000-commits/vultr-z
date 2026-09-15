"""Independent causal execution review fixtures; no market/economic evaluation."""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_execution_v2 as e

TF = 1_800_000


def bars(values: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * TF,
                "close_ts_ms": (i + 1) * TF,
                "available_ts_ms": (i + 1) * TF,
                "segment_id": "s1",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
            }
            for i, (o, h, low, c) in enumerate(values)
        ]
    )


def signal(**updates: Any) -> dict[str, Any]:
    return {
        "identity": "qa30",
        "lane": "qa",
        "symbol": "BTC-USDT",
        "timeframe_min": 30,
        "side": 1,
        "signal_open_ts_ms": 0,
        "signal_ts_ms": TF,
        "segment_id": "s1",
        "stop_price": 95,
        "max_hold_bars": 1,
        **updates,
    }


def run(frame: pd.DataFrame, **kw: Any) -> dict[str, Any]:
    return e.replay(
        [signal(**kw.pop("signal_updates", {}))],
        {"BTC-USDT": frame},
        {"BTC-USDT": 14},
        **kw,
    )


def test_same_bar_stop_precedes_target() -> None:
    x = bars([(100, 101, 99, 100), (100, 112, 94, 108), (108, 109, 107, 108)])
    out = run(x, signal_updates={"take_profit_r": 2})
    trade = out["trades"][0]
    assert trade["reason"] == "STOP_FIRST"
    assert trade["exit_prices"]["BTC-USDT"] == 95
    assert trade["net_bps"] == pytest.approx(-514)


def test_entry_bar_open_gap_below_stop_rejects() -> None:
    x = bars([(100, 101, 99, 100), (94, 95, 92, 93)])
    out = run(x)
    assert out["trades"] == []
    assert out["rejections"]["ENTRY_INVALIDATES_STOP"] == 1


def test_open_gap_stop_uses_worse_open() -> None:
    x = bars([(100, 101, 99, 100), (100, 102, 98, 101), (93, 94, 92, 93)])
    out = run(x, signal_updates={"max_hold_bars": 8})
    trade = out["trades"][0]
    assert trade["exit_prices"]["BTC-USDT"] == 93
    assert trade["outcome_available_ts_ms"] == 2 * TF


def test_lifecycle_stop_only_effective_next_bar() -> None:
    x = bars([(100, 101, 99, 100), (100, 110, 96, 109), (107, 108, 106, 107)])
    out = run(
        x,
        signal_updates={"max_hold_bars": 8},
        exit_update=lambda _p, _b, _h: {"next_stop": 108},
    )
    trade = out["trades"][0]
    assert trade["entry_ts_ms"] == TF
    assert trade["exit_ts_ms"] == 2 * TF
    assert trade["exit_prices"]["BTC-USDT"] == 107


def test_unresolved_gap_retains_ownership_and_no_pnl() -> None:
    x = bars([(100, 101, 99, 100)] * 6)
    x.loc[2:, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] += TF
    s2 = signal(signal_open_ts_ms=4 * TF, signal_ts_ms=5 * TF)
    out = e.replay([signal(max_hold_bars=100), s2], {"BTC-USDT": x}, {"BTC-USDT": 14})
    assert out["trades"] == []
    assert len(out["unresolved"]) == 1
    assert out["rejections"]["POSITION_ALREADY_OWNED"] == 1


def test_final_bar_does_not_invent_exit() -> None:
    x = bars([(100, 101, 99, 100), (100, 102, 98, 101)])
    out = run(x)
    assert not out["trades"]
    assert len(out["unresolved"]) == 1


def test_feature_availability_blocks_impossible_entry_open() -> None:
    x = bars([(100, 101, 99, 100), (100, 102, 98, 101)])
    x.loc[0, "available_ts_ms"] = TF + 1
    out = run(x, signal_updates={"signal_ts_ms": TF + 1})
    assert not out["trades"]
    assert out["rejections"]["LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"] == 1


def test_late_callback_cannot_sell_at_earlier_open() -> None:
    x = bars(
        [
            (100, 101, 99, 100),
            (100, 102, 98, 101),
            (110, 111, 108, 109),
            (90, 91, 88, 89),
        ]
    )
    x.loc[1, "available_ts_ms"] = 3 * TF
    out = run(
        x,
        signal_updates={"max_hold_bars": 10},
        exit_update=lambda _p, _b, _h: {"exit_next_open": True, "reason": "QA"},
    )
    assert not any(
        t["exit_ts_ms"] < 3 * TF and t["reason"] == "QA" for t in out["trades"]
    )


def test_intrabar_exit_time_not_claimed_as_open() -> None:
    x = bars([(100, 101, 99, 100), (100, 104, 94, 103)])
    trade = run(x)["trades"][0]
    assert trade["outcome_available_ts_ms"] == 2 * TF
    assert trade["exit_ts_ms"] >= 2 * TF or trade.get("exit_time_interval_ms") == [
        TF,
        2 * TF,
    ]


def test_adaptive_same_bar_partial_price_forbidden() -> None:
    x = bars([(100, 101, 99, 100), (100, 110, 96, 108), (108, 109, 107, 108)])
    with pytest.raises(ValueError, match="PARTIAL"):
        run(
            x,
            exit_update=lambda _p, b, _h: {
                "partial_fraction": 0.5,
                "partial_price": b["high"],
            },
        )


def test_duplicate_signal_not_double_counted() -> None:
    x = bars([(100, 101, 99, 100)] * 3)
    s = signal()
    out = e.replay([s, dict(s)], {"BTC-USDT": x}, {"BTC-USDT": 14})
    assert out["closed_trade_count"] == 1
    assert out["rejections"]["DUPLICATE_SIGNAL"] == 1


def test_pair_gross_and_cost_weight_each_leg_once() -> None:
    btc = bars([(100, 101, 99, 100), (100, 102, 99, 101), (102, 103, 101, 102)])
    eth = bars([(200, 201, 199, 200), (200, 201, 197, 198), (196, 198, 195, 197)])
    s = signal(
        symbol="BTC-ETH",
        legs=[
            {"symbol": "BTC-USDT", "side": 1, "weight": 0.5},
            {"symbol": "ETH-USDT", "side": -1, "weight": 0.5},
        ],
    )
    out = e.replay(
        [s],
        {"BTC-USDT": btc, "ETH-USDT": eth},
        {"BTC-USDT": 10, "ETH-USDT": 20},
        exit_update=lambda *_: {},
    )
    trade = out["trades"][0]
    assert trade["gross_bps"] == pytest.approx(200)
    assert trade["cost_bps"] == 15
    assert trade["net_bps"] == pytest.approx(185)


def test_missing_pair_leg_never_synthetic_fill() -> None:
    btc = bars([(100, 101, 99, 100)] * 5)
    eth = bars([(200, 201, 199, 200)] * 5).drop(index=2).reset_index(drop=True)
    s = signal(
        symbol="BTC-ETH",
        max_hold_bars=9,
        legs=[
            {"symbol": "BTC-USDT", "side": 1, "weight": 0.5},
            {"symbol": "ETH-USDT", "side": -1, "weight": 0.5},
        ],
    )
    out = e.replay(
        [s],
        {"BTC-USDT": btc, "ETH-USDT": eth},
        {"BTC-USDT": 14, "ETH-USDT": 14},
        exit_update=lambda *_: {},
    )
    assert not out["trades"]
    assert len(out["unresolved"]) == 1


@pytest.mark.parametrize("tf", [5, 60, 240])
def test_old_timeframes_cannot_enter_current_portfolio(tf: int) -> None:
    with pytest.raises(ValueError, match="SCALP7"):
        e.validate_signal(signal(timeframe_min=tf))


def test_negative_target_cannot_create_out_of_range_fill() -> None:
    with pytest.raises(ValueError, match="TARGET|TAKE_PROFIT"):
        e.validate_signal(signal(take_profit_r=-2))


def test_adjusted_stop_must_remain_positive_finite() -> None:
    x = bars([(100, 101, 99, 100)] * 3)
    out = run(x, entry_update=lambda *_: {"stop_price": -1.0})
    assert not out["trades"]
    assert out["rejections"]["ENTRY_STOP_INVALID"] == 1


def test_mixed_pair_segments_require_explicit_binding() -> None:
    btc = bars([(100, 101, 99, 100)] * 3)
    eth = bars([(200, 201, 199, 200)] * 3)
    eth["segment_id"] = "different"
    s = signal(
        symbol="BTC-ETH",
        legs=[
            {"symbol": "BTC-USDT", "side": 1, "weight": 0.5},
            {"symbol": "ETH-USDT", "side": -1, "weight": 0.5},
        ],
    )
    out = e.replay(
        [s],
        {"BTC-USDT": btc, "ETH-USDT": eth},
        {"BTC-USDT": 14, "ETH-USDT": 14},
        exit_update=lambda *_: {},
    )
    assert not out["trades"]
    assert out["rejections"].get("PAIR_SIGNAL_SEGMENT_UNBOUND", 0) == 1


def test_late_stop_outcome_retains_ownership_until_known() -> None:
    x = bars(
        [
            (100, 101, 99, 100),
            (100, 101, 94, 99),
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (100, 101, 99, 100),
        ]
    )
    x.loc[1, "available_ts_ms"] = 5 * TF
    later = signal(signal_open_ts_ms=2 * TF, signal_ts_ms=3 * TF)
    out = e.replay([signal(), later], {"BTC-USDT": x}, {"BTC-USDT": 14})
    assert len(out["trades"]) == 1
    assert out["rejections"]["POSITION_ALREADY_OWNED"] == 1


def test_frozen_partial_realized_profit_and_remaining_notional() -> None:
    x = bars([(100, 101, 99, 100), (100, 106, 96, 104), (102, 103, 101, 102)])
    out = run(
        x,
        signal_updates={"partial_take_profit_r": 1, "partial_fraction": 0.3},
        exit_update=lambda _p, _b, _h: {"partial_fraction": 0.3, "partial_price": 105},
    )
    trade = out["trades"][0]
    assert trade["gross_bps"] == pytest.approx(0.3 * 500 + 0.7 * 200)
    assert trade["net_bps"] == pytest.approx(276)


def test_resting_partial_favorable_gap_uses_frozen_limit_conservatively() -> None:
    x = bars(
        [
            (100, 101, 99, 100),
            (100, 104, 96, 103),
            (110, 112, 108, 111),
            (108, 110, 107, 109),
        ]
    )

    def callback(
        p: dict[str, Any], b: dict[str, Any], _h: pd.DataFrame
    ) -> dict[str, Any]:
        if p["hold_bars"] == 2:
            return {
                "partial_fraction": 0.3,
                "partial_price": 105,
                "exit_next_open": True,
                "reason": "QA",
            }
        return {}

    out = run(
        x,
        signal_updates={
            "partial_take_profit_r": 1,
            "partial_fraction": 0.3,
            "max_hold_bars": 8,
        },
        exit_update=callback,
    )
    trade = out["trades"][0]
    assert trade["gross_bps"] == pytest.approx(0.3 * 500 + 0.7 * 800)
    assert trade["net_bps"] == pytest.approx(696)
