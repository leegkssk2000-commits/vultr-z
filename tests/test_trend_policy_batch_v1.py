from __future__ import annotations

import pytest

from backend.research.rebuild.policy_kernel_v1 import (
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    evaluator_adapter_sha,
)
from backend.research.rebuild.trend_policy_batch_v1 import (
    FeatureSnapshot,
    build_supertrend_pullback_intent,
    build_trend_ma_macd_intent,
    build_trend_rider_intent,
    compute_supertrend_pullback_feature,
    compute_trend_ma_macd_feature,
    compute_trend_rider_feature,
)

SRC = "historical-r7-policy-source-sha"
COST = 10.0
NOW = 10_000_000_000


def bars(n: int = 90):
    out = []
    px = 100.0
    for i in range(n):
        drift = 0.20 if i < n - 8 else (-0.10 if i < n - 3 else 0.35)
        o = px
        c = px + drift
        out.append({"ts_ms": NOW - (n - 1 - i) * 3_600_000, "open": o,
                    "high": max(o, c) + 0.30, "low": min(o, c) - 0.30,
                    "close": c, "volume": 1000.0 + i})
        px = c
    return out


def feature(sid: str) -> FeatureSnapshot:
    common = dict(strategy_id=sid, symbol="BTC-USDT", signal_ts=NOW, fresh=True,
                  close=100.0, atr=1.0, feature_sha=f"fixture-{sid}")
    if sid == "supertrend_pullback":
        values = {"long_reclaim": True, "short_reclaim": False, "pullback_depth_atr": 0.8,
                  "chase_atr": 0.5}
    elif sid == "trend_ma_macd":
        values = {"long_cross": True, "short_cross": False, "impulse_atr": 0.08,
                  "chase_atr": 0.4}
    else:
        values = {"long_confirm": True, "short_confirm": False, "st_gap_atr": 0.8,
                  "chase_atr": 0.6}
    return FeatureSnapshot(values=values, **common)


@pytest.mark.parametrize("sid,builder", [
    ("supertrend_pullback", build_supertrend_pullback_intent),
    ("trend_ma_macd", build_trend_ma_macd_intent),
    ("trend_rider", build_trend_rider_intent),
])
def test_planted_edge_positive_control_and_parity(sid, builder):
    intent = builder(feature(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
    assert intent.no_trade is False
    assert intent.side == "long"
    assert intent.cost_budget_ratio >= 1.25
    assert intent.pyramiding == {"enabled": False, "adverse_add": False}
    assert evaluator_adapter_sha(intent) == intent.sha
    recomputed_risk_bps = abs(intent.sl - 100.0) / 100.0 * 10_000.0
    assert recomputed_risk_bps == pytest.approx(intent.risk_size["risk_distance_bps"])

    flipped = control_direction_flip(intent)
    placebo = control_time_placebo(intent, 7 * 3_600_000)
    delayed = control_delayed_entry(intent, 2, 3_600_000)
    assert flipped.side == "short" and flipped.sha != intent.sha
    assert placebo.signal_ts != intent.signal_ts and placebo.sha != intent.sha
    assert delayed.signal_ts != intent.signal_ts and delayed.sha != intent.sha


@pytest.mark.parametrize("sid,builder", [
    ("supertrend_pullback", build_supertrend_pullback_intent),
    ("trend_ma_macd", build_trend_ma_macd_intent),
    ("trend_rider", build_trend_rider_intent),
])
def test_stale_missing_cost_and_strategy_mismatch_fail_closed(sid, builder):
    stale = feature(sid)
    stale = FeatureSnapshot(stale.strategy_id, stale.symbol, stale.signal_ts, False,
                            stale.close, stale.atr, stale.values, stale.feature_sha)
    intent = builder(stale, policy_source_sha=SRC, verified_round_trip_cost_bps=COST)
    assert intent.no_trade is True
    assert "STALE_SOURCE_FAIL_CLOSED" in intent.reason_codes
    with pytest.raises(ValueError, match="VERIFIED_COST_AUTHORITY_REQUIRED"):
        builder(feature(sid), policy_source_sha=SRC, verified_round_trip_cost_bps=0.0)
    wrong = feature("trend_rider" if sid != "trend_rider" else "trend_ma_macd")
    with pytest.raises(ValueError, match="FEATURE_STRATEGY_MISMATCH"):
        builder(wrong, policy_source_sha=SRC, verified_round_trip_cost_bps=COST)


def test_feature_ssot_closed_bar_determinism_and_duplicate_guard():
    xs = bars()
    fns = [compute_supertrend_pullback_feature, compute_trend_ma_macd_feature, compute_trend_rider_feature]
    for fn in fns:
        a = fn(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        b = fn(xs, symbol="BTC-USDT", now_ts_ms=NOW)
        assert a.feature_sha == b.feature_sha
        assert a.signal_ts == xs[-1]["ts_ms"]
    dup = list(xs)
    dup[-1] = dict(dup[-1], ts_ms=dup[-2]["ts_ms"])
    for fn in fns:
        with pytest.raises(ValueError, match="BAR_TS_NON_MONOTONIC_OR_DUPLICATE"):
            fn(dup, symbol="BTC-USDT", now_ts_ms=NOW)


def test_source_method_fidelity_fields_exist():
    xs = bars()
    a = compute_supertrend_pullback_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
    b = compute_trend_ma_macd_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
    c = compute_trend_rider_feature(xs, symbol="BTC-USDT", now_ts_ms=NOW)
    assert {"supertrend", "direction", "ema50", "long_reclaim", "short_reclaim"} <= set(a.values)
    assert {"ema_fast", "ema_slow", "hist", "hist_prev", "long_cross", "short_cross"} <= set(b.values)
    assert {"supertrend", "direction", "ema50", "long_confirm", "short_confirm"} <= set(c.values)
