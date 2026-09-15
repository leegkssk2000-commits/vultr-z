from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from backend.research.rebuild import scalp7_positive_lanes_v2 as p


def candles(n: int = 130) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for i in range(n):
        close = 100.0 + i
        rows.append(
            {
                "open_ts_ms": i * p.TIMEFRAME_MS,
                "close_ts_ms": (i + 1) * p.TIMEFRAME_MS,
                "available_ts_ms": (i + 1) * p.TIMEFRAME_MS,
                "segment_id": "A",
                "open": close - 0.5,
                "high": close + 0.5,
                "low": close - 1,
                "close": close,
                "regime": "TREND_DISPERSED",
                "regime_available_ts_ms": (i + 1) * p.TIMEFRAME_MS,
                "regime_fit_end_ts_ms": -1,
                "regime_spec_sha256": "a" * 64,
            }
        )
    if n > 121:
        rows[121]["low"] = rows[121]["close"] - 12
    return pd.DataFrame(rows)


def signal(identity: str = p.KELTNER_PARENT, arm: float | None = 1) -> dict[str, Any]:
    return {
        "identity": identity,
        "side": 1,
        "stop_price": 99,
        "meta": {
            "frozen_cost_bps": 14,
            "entry_cost_gate": {"atr_price": 2, "min_ratio": 4.5},
            "fallback_stop_atr_mult": 1.2,
            "be_arm_r": arm,
        },
    }


def position(identity: str = p.KELTNER_PARENT, arm: float | None = 1) -> dict[str, Any]:
    return {
        "signal": signal(identity, arm),
        "entry_ts_ms": 0,
        "entry_price": 100,
        "initial_risk": 1,
        "side": 1,
        "stop_price": 99,
        "mfe_R": 0,
        "hold_bars": 1,
        "remaining": 1.0,
    }


def lifecycle_bars(high: float = 101, low: float = 99.5) -> pd.DataFrame:
    x = candles(3)
    x[["open", "high", "low", "close"]] = [100, high, low, 100.5]
    return x


def test_keltner_utc_parent_and_td_child_frozen_entry_match() -> None:
    x = candles()
    rows = p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14})
    hg = [s for s in rows if s["identity"] in (p.KELTNER_PARENT, p.KELTNER_TD075)]
    assert len(hg) == 2
    parent, child = sorted(hg, key=lambda s: s["identity"])
    assert (
        parent["signal_open_ts_ms"]
        == child["signal_open_ts_ms"]
        == 122 * p.TIMEFRAME_MS
    )
    assert parent["stop_price"] == child["stop_price"]
    assert {s["meta"]["be_arm_r"] for s in hg} == {1.0, 0.75}
    assert all(
        s["partial_take_profit_r"] == 2 and s["partial_fraction"] == 0.1 for s in hg
    )
    assert all(s["max_hold_bars"] == 25 for s in hg)


def test_no_next_open_or_future_outcome_in_signal() -> None:
    x = candles()
    base = p.generate_signals({"BTC-USDT": x.iloc[:123]}, costs={"BTC-USDT": 14})
    x.loc[123:, ["open", "high", "low", "close"]] = [100, 10000, 1, 9999]
    extended = p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14})
    assert [
        r for r in extended if r["signal_open_ts_ms"] <= 122 * p.TIMEFRAME_MS
    ] == base


@pytest.mark.parametrize(
    "column,value",
    [
        ("regime_available_ts_ms", 10**14),
        ("regime_fit_end_ts_ms", 10**14),
        ("regime_spec_sha256", ""),
        ("regime", "RANGE_MIXED"),
    ],
)
def test_unbound_future_or_wrong_regime_has_no_positive_entry(
    column: str, value: Any
) -> None:
    x = candles()
    x[column] = value
    assert p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14}) == []


def test_cost_missing_produces_no_trade_and_open_cost_gate_is_causal() -> None:
    assert p.generate_signals({"BTC-USDT": candles()}) == []
    sig = signal()
    assert p.entry_update(sig, 100)["stop_price"] == 99
    assert p.entry_update(sig, 10000)["reject"] is True


def test_fallback_stop_uses_actual_open_once_admitted() -> None:
    sig = signal()
    sig["stop_price"] = 105
    assert p.entry_update(sig, 100)["stop_price"] == pytest.approx(97.6)


def test_td075_is_unchanged_in_panic() -> None:
    x = candles()
    x["regime"] = "PANIC_DISPERSION"
    rows = p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14})
    assert all(
        s["meta"]["be_arm_r"] == 1 for s in rows if s["identity"] == p.KELTNER_TD075
    )


def test_be_is_next_bar_instruction_never_same_bar_fill() -> None:
    h = lifecycle_bars(high=101, low=99.5)
    pos = position()
    pos["mfe_R"] = 1
    result = p.exit_update(pos, h.iloc[-1].to_dict(), h)
    assert result["next_stop"] == pytest.approx(100.16)
    assert result["exit_next_open"] is False
    assert "exit_price" not in result
    assert pos["stop_price"] == 99


def test_keltner_declared_partial_once_and_runner_ratchet() -> None:
    h = lifecycle_bars(high=103.5, low=100)
    pos = position()
    pos["mfe_R"] = 3.5
    result = p.exit_update(pos, h.iloc[-1].to_dict(), h)
    assert result["partial_fraction"] == 0.1
    assert result["partial_price"] == 102
    assert result["next_stop"] == 102.25
    pos["remaining"] = 0.9
    assert "partial_fraction" not in p.exit_update(pos, h.iloc[-1].to_dict(), h)


def test_hg_source_scratch_frozen_threshold_and_clock() -> None:
    h = lifecycle_bars()
    pos = position()
    pos.update(hold_bars=5, mfe_R=0.39)
    assert p.exit_update(pos, h.iloc[-1].to_dict(), h)["exit_next_open"] is True
    pos["mfe_R"] = 0.4
    assert p.exit_update(pos, h.iloc[-1].to_dict(), h)["exit_next_open"] is False


def test_squeeze_parent_has_no_be_child_has_exact_fee_be() -> None:
    h = lifecycle_bars()
    parent = position(p.SQUEEZE_PARENT, None)
    child = position(p.SQUEEZE_BE1R, 1)
    parent["mfe_R"] = child["mfe_R"] = 1
    assert "next_stop" not in p.exit_update(parent, h.iloc[-1].to_dict(), h)
    assert p.exit_update(child, h.iloc[-1].to_dict(), h)["next_stop"] == pytest.approx(
        100.14
    )


def test_squeeze_momentum_tail_equals_full_causal_indicator() -> None:
    x = candles(130)
    enriched = p.enriched_segments(x)[0]
    assert np.allclose(p._last_momenta(x), enriched.momentum.iloc[-3:].to_numpy())
    for start in (20, 50, 90):
        values = np.arange(20, dtype=float) ** 2 + start
        coeff = np.polyfit(np.arange(20), values, 1)
        assert p._linreg_endpoint(values) == pytest.approx(np.polyval(coeff, 19))


def test_gap_resets_atr_ema_and_signal_warmup() -> None:
    x = candles()
    x.loc[122:, "segment_id"] = "B"
    assert p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14}) == []
    segments = p.enriched_segments(x)
    assert len(segments) == 2
    assert np.isnan(segments[1].iloc[0].atr)


def test_fractional_timestamp_rejected() -> None:
    x = candles()
    x["open_ts_ms"] = x.open_ts_ms.astype(float)
    x.loc[0, "open_ts_ms"] = 0.1
    with pytest.raises(ValueError, match="INTEGER_TIMESTAMPS"):
        p.generate_signals({"BTC-USDT": x}, costs={"BTC-USDT": 14})


def test_common_engine_partial_and_next_bar_fee_stop_accounting() -> None:
    from backend.research.rebuild import scalp7_execution_v2 as engine

    x = candles(3)
    x.loc[0, ["open", "high", "low", "close"]] = [100, 101, 99.5, 100]
    x.loc[1, ["open", "high", "low", "close"]] = [100, 102.5, 99.5, 101.5]
    x.loc[2, ["open", "high", "low", "close"]] = [101.5, 101.6, 100.1, 100.5]
    sig = signal()
    sig.update(
        symbol="BTC-USDT",
        lane="keltner_holygrail",
        timeframe_min=30,
        signal_open_ts_ms=0,
        signal_ts_ms=p.TIMEFRAME_MS,
        segment_id="A",
        max_hold_bars=25,
        partial_take_profit_r=2.0,
        partial_fraction=0.10,
    )
    result = engine.replay(
        [sig],
        {"BTC-USDT": x},
        {"BTC-USDT": 14},
        exit_update=p.exit_update,
        entry_update=p.entry_update,
    )
    assert result["closed_trade_count"] == 1
    trade = result["trades"][0]
    assert trade["gross_bps"] == pytest.approx(34.4)
    assert trade["net_bps"] == pytest.approx(20.4)
    assert trade["exit_prices"]["BTC-USDT"] == pytest.approx(100.16)
    assert trade["entry_ts_ms"] == p.TIMEFRAME_MS
    assert trade["exit_ts_ms"] == 3 * p.TIMEFRAME_MS


def test_common_engine_squeeze_be_does_not_stop_on_witness_bar() -> None:
    from backend.research.rebuild import scalp7_execution_v2 as engine

    x = candles(3)
    x.loc[0, ["open", "high", "low", "close"]] = [100, 101, 99.5, 100]
    x.loc[1, ["open", "high", "low", "close"]] = [100, 101.5, 99.5, 101]
    x.loc[2, ["open", "high", "low", "close"]] = [101, 101.5, 100.1, 100.5]
    sig = signal(p.SQUEEZE_BE1R)
    sig.update(
        symbol="BTC-USDT",
        lane="squeeze_break",
        timeframe_min=30,
        signal_open_ts_ms=0,
        signal_ts_ms=p.TIMEFRAME_MS,
        segment_id="A",
        max_hold_bars=11,
    )
    result = engine.replay(
        [sig],
        {"BTC-USDT": x},
        {"BTC-USDT": 14},
        exit_update=p.exit_update,
        entry_update=p.entry_update,
    )
    assert result["closed_trade_count"] == 1
    trade = result["trades"][0]
    assert trade["exit_ts_ms"] == 3 * p.TIMEFRAME_MS
    assert trade["net_bps"] == pytest.approx(0.0, abs=1e-9)


def test_favorable_gap_fills_frozen_resting_partial_conservatively() -> None:
    h = lifecycle_bars(high=104, low=102.5)
    h[["open", "close"]] = [103, 103.2]
    pos = position()
    pos["mfe_R"] = 4
    result = p.exit_update(pos, h.iloc[-1].to_dict(), h)
    assert result["partial_fraction"] == 0.1
    assert result["partial_price"] == 102
    assert result["partial_price"] < h.iloc[-1]["low"]


def test_fallback_cannot_create_nonpositive_stop() -> None:
    sig = signal()
    sig["stop_price"] = 105
    sig["meta"]["entry_cost_gate"]["atr_price"] = 100
    assert p.entry_admission(sig, 100) == {
        "allowed": False,
        "reason": "INVALID_FINAL_STOP",
    }


def test_short_favorable_gap_partial_uses_declared_limit() -> None:
    h = lifecycle_bars(high=97.5, low=96)
    h[["open", "close"]] = [97, 96.8]
    pos = position()
    pos.update(side=-1, stop_price=101, mfe_R=4)
    pos["signal"]["side"] = -1
    result = p.exit_update(pos, h.iloc[-1].to_dict(), h)
    assert result["partial_price"] == 98
    assert result["partial_fraction"] == 0.1
