"""Artificial native-engine counterexamples only; no historical economics."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from ops import scalp7_squeeze_signal_low_successor_v1 as successor


TF = 1_800_000


def test_frozen_parent_engine_and_saved_overlay_sources_unchanged():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (
            root
            / "research/campaigns/scalp7_20261013/dual_streak_v1/SQUEEZE_NATIVE_PREPARATION_V1.json"
        ).read_text()
    )
    for path, expected in contract["source_pins_sha256"].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected
    assert contract["new_native_candidate_comparisons"] == 0
    assert contract["economic_dispatch_enabled_by_this_patch"] is False


def frame():
    rows = [
        dict(
            open_ts_ms=i * TF,
            close_ts_ms=(i + 1) * TF,
            available_ts_ms=(i + 1) * TF,
            segment_id="A",
            open=103.0,
            high=104.0,
            low=101.0,
            close=103.0,
        )
        for i in range(8)
    ]
    rows[0]["low"] = 100.0
    rows[1].update(low=98.0, close=99.0)
    rows[2].update(open=97.0, high=99.0, low=96.0, close=98.0)
    return pd.DataFrame(rows)


def signal(regime="TREND_DISPERSED"):
    return dict(
        identity=positive.SQUEEZE_PARENT,
        lane="squeeze_break",
        symbol="BTC-USDT",
        timeframe_min=30,
        side=1,
        signal_open_ts_ms=0,
        signal_ts_ms=TF,
        segment_id="A",
        stop_price=90.0,
        max_hold_bars=11,
        take_profit_r=None,
        meta=dict(
            regime=regime,
            be_arm_r=None,
            frozen_cost_bps=14.0,
            fallback_stop_atr_mult=2.0,
            entry_cost_gate=dict(atr_price=2.0, min_ratio=4.0),
        ),
    )


def position(sig):
    return dict(
        signal=sig,
        entry_ts_ms=TF,
        entry_price=103.0,
        initial_risk=13.0,
        stop_price=90.0,
        side=1,
        mfe_R=0.0,
        hold_bars=1,
        remaining=1.0,
    )


def native(sig, bars, callback=successor.native_exit_update):
    records, index = execution._frame_records(bars, 30)
    return execution._single(
        sig, bars, records, index, 14.0, callback, positive.entry_update
    )


def saved_trade(bars, regime="TREND_DISPERSED", exit_ts=6 * TF):
    sig = signal(regime)
    sig["identity"] = successor.SAVED_OVERLAY
    sig["meta"]["lifecycle_adapter_parent_identity"] = positive.SQUEEZE_PARENT
    return dict(
        symbol="BTC-USDT",
        regime=regime,
        signal=sig,
        entry_ts_ms=TF,
        entry_prices={"BTC-USDT": float(bars.iloc[1].open)},
        exit_ts_ms=exit_ts,
    )


def test_low_frozen_at_signal_not_later_low_and_inputs_unchanged():
    bars, sig = frame(), signal()
    old = deepcopy(sig)
    bound = successor.bind_signal_low(sig, bars)
    assert bound["meta"][successor.BINDING]["low"] == 100
    assert sig == old
    bars.loc[2:, "low"] = 1.0
    assert bound == successor.bind_signal_low(sig, bars)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "future", "segment", "nonfinite"]
)
def test_unverified_signal_low_fails_closed(change):
    bars = frame()
    if change == "missing":
        bars = bars.iloc[1:]
    elif change == "duplicate":
        bars = pd.concat([bars, bars.iloc[:1]])
    elif change == "future":
        bars.loc[0, "available_ts_ms"] = 2 * TF
    elif change == "segment":
        bars.loc[0, "segment_id"] = "B"
    else:
        bars.loc[0, "low"] = float("nan")
    with pytest.raises(ValueError):
        successor.bind_signal_low(signal(), bars)


def test_fractional_source_clock_is_not_silently_truncated():
    bars = frame()
    bars["available_ts_ms"] = bars["available_ts_ms"].astype(float)
    bars.loc[0, "available_ts_ms"] = TF + 0.5
    with pytest.raises(ValueError, match="NONINTEGER"):
        successor.bind_signal_low(signal(), bars)


def test_panics_signal_and_native_lifecycle_unchanged():
    bars, sig = frame(), signal("PANIC_DISPERSION")
    assert successor.bind_signal_low(sig, bars) == sig
    assert native(sig, bars) == native(sig, bars, positive.exit_update)


def test_actual_native_callback_fills_next_actual_open_not_signal_low():
    bars = frame()
    sig = successor.bind_signal_low(signal(), bars)
    traces = []

    def callback(pos, bar, history):
        return successor.native_exit_update(pos, bar, history, trace=traces)

    trade, unresolved, until, rejection = native(sig, bars, callback)
    assert unresolved is None and rejection is None
    assert trade["exit_ts_ms"] == 2 * TF == until
    assert trade["exit_prices"]["BTC-USDT"] == 97 != 100
    assert trade["reason"] == successor.EXIT_REASON
    assert traces[0]["invalidation_available_ts_ms"] == 2 * TF
    assert traces[0]["invalidation_close"] == 99


def test_current_bar_stop_wins_before_callback():
    bars = frame()
    bars.loc[1, "low"] = 89
    trade, _, _, _ = native(successor.bind_signal_low(signal(), bars), bars)
    assert trade["reason"] == "STOP_FIRST"
    assert trade["exit_prices"]["BTC-USDT"] == 90


def test_original_callback_exit_wins_same_close():
    bars = frame()
    pos = position(successor.bind_signal_low(signal(), bars))
    expected = dict(exit_next_open=True, reason="SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN")
    out = successor.native_exit_update(
        pos,
        bars.to_dict("records")[1],
        bars.iloc[:2],
        parent_callback=lambda *args: expected,
    )
    assert out == expected


def test_original_engine_max_hold_wins_same_close():
    bars = frame()
    sig = signal()
    sig["max_hold_bars"] = 1
    trade, _, _, _ = native(successor.bind_signal_low(sig, bars), bars)
    assert trade["reason"] == "MAX_HOLD_NEXT_OPEN"


def test_no_next_bar_preserves_unresolved_no_fake_fill():
    bars = frame().iloc[:2]
    trade, unresolved, _, rejection = native(
        successor.bind_signal_low(signal(), bars), bars
    )
    assert trade is None and rejection is None
    assert unresolved["state"] == "UNRESOLVED_GAP_OR_END"


def test_gap_after_invalidation_no_synthetic_next_open():
    bars = frame().drop(index=2).reset_index(drop=True)
    trade, unresolved, _, _ = native(successor.bind_signal_low(signal(), bars), bars)
    assert trade is None and unresolved is not None


def test_missing_runtime_binding_not_silently_invented():
    bars = frame()
    with pytest.raises(ValueError, match="BINDING_REQUIRED"):
        successor.native_exit_update(
            position(signal()), bars.to_dict("records")[1], bars.iloc[:2]
        )


def test_scan_uses_saved_rows_only_without_regenerating_or_pnl():
    bars = frame()
    saved = saved_trade(bars)
    before = deepcopy(saved)
    result = successor._scan_rows({"BTC-USDT": bars}, [saved])
    assert saved == before
    assert result["earlier_invalidation_count"] == 1
    assert result["economic_result"] is None
    assert result["new_native_candidate_comparisons"] == 0
    assert result["old_candidate_replayed"] is False


def test_same_original_exit_not_earlier_and_panics_not_scanned():
    bars = frame()
    result = successor._scan_rows(
        {"BTC-USDT": bars},
        [saved_trade(bars, exit_ts=2 * TF), saved_trade(bars, "PANIC_DISPERSION")],
    )
    assert result["saved_trend_trades_scanned"] == 1
    assert result["earlier_invalidation_count"] == 0


def test_scan_stop_first_not_false_new_trigger():
    bars = frame()
    bars.loc[1, "low"] = 89
    result = successor._scan_rows(
        {"BTC-USDT": bars}, [saved_trade(bars, exit_ts=2 * TF)]
    )
    assert result["earlier_invalidation_count"] == 0


def test_scan_inconsistent_earlier_stop_is_integrity_error_not_zero():
    bars = frame()
    bars.loc[1, "low"] = 89
    with pytest.raises(ValueError, match="EARLIER_STOP_CONFLICT"):
        successor._scan_rows({"BTC-USDT": bars}, [saved_trade(bars)])


def test_scan_missing_next_open_is_not_zero_trigger_success():
    bars = frame().iloc[:2]
    with pytest.raises(ValueError, match="NEXT_OPEN_UNVERIFIED"):
        successor._scan_rows({"BTC-USDT": bars}, [saved_trade(bars)])


def test_truncated_nontriggering_path_is_not_structural_zero():
    bars = frame().iloc[:2].copy()
    bars.loc[1, ["low", "close"]] = [101.0, 103.0]
    with pytest.raises(ValueError, match="EXIT_SOURCE_NOT_COVERED"):
        successor._scan_rows({"BTC-USDT": bars}, [saved_trade(bars)])


def test_gap_crossing_original_exit_is_not_structural_zero():
    bars = frame().drop(index=[2, 3, 4]).reset_index(drop=True)
    bars.loc[1, ["low", "close"]] = [101.0, 103.0]
    with pytest.raises(ValueError, match="PATH_SOURCE_GAP"):
        successor._scan_rows({"BTC-USDT": bars}, [saved_trade(bars, exit_ts=4 * TF)])


def test_scanner_rejects_unpinned_receipt_before_reading_any_rows():
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        successor.scan_saved_trend_triggers({}, {"receipt_sha256": "0" * 64})
