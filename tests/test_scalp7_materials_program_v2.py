from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_materials_program_v2 as m


def candles(count: int = 180, seed: int = 9) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.35, count))
    opening = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open_ts_ms": np.arange(count, dtype=np.int64) * m.TF_MS,
            "close_ts_ms": (np.arange(count, dtype=np.int64) + 1) * m.TF_MS,
            "available_ts_ms": (np.arange(count, dtype=np.int64) + 1) * m.TF_MS,
            "open": opening,
            "high": np.maximum(opening, close) + 0.15,
            "low": np.minimum(opening, close) - 0.15,
            "close": close,
            "segment_id": ["part1"] * count,
        }
    )


def pos(identity: str) -> dict[str, Any]:
    return {
        "signal": {
            "identity": identity,
            "invalidation_price": 100.0,
            "meta": {"entry_atr": 1.0},
        },
        "side": 1,
        "hold_bars": 2,
        "mfe_R": 0.5,
        "stop_price": 97.0,
        "entry_price": 100.0,
        "initial_risk": 3.0,
        "entry_ts_ms": 0,
    }


def test_identity_rejects_legacy_and_unknown() -> None:
    for value in ("turtle_trend_1h", "turtle_trend_30m_round2_v2"):
        with pytest.raises(ValueError, match="UNKNOWN"):
            m.generate_signals({"BTC-USDT": candles()}, value)


def test_prefix_invariance_and_closed_availability() -> None:
    frame = candles(900)
    all_events = m.generate_signals({"BTC-USDT": frame})
    prefix = m.generate_signals({"BTC-USDT": frame.iloc[:600]})
    cutoff = 600 * m.TF_MS
    assert prefix == [e for e in all_events if e["signal_ts_ms"] <= cutoff]
    assert all(
        e["signal_ts_ms"] >= e["signal_open_ts_ms"] + m.TF_MS for e in all_events
    )
    assert all(e["timeframe_min"] == 30 for e in all_events)
    assert all(e["lane"].startswith("MATERIAL:") for e in all_events)
    assert all(e["meta"]["order"] == "BLOCKED" for e in all_events)


def test_future_price_changes_cannot_change_past() -> None:
    frame = candles(500)
    before = m.generate_signals({"BTC-USDT": frame.iloc[:300]})
    frame.loc[300:, ["open", "high", "low", "close"]] *= 10
    after = m.generate_signals({"BTC-USDT": frame})
    assert before == [e for e in after if e["signal_open_ts_ms"] < 300 * m.TF_MS]


def test_physical_gap_resets_features_and_setup_state() -> None:
    frame = candles(330)
    frame.loc[165:, ["open_ts_ms", "close_ts_ms", "available_ts_ms"]] += m.TF_MS
    events = m.generate_signals({"BTC-USDT": frame})
    gap = int(frame.iloc[165].open_ts_ms)
    assert not [
        e for e in events if gap <= e["signal_open_ts_ms"] < gap + 101 * m.TF_MS
    ]


def test_segment_change_without_gap_also_resets() -> None:
    frame = candles(300)
    frame.loc[150:, "segment_id"] = "part2"
    events = m.generate_signals({"BTC-USDT": frame})
    assert not [
        e for e in events if 150 * m.TF_MS <= e["signal_open_ts_ms"] < 251 * m.TF_MS
    ]


@pytest.mark.parametrize("mutation", ["duplicate", "unaligned", "nan", "bad_ohlc"])
def test_integrity_failfast(mutation: str) -> None:
    frame = candles()
    if mutation == "duplicate":
        frame.loc[1, "open_ts_ms"] = 0
    elif mutation == "unaligned":
        frame.loc[1, "open_ts_ms"] += 1
    elif mutation == "nan":
        frame.loc[1, "close"] = np.nan
    else:
        frame.loc[1, "high"] = 1.0
    with pytest.raises(ValueError, match="MATERIAL_"):
        m.generate_signals({"BTC-USDT": frame})


def test_volume_changes_irrelevant_to_price_only_controls() -> None:
    frame = candles(500)
    first = m.generate_signals({"BTC-USDT": frame})
    frame["volume"] = -100
    assert first == m.generate_signals({"BTC-USDT": frame})


@pytest.mark.parametrize(
    "material", ["rbreaker_like", "rsi_swing_fail", "turtle_trend"]
)
def test_exit_only_child_preserves_all_entry_geometry(material: str) -> None:
    frame = candles(1000)
    parent = m.generate_signals({"BTC-USDT": frame}, f"{material}_30m_control_v2")
    child = m.generate_signals({"BTC-USDT": frame}, f"{material}_30m_round1_v2")
    assert parent
    keys = (
        "signal_ts_ms",
        "side",
        "stop_price",
        "invalidation_price",
        "take_profit_r",
        "max_hold_bars",
    )
    assert [[e[k] for k in keys] for e in parent] == [
        [e[k] for k in keys] for e in child
    ]


def test_rbreaker_child_requests_next_open_only() -> None:
    parent = pos("rbreaker_like_30m_control_v2")
    child = pos("rbreaker_like_30m_round1_v2")
    bar = {"close": 99.0}
    assert not m.exit_update(parent, bar, pd.DataFrame())["exit_next_open"]
    decision = m.exit_update(child, bar, pd.DataFrame())
    assert decision["exit_next_open"] is True
    assert decision["reason"] == "RANGE_THESIS_INVALIDATED"
    assert decision["next_stop"] is None


def test_trail_is_prospective_and_never_widens() -> None:
    p = pos("trend_ma_macd_30m_control_v2")
    p["mfe_R"] = 1.1
    out = m.exit_update(p, {"close": 105.0}, pd.DataFrame())
    assert out["next_stop"] == pytest.approx(103.2)
    p["stop_price"] = 104.0
    assert m.exit_update(p, {"close": 105.0}, pd.DataFrame())["next_stop"] is None


def test_turtle_child_removes_only_atr_trail() -> None:
    p = pos("turtle_trend_30m_control_v2")
    p["mfe_R"] = 2.0
    assert m.exit_update(p, {"close": 106.0}, pd.DataFrame())["next_stop"] == 104.0
    p["signal"]["identity"] = "turtle_trend_30m_round1_v2"
    assert m.exit_update(p, {"close": 106.0}, candles().iloc[:0])["next_stop"] is None


def test_future_history_tail_rejected() -> None:
    p = pos("rsi_swing_fail_30m_round1_v2")
    with pytest.raises(ValueError, match="CLOSED_PREFIX"):
        m.exit_update(p, {"close": 100, "open_ts_ms": 0}, candles())


def test_cosine_alignment_and_unknown_zero() -> None:
    assert m.behavior_cosine({"BTC:1": 1}, {"BTC:1": 1}) == pytest.approx(1)
    assert m.behavior_cosine({"BTC:1": 1}, {"ETH:1": 1}) == 0
    assert m.behavior_cosine({}, {}) is None
    with pytest.raises(ValueError, match="NONFINITE"):
        m.behavior_cosine({"a": float("nan")}, {"a": 1})


def economics() -> dict[str, Any]:
    return {
        "T": 40,
        "Net": 100.0,
        "PF": 1.5,
        "DD": 20.0,
        "loss_tail": 5.0,
        "source_integrity": True,
        "cost_bound": True,
        "evidence_kind": "GENUINE_FRESH_FROZEN",
        "rule_sha256": "f" * 64,
        "receipt_sha256": "e" * 64,
        "start_ts_ms": 200,
        "comparison_id": "identical-cost-opportunity",
    }


def test_b_requires_fresh_preregistered_sample_and_marginal_risk() -> None:
    parent = dict(economics(), Net=80, DD=21, loss_tail=6)
    child, fresh = economics(), economics()
    assert not m.assess_b_grade(parent, child, fresh, {})["B_eligible"]
    contract = {
        "minimum_trades": 30,
        "minimum_fresh_trades": 30,
        "source_sha256": "c" * 64,
        "rule_sha256": "f" * 64,
        "frozen_at_ms": 100,
    }
    assert m.assess_b_grade(parent, child, fresh, contract)["B_eligible"]
    fresh["evidence_kind"] = "HISTORICAL_ROLLING"
    assert not m.assess_b_grade(parent, child, fresh, contract)["B_eligible"]
    fresh = economics()
    child["DD"] = 22
    assert not m.assess_b_grade(parent, child, fresh, contract)["B_eligible"]


@pytest.mark.parametrize(
    "metric,value", [("Net", 0), ("PF", 1), ("T", 0), ("loss_tail", None)]
)
def test_b_rejects_missing_or_negative_evidence(metric: str, value: Any) -> None:
    child = economics()
    child[metric] = value
    assert not m.assess_b_grade(
        dict(economics(), Net=80),
        child,
        economics(),
        {"minimum_trades": 30, "source_sha256": "a" * 64},
    )["B_eligible"]


def test_fusion_no_cxc_no_duplicate_or_unknown_cosine() -> None:
    left = {"grade": "B", "B_eligible": True, "fresh_verified": True, "identity": "a"}
    right = {"grade": "B", "B_eligible": True, "fresh_verified": True, "identity": "b"}
    assert m.fusion_eligible(left, right, 0.84)
    assert not m.fusion_eligible(left, right, 0.85)
    assert not m.fusion_eligible(left, right, None)
    assert not m.fusion_eligible(left, left, 0.2)
    assert not m.fusion_eligible(dict(left, grade="C"), right, 0.2)


def test_late_dependency_delays_signal_availability() -> None:
    frame = candles(500)
    delayed = 1000 * m.TF_MS
    frame["available_ts_ms"] = frame.open_ts_ms + m.TF_MS
    frame.loc[80, "available_ts_ms"] = delayed
    events = m.generate_signals({"BTC-USDT": frame})
    assert events
    assert all(e["signal_ts_ms"] >= delayed for e in events)


def test_prepared_prefix_matches_uncached_exit_features() -> None:
    frame = candles()
    prepared = m.prepare_frames({"BTC-USDT": frame})["BTC-USDT"]
    bar = frame.iloc[-1].to_dict()
    p = pos("rsi_swing_fail_30m_round1_v2")
    assert m.exit_update(p, bar, frame) == m.exit_update(p, bar, prepared)


def test_grade_rejects_stale_or_different_frozen_identity() -> None:
    contract = {
        "minimum_trades": 30,
        "minimum_fresh_trades": 30,
        "source_sha256": "c" * 64,
        "rule_sha256": "f" * 64,
        "frozen_at_ms": 100,
    }
    parent = dict(economics(), Net=80, DD=21, loss_tail=6)
    fresh = dict(economics(), rule_sha256="d" * 64)
    assert not m.assess_b_grade(parent, economics(), fresh, contract)["B_eligible"]
    fresh = dict(economics(), start_ts_ms=99)
    assert not m.assess_b_grade(parent, economics(), fresh, contract)["B_eligible"]


def test_comparison_domain_and_receipt_required() -> None:
    contract = {
        "minimum_trades": 30,
        "minimum_fresh_trades": 30,
        "source_sha256": "c" * 64,
        "rule_sha256": "f" * 64,
        "frozen_at_ms": 100,
    }
    parent = dict(economics(), Net=80, DD=21, loss_tail=6)
    child = dict(economics(), comparison_id="othercost")
    assert not m.assess_b_grade(parent, child, economics(), contract)["B_eligible"]
    child = dict(economics(), receipt_sha256="fake")
    assert not m.assess_b_grade(parent, child, economics(), contract)["B_eligible"]


def test_noncanonical_availability_and_missing_segment_rejected() -> None:
    frame = candles()
    frame.loc[20, "available_ts_ms"] -= 1
    with pytest.raises(ValueError, match="AVAILABILITY"):
        m.generate_signals({"BTC-USDT": frame})
    with pytest.raises(ValueError, match="SCHEMA"):
        m.generate_signals({"BTC-USDT": candles().drop(columns="segment_id")})


def test_cosine_outside_mathematical_domain_rejected() -> None:
    left = {"grade": "B", "B_eligible": True, "fresh_verified": True, "identity": "a"}
    right = dict(left, identity="b")
    assert not m.fusion_eligible(left, right, -999)


def test_fractional_timestamp_not_silently_truncated() -> None:
    for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame = candles()
        frame[column] = frame[column].astype(float)
        frame.loc[20, column] += 0.5
        with pytest.raises(ValueError, match="TIMESTAMP_INTEGER"):
            m.generate_signals({"BTC-USDT": frame})
