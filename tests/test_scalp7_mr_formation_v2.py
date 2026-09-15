from __future__ import annotations

from dataclasses import asdict
from math import exp
from typing import Any

import numpy as np  # type: ignore[import-not-found]
import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild.scalp7_mr_formation_v2 import (
    FORMATION_BARS,
    MAX_HOLD_BARS,
    PAIR,
    TF_MS,
    WEEK_MS,
    FrozenFormation,
    entry_side,
    exit_reason,
    exit_update,
    fit_formation,
    generate_pair_events,
    generate_signals,
    pair_economics,
    week_start,
)

START = 1_767_571_200_000  # 2026-01-05 UTC Monday
TRADE_START = START + WEEK_MS


def frames(extra: int = 20) -> dict[str, pd.DataFrame]:
    size = FORMATION_BARS + extra
    t = np.arange(size)
    x = 7.0 + t * 0.0001
    residual = 0.003 * np.sin(t * 2.0 * np.pi / 20.0)
    y = 3.0 + 1.2 * x + residual
    bars: dict[str, pd.DataFrame] = {}
    for symbol, values in zip(PAIR, [np.exp(y), np.exp(x)]):
        ts = START + t * TF_MS
        bars[symbol] = pd.DataFrame(
            {
                "ts_ms": ts,
                "close": values,
                "segment_id": 0,
                "available_at_ms": ts + TF_MS,
            }
        )
    return bars


def with_excursion() -> tuple[dict[str, pd.DataFrame], FrozenFormation]:
    bars = frames()
    fit = fit_formation(bars, TRADE_START)
    assert fit is not None
    for offset, z in enumerate([3.2, 2.8, 2.4, 1.8, 0.2, -0.2]):
        index = FORMATION_BARS + offset
        eth = float(bars[PAIR[1]].iloc[index]["close"])
        btc = exp(
            fit.intercept
            + fit.beta * np.log(eth)
            + fit.residual_mean
            + z * fit.residual_sd
        )
        bars[PAIR[0]].loc[index, "close"] = btc
    return bars, fit


def test_week_fit_is_frozen_separate_from_trading() -> None:
    bars = frames()
    fit = fit_formation(bars, TRADE_START)
    assert fit is not None
    assert week_start(START) == START
    assert fit.formation_end_ms == fit.trading_start_ms == TRADE_START
    assert fit.formation_start_ms == START
    assert fit.trading_end_ms == TRADE_START + WEEK_MS
    assert fit.beta > 0 and 0 < fit.residual_phi < 1
    assert sum(fit.weights.values()) == pytest.approx(1.0)
    assert fit.weights[PAIR[1]] / fit.weights[PAIR[0]] == pytest.approx(fit.beta)


def test_future_prices_do_not_change_fit_or_training_hash() -> None:
    bars = frames()
    before = fit_formation(bars, TRADE_START)
    for frame in bars.values():
        frame.loc[frame["ts_ms"] >= TRADE_START, "close"] *= 20.0
    after = fit_formation(bars, TRADE_START)
    assert before == after


@pytest.mark.parametrize("defect", ["missing", "segment", "late", "nan"])
def test_formation_rejects_missing_delayed_or_disconnected_data(defect: str) -> None:
    bars = frames()
    if defect == "missing":
        bars[PAIR[0]] = bars[PAIR[0]].drop(index=100)
    elif defect == "segment":
        bars[PAIR[0]].loc[100:, "segment_id"] = 1
    elif defect == "late":
        bars[PAIR[1]].loc[100, "available_at_ms"] = TRADE_START + 1
    else:
        bars[PAIR[0]].loc[100, "close"] = np.nan
    assert fit_formation(bars, TRADE_START) is None


def test_formation_rejects_inverted_or_degenerate_hedge() -> None:
    bars = frames()
    bars[PAIR[0]]["close"] = 1.0 / bars[PAIR[1]]["close"]
    assert fit_formation(bars, TRADE_START) is None
    bars[PAIR[1]]["close"] = 100.0
    assert fit_formation(bars, TRADE_START) is None


def test_only_stretched_same_sign_contraction_can_enter() -> None:
    assert entry_side(3.0, 2.5) == -1
    assert entry_side(-3.0, -2.5) == 1
    assert entry_side(2.1, 2.2) == 0
    assert entry_side(2.1, 1.9) == 0
    assert entry_side(3.0, -2.5) == 0
    assert entry_side(float("nan"), 2.5) == 0


def test_prefix_invariance_and_no_price_fill_in_signal() -> None:
    bars, _ = with_excursion()
    full = generate_signals(bars)
    assert len(full) >= 1
    first = full[0]
    assert first["signal_open_ts_ms"] == TRADE_START + TF_MS
    assert first["signal_ts_ms"] == first["signal_open_ts_ms"] + TF_MS
    assert (
        first["lane"] == "cross_sectional_mean_reversion"
        and first["timeframe_min"] == 30
    )
    assert [leg["side"] for leg in first["legs"]] == [-1, 1]
    assert sum(leg["weight"] for leg in first["legs"]) == pytest.approx(1.0)
    assert "entry_price" not in first and "exit_price" not in first
    prefix = {
        symbol: frame.loc[frame["ts_ms"] <= first["signal_open_ts_ms"]].copy()
        for symbol, frame in bars.items()
    }
    assert generate_signals(prefix) == [first]
    bars[PAIR[0]].loc[bars[PAIR[0]]["ts_ms"] > first["signal_open_ts_ms"], "close"] *= 5
    assert generate_signals(bars)[0] == first


def test_single_position_and_one_signal_per_same_sign_excursion() -> None:
    bars, _ = with_excursion()
    events = generate_pair_events(bars)
    actions = [event["action"] for event in events]
    assert actions[:2] == ["ENTER", "EXIT"]
    assert events[1]["reason"] == "FROZEN_MEAN_REACHED"
    assert events[1]["position_id"] == events[0]["position_id"]
    assert len([e for e in events if e["action"] == "ENTER"]) == 1


def test_gap_during_position_is_unresolved_without_fake_exit_fill() -> None:
    bars, _ = with_excursion()
    for symbol in PAIR:
        bars[symbol] = bars[symbol].drop(index=FORMATION_BARS + 2)
    events = generate_pair_events(bars)
    assert [e["action"] for e in events] == ["ENTER", "UNRESOLVED_GAP"]
    assert "execute_ts_ms" not in events[-1]
    assert "exit_price" not in events[-1]


def test_lifecycle_has_no_same_entry_close_exit() -> None:
    _, fit = with_excursion()
    assert exit_reason(2.8, 3.1, 0, TRADE_START + TF_MS, fit) is None
    assert (
        exit_reason(2.8, 3.1, 1, TRADE_START + 2 * TF_MS, fit)
        == "FROZEN_SPREAD_REEXPANSION"
    )
    assert (
        exit_reason(2.8, -0.1, 1, TRADE_START + 2 * TF_MS, fit) == "FROZEN_MEAN_REACHED"
    )
    assert (
        exit_reason(2.8, 1.9, MAX_HOLD_BARS, TRADE_START + 10 * TF_MS, fit)
        == "TIME_8BAR"
    )
    assert exit_reason(2.8, 1.9, 1, fit.trading_end_ms, fit) == "FORMATION_WINDOW_END"


def test_both_leg_costs_and_frozen_gross_notional() -> None:
    result = pair_economics(
        {PAIR[0]: 100.0, PAIR[1]: 50.0},
        {PAIR[0]: 102.0, PAIR[1]: 49.0},
        {PAIR[0]: 1, PAIR[1]: -1},
        {PAIR[0]: 0.25, PAIR[1]: 0.75},
        {PAIR[0]: 10.0, PAIR[1]: 30.0},
    )
    assert result["gross_bps"] == pytest.approx(200.0)
    assert result["cost_bps"] == pytest.approx(25.0)
    assert result["net_bps"] == pytest.approx(175.0)
    assert result["stress2x_net_bps"] == pytest.approx(150.0)
    with pytest.raises(KeyError):
        pair_economics(
            {PAIR[0]: 100.0, PAIR[1]: 50.0},
            {PAIR[0]: 102.0, PAIR[1]: 49.0},
            {PAIR[0]: 1, PAIR[1]: -1},
            {PAIR[0]: 0.25, PAIR[1]: 0.75},
            {PAIR[0]: 10.0},
        )


def test_exit_adapter_never_refits_on_later_history() -> None:
    bars, fit = with_excursion()
    signal = generate_signals(bars)[0]
    position: dict[str, Any] = {"signal": signal, "hold_bars": 4}
    index = FORMATION_BARS + 5
    bar = {symbol: bars[symbol].iloc[index].to_dict() for symbol in PAIR}
    first = exit_update(position, bar, {})
    for frame in bars.values():
        frame["close"] *= 10
    second = exit_update(position, bar, bars)
    assert first == second
    assert first["exit_next_open"] is True
    assert signal["meta"]["formation"] == asdict(fit)


@pytest.mark.parametrize("defect", ["duplicate", "unsorted", "grid", "early"])
def test_structurally_invalid_bar_contract_fails(defect: str) -> None:
    bars = frames()
    if defect == "duplicate":
        bars[PAIR[0]].loc[1, "ts_ms"] = START
    elif defect == "unsorted":
        bars[PAIR[0]] = bars[PAIR[0]].iloc[::-1]
    elif defect == "grid":
        bars[PAIR[0]]["ts_ms"] += 1
    else:
        bars[PAIR[0]].loc[0, "available_at_ms"] = START
    with pytest.raises(ValueError):
        fit_formation(bars, TRADE_START)


def test_canonical_time_columns_and_availability_are_enforced() -> None:
    bars, fit = with_excursion()
    for symbol in PAIR:
        bars[symbol] = bars[symbol].rename(
            columns={"ts_ms": "open_ts_ms", "available_at_ms": "available_ts_ms"}
        )
        bars[symbol]["close_ts_ms"] = bars[symbol]["open_ts_ms"] + TF_MS
    assert fit_formation(bars, TRADE_START) == fit
    assert len(generate_signals(bars)) == 1
    bars[PAIR[0]].loc[10, "available_ts_ms"] = TRADE_START + 1
    assert fit_formation(bars, TRADE_START) is None
    bars[PAIR[0]].loc[10, "close_ts_ms"] -= 1
    with pytest.raises(ValueError, match="EXCLUSIVE"):
        fit_formation(bars, TRADE_START)


def test_missing_explicit_availability_is_not_guessed() -> None:
    bars = frames()
    bars[PAIR[0]] = bars[PAIR[0]].drop(columns="available_at_ms")
    with pytest.raises(ValueError, match="AVAILABILITY_UNBOUND"):
        generate_signals(bars)


def control_frames() -> dict[str, pd.DataFrame]:
    from backend.research.rebuild.scalp7_mr_formation_v2 import PARENT_SYMBOLS

    t = np.arange(50)
    out: dict[str, pd.DataFrame] = {}
    for symbol in PARENT_SYMBOLS:
        values = np.full(50, 100.0)
        if symbol == "BTC-USDT":
            values[19:31] = [
                104.0,
                103.5,
                103.2,
                103.1,
                104.0,
                104.1,
                104.0,
                103.8,
                103.6,
                103.4,
                103.2,
                103.1,
            ]
        ts = START + t * TF_MS
        out[symbol] = pd.DataFrame(
            {
                "ts_ms": ts,
                "close": values,
                "segment_id": 0,
                "available_at_ms": ts + TF_MS,
            }
        )
    return out


def test_parent_and_bar4_child_keep_independent_occupancy_and_weights() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import (
        PARENT_IDENTITY,
        REEXPANSION_IDENTITY,
    )

    bars = control_frames()
    parent = generate_signals(bars, PARENT_IDENTITY)
    child = generate_signals(bars, REEXPANSION_IDENTITY)
    assert (
        parent[0]["signal_open_ts_ms"]
        == child[0]["signal_open_ts_ms"]
        == START + 20 * TF_MS
    )
    assert child[1]["signal_open_ts_ms"] == START + 25 * TF_MS
    assert all(row["signal_open_ts_ms"] != START + 25 * TF_MS for row in parent)
    assert parent[0]["legs"] == [
        {"symbol": "ETH-USDT", "side": 1, "weight": 0.5},
        {"symbol": "BTC-USDT", "side": -1, "weight": 0.5},
    ]
    assert parent[0]["meta"]["signal_spread6h"] == pytest.approx(0.035)
    prefix = {symbol: frame.iloc[:21] for symbol, frame in bars.items()}
    assert generate_signals(prefix, PARENT_IDENTITY) == parent[:1]
    assert generate_signals(prefix, REEXPANSION_IDENTITY) == child[:1]


def test_parent_fixed_hold_and_pr1335_bar4_thesis_rule_are_separate() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import (
        PARENT_IDENTITY,
        REEXPANSION_IDENTITY,
    )

    bars = control_frames()
    parent = generate_signals(bars, PARENT_IDENTITY)[0]
    child = generate_signals(bars, REEXPANSION_IDENTITY)[0]
    current = {symbol: frame.iloc[24].to_dict() for symbol, frame in bars.items()}
    history = {symbol: frame.iloc[:25] for symbol, frame in bars.items()}
    assert (
        exit_update({"signal": parent, "hold_bars": 4}, current, history)[
            "exit_next_open"
        ]
        is False
    )
    assert (
        exit_update({"signal": child, "hold_bars": 3}, current, history)[
            "exit_next_open"
        ]
        is False
    )
    result = exit_update({"signal": child, "hold_bars": 4}, current, history)
    assert result["exit_next_open"] is True
    assert result["reason"] == "THESIS_REEXPAND_FAIL_BAR4"
    assert (
        exit_update({"signal": parent, "hold_bars": 8}, current, history)["reason"]
        == "TIME_8BAR"
    )


def test_observed_late_controls_emit_actual_decision_time() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import PARENT_IDENTITY

    bars = control_frames()
    historical = generate_signals(bars, PARENT_IDENTITY)[0]
    for frame in bars.values():
        frame["available_at_ms"] += 1000
    actual = generate_signals(bars, PARENT_IDENTITY)[0]
    assert actual["signal_open_ts_ms"] == historical["signal_open_ts_ms"]
    assert actual["signal_ts_ms"] == historical["signal_ts_ms"] + 1000
    prefix = {symbol: frame.iloc[:21] for symbol, frame in bars.items()}
    assert generate_signals(prefix, PARENT_IDENTITY) == [actual]


def test_late_observed_formation_freezes_after_training_is_available() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import IDENTITY

    bars, historical_fit = with_excursion()
    for frame in bars.values():
        frame["available_at_ms"] += 1000
    assert fit_formation(bars, TRADE_START) is None
    actual_fit = fit_formation(bars, TRADE_START, TRADE_START + 1000)
    assert actual_fit is not None
    assert actual_fit.beta == historical_fit.beta
    assert actual_fit.fitted_available_ts_ms == TRADE_START + 1000
    actual = generate_signals(bars, IDENTITY)[0]
    assert actual["signal_open_ts_ms"] == TRADE_START + TF_MS
    assert actual["signal_ts_ms"] == TRADE_START + 2 * TF_MS + 1000
    assert (
        actual["meta"]["formation"]["fitted_available_ts_ms"] <= actual["signal_ts_ms"]
    )
