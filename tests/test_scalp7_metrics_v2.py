from __future__ import annotations

from typing import Any

import pytest

from backend.research.rebuild import scalp7_metrics_v2 as metrics

DAY = 86_400_000


def trade(
    net: float, signal: int = 0, entry: int = 0, exited: int = 900_000, **extra: Any
) -> dict[str, Any]:
    return {
        "identity": "test",
        "lane": "test",
        "symbol": "BTC-USDT",
        "side": 1,
        "signal_ts_ms": signal,
        "entry_ts_ms": entry,
        "exit_ts_ms": exited,
        "outcome_available_ts_ms": exited,
        "gross_bps": net + 10,
        "cost_bps": 10,
        "net_bps": net,
        **extra,
    }


def test_full_calendar_denominator_and_exact_economics() -> None:
    rows = [trade(20), trade(-10, exited=1_800_000), trade(5, exited=2_700_000)]
    result = metrics.summarize(rows, 0, 2 * DAY)
    assert result["T"] == 3
    assert result["T_per_day"] == 1.5
    assert result["WR"] == pytest.approx(2 / 3)
    assert result["Gross_bps"] == 45
    assert result["Net_bps"] == 15
    assert result["PF"] == 2.5
    assert result["DD_bps"] == 10
    assert result["hold_median_min"] == 30
    assert result["hold_p95_min"] == 43.5
    assert result["largest_winner_contribution"] == 0.8


def test_cost_stress_does_not_mutate_source_net() -> None:
    row = trade(5)
    result = metrics.summarize([row], 0, DAY, cost_multiplier=2)
    assert result["Net_bps"] == -5
    assert result["Cost_bps"] == 20
    assert result["WR"] == 0
    assert row["net_bps"] == 5


def test_half_open_outcome_boundary_and_carry_in() -> None:
    rows = [
        trade(10, signal=-1),
        trade(10, signal=0, entry=0, exited=DAY),
        trade(10, signal=DAY, entry=DAY, exited=DAY + 900_000),
        trade(10),
    ]
    result = metrics.summarize(rows, 0, DAY)
    assert result["T"] == 1
    assert sum(result["excluded_counts"].values()) == 3


def test_rolling_windows_do_not_relabel_late_outcome_as_oos() -> None:
    rows = [trade(10, signal=DAY - 900_000, entry=DAY - 900_000, exited=DAY + 900_000)]
    result = metrics.rolling_summary(
        rows, [{"start_ms": 0, "end_ms": DAY}, {"start_ms": DAY, "end_ms": 2 * DAY}]
    )
    assert [r["T"] for r in result["windows"]] == [0, 0]
    assert result["rolling_positive_window_ratio"] == 0
    assert result["nonempty_positive_window_ratio"] is None


def test_empty_window_keeps_full_preregistered_denominator() -> None:
    result = metrics.rolling_summary(
        [trade(10)],
        [{"start_ms": 0, "end_ms": DAY}, {"start_ms": DAY, "end_ms": 2 * DAY}],
    )
    assert result["rolling_positive_window_ratio"] == 0.5
    assert result["nonempty_positive_window_ratio"] == 1


def test_simultaneous_realized_cohort_has_no_artificial_intratime_dd() -> None:
    rows = [trade(-20), trade(30, symbol="ETH-USDT")]
    assert metrics.summarize(rows, 0, DAY)["DD_bps"] == 0
    assert metrics.summarize(list(reversed(rows)), 0, DAY)["DD_bps"] == 0


def test_pf_null_explained_and_loss_tail_exact() -> None:
    assert metrics.summarize([trade(2)], 0, DAY)["PF_null_reason"] == "NO_LOSING_TRADES"
    assert metrics.summarize([], 0, DAY)["PF_null_reason"] == "NO_TRADES"
    rows = [trade(float(-n), exited=n * 900_000) for n in range(1, 21)]
    result = metrics.summarize(rows, 0, DAY)
    assert result["loss_tail"]["worst_5pct_losing_trades_mean_bps"] == -20
    assert result["MaxLossStreak"] == 20


def test_concentration_negative_groups_preserved() -> None:
    result = metrics.summarize([trade(20), trade(-5, symbol="ETH-USDT")], 0, DAY)
    groups = result["concentration"]["symbol"]["groups"]
    assert groups["ETH-USDT"]["Net_bps"] == -5
    assert groups["BTC-USDT"]["positive_profit_share"] == 1
    assert groups["ETH-USDT"]["trade_count_share"] == 0.5


@pytest.mark.parametrize(
    "update,error",
    [
        ({"net_bps": 999}, "RECONCILIATION"),
        ({"gross_bps": float("nan")}, "NONFINITE"),
        ({"entry_ts_ms": -1}, "CAUSAL"),
        ({"outcome_available_ts_ms": 1}, "CAUSAL"),
    ],
)
def test_malformed_economics_fail_closed(update: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        metrics.summarize([trade(10, **update)], 0, DAY)


def test_cosine_uses_signed_exposure_all_calendar_buckets() -> None:
    long = [trade(10, exited=1_800_000)]
    opposite = [trade(-10, exited=1_800_000, side=-1)]
    same = metrics.behavior_cosine(long, long, 0, DAY)
    assert same["behavior_cosine"] == pytest.approx(1)
    assert same["duplicate_by_user_rule"] is True
    assert same["full_vector_dimensions"] == 6 * 96
    assert metrics.behavior_cosine(long, opposite, 0, DAY)[
        "behavior_cosine"
    ] == pytest.approx(-1)
    assert (
        metrics.behavior_cosine([], long, 0, DAY)["null_reason"] == "ZERO_EXPOSURE_NORM"
    )


def test_cosine_pair_weights_and_actual_overlap() -> None:
    pair = [
        trade(
            10,
            legs=[
                {"symbol": "BTC-USDT", "side": 1, "weight": 0.5},
                {"symbol": "ETH-USDT", "side": -1, "weight": 0.5},
            ],
        )
    ]
    singles = [
        trade(999, risk_weight=0.5),
        trade(-999, symbol="ETH-USDT", side=-1, risk_weight=0.5),
    ]
    assert metrics.behavior_cosine(pair, singles, 0, DAY)[
        "behavior_cosine"
    ] == pytest.approx(1)
    assert (
        metrics.behavior_cosine(
            [trade(1, entry=0, exited=450_000)],
            [trade(-999, entry=450_000, exited=900_000)],
            0,
            DAY,
        )["behavior_cosine"]
        == 1
    )


def test_cosine_does_not_select_winners_or_delete_carry_in() -> None:
    first = [trade(-100, signal=-900_000, entry=-900_000, exited=900_000)]
    second = [trade(100)]
    assert metrics.behavior_cosine(first, second, 0, DAY)["behavior_cosine"] == 1
