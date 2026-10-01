"""Synthetic HG lifecycle and existing-engine integration; no historical data."""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_hg_closure_v1 as m


def bars(candles, start=0):
    return pd.DataFrame(
        [
            dict(
                open_ts_ms=start + i * m.TF,
                close_ts_ms=start + (i + 1) * m.TF,
                available_ts_ms=start + (i + 1) * m.TF,
                segment_id="a",
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
                volume=100.0,
            )
            for i, (o, h, low, c) in enumerate(candles)
        ]
    )


def source_bars():
    candles = [(100, 100.2, 99.8, 100)] * 35
    candles += [(100 + i + 0.2, 101 + i + 0.2, 100 + i, 101 + i) for i in range(12)]
    return bars(candles + [(112, 112.2, 103, 108)])


def evaluated(frame=None):
    return m.evaluate(
        m.MODEL_ID,
        {"X": source_bars() if frame is None else frame},
        {"tick_size": 0.01},
    )


def order():
    out = evaluated()
    return m.create_order(out["plans"][0], 10000, "synthetic-hg", out["rule_digest"])


def minute(opened, o=110, h=111, low=109, c=110):
    return dict(
        symbol="X",
        open_ts_ms=opened,
        close_ts_ms=opened + m.MINUTE,
        available_ts_ms=opened + m.MINUTE,
        segment_id="a",
        open=o,
        high=h,
        low=low,
        close=c,
    )


def test_raw_qualification_first_touch_conditional_plan_and_fixed_classification():
    out = evaluated()
    assert len(out["plans"]) == 1
    plan = out["plans"][0]
    assert plan["order_kind"] == "STOP_MARKET"
    assert plan["trigger_price"] == pytest.approx(112.21)
    assert plan["protective_stop"] == pytest.approx(102.99)
    assert plan["order_active_ts_ms"] == plan["feature_available_ts_ms"] + m.MINUTE
    assert plan["expires_ts_ms"] - plan["order_active_ts_ms"] == m.TF
    assert [r["origin"] for r in out["rules"]] == [
        "SOURCE_DIRECT",
        "EXISTING_FROZEN",
        "DECLARED_HYPOTHESIS",
        "EXISTING_FROZEN",
    ]
    assert {
        r.get("source_mode") for r in out["rules"] if r["origin"] == "SOURCE_DIRECT"
    } == {"HG_1997_CONDITIONAL"}
    assert (
        not out["exact_source_reproduction"] and not out["economic_execution_performed"]
    )
    assert "be_arm_r" not in plan["signal"] and "partial_fraction" not in plan["signal"]
    assert out["events"][0]["available_ts_ms"] < plan["feature_available_ts_ms"]


def test_prefix_invariance_and_future_mutation():
    x = source_bars()
    expected = evaluated(x)
    for n in range(1, len(x) + 1):
        cutoff = int(x.iloc[n - 1].available_ts_ms)
        assert evaluated(x.iloc[:n])["plans"] == [
            p for p in expected["plans"] if p["feature_available_ts_ms"] <= cutoff
        ]
    changed = pd.concat(
        [x, bars([(108, 500, 1, 400)], start=len(x) * m.TF)], ignore_index=True
    )
    assert evaluated(changed)["plans"] == expected["plans"]


@pytest.mark.parametrize(
    "change",
    [
        {"mode_id": "HG_2004_MOMENTUM_CASE"},
        {"qualification_expiry_bars": 10},
        {"be_arm_r": 1},
    ],
)
def test_profile_cannot_be_retuned(change):
    with pytest.raises(ValueError, match="CANNOT_BE_RETUNED"):
        m.evaluate(m.MODEL_ID, {"X": source_bars()}, {"tick_size": 0.01, **change})


@pytest.mark.parametrize("tick", [None, True, 0, -1, float("nan")])
def test_price_grid_required_not_a_trade_tick_receipt(tick):
    with pytest.raises(ValueError, match="POSITIVE_NUMBER"):
        m.profile(tick_size=tick)


def test_real_gap_and_noncanonical_clock_cannot_inherit_qualification():
    x = source_bars()
    x.loc[len(x) - 1, "segment_id"] = "b"
    assert evaluated(x)["plans"] == []
    x = source_bars()
    x["close_ts_ms"] -= 1
    with pytest.raises(ValueError, match="EXCLUSIVE_CANONICAL"):
        evaluated(x)


def feature_fixture(monkeypatch, adx, touches=()):
    x = bars([(112, 114, 111, 113)] * len(adx))
    for i in touches:
        x.loc[i, "low"] = 99

    def measures(rows):
        return [
            {**r, "ema": 100 + i * 0.01, "adx14": adx[i]} for i, r in enumerate(rows)
        ]

    monkeypatch.setattr(m.source, "_measures", measures)
    return x


def test_same_bar_touch_not_retroactive_and_requalification_requires_later_bar(
    monkeypatch,
):
    x = feature_fixture(monkeypatch, [29, 31, 29, 24, 31, 28], touches=(1, 2, 5))
    out = evaluated(x)
    kinds = [e["kind"] for e in out["events"]]
    assert kinds == [
        "INITIAL_ADX_QUALIFICATION",
        "FIRST_POST_QUALIFICATION_EMA_TOUCH",
        "REQUALIFICATION_RESET",
        "INITIAL_ADX_QUALIFICATION",
        "FIRST_POST_QUALIFICATION_EMA_TOUCH",
    ]
    assert [p["feature_available_ts_ms"] for p in out["plans"]] == [3 * m.TF, 6 * m.TF]
    assert out["events"][2]["available_ts_ms"] < out["events"][3]["available_ts_ms"]


def test_qualification_expiry_20_later_bars_then_no_retry(monkeypatch):
    x = feature_fixture(monkeypatch, [29] + [31] * 22, touches=(22,))
    out = evaluated(x)
    assert not out["plans"]
    assert out["events"][-1]["kind"] == "QUALIFICATION_EXPIRED_HYPOTHESIS"


def test_gap_through_ema_is_not_claimed_as_observed_touch(monkeypatch):
    x = feature_fixture(monkeypatch, [29, 31, 29])
    x.loc[2, ["open", "high", "low", "close"]] = [99, 99.5, 98, 99]
    out = evaluated(x)
    assert out["plans"] == []
    assert out["events"][-1]["kind"] == "HG_GAP_THROUGH_EMA_NO_OBSERVED_TOUCH_NO_ORDER"


def test_preentry_swing_invalidation_cancels_without_fill():
    o = order()
    adapter = m.create_adapter(o, fee_rate=0.001)
    event = adapter.process_detail_bar(minute(o["order_active_ts_ms"], low=102))
    assert event["status"] == "HG_PREENTRY_SWING_INVALIDATED"
    assert adapter.state == "CANCELLED" and not adapter.ledger
    adapter.process_detail_bar(
        minute(o["order_active_ts_ms"] + m.MINUTE, o=113, h=114, low=113, c=114)
    )
    assert not adapter.ledger


def test_simultaneous_trigger_and_stop_stays_unknown():
    o = order()
    adapter = m.create_adapter(o, fee_rate=0.001)
    event = adapter.process_detail_bar(minute(o["order_active_ts_ms"], h=114, low=102))
    assert event["status"] == "UNRESOLVED_ENTRY_STOP_ORDER"
    assert adapter.state == "UNRESOLVED" and not adapter.ledger


def test_untriggered_order_expires_once_no_retry():
    o = order()
    adapter = m.create_adapter(o, fee_rate=0.001)
    for ts in range(o["order_active_ts_ms"], o["expires_ts_ms"] + m.MINUTE, m.MINUTE):
        adapter.process_detail_bar(minute(ts))
    assert adapter.finish()["state"] == "EXPIRED"
    assert not adapter.ledger


def lifecycle_fixture():
    x = source_bars()
    more = [
        (112.3, 114, 112.3, 113),
        (113, 114, 112, 113),
        (113, 114, 111.5, 113.5),
        (113.5, 115, 112.2, 114.2),
        (114.2, 114.3, 111, 112),
    ]
    x = pd.concat([x, bars(more, start=len(x) * m.TF)], ignore_index=True)
    active = 48 * m.TF + m.MINUTE
    details = []
    for r in x.iloc[48:].to_dict("records"):
        for ts in range(r["open_ts_ms"], r["close_ts_ms"], m.MINUTE):
            if ts >= active:
                details.append(
                    minute(
                        ts,
                        o=r["open"] if ts in (active, r["open_ts_ms"]) else r["close"],
                        h=r["high"],
                        low=r["low"],
                        c=r["close"],
                    )
                )
    return x, pd.DataFrame(details)


def test_raw_to_caller_to_existing_engine_management_and_exit():
    x, detail = lifecycle_fixture()
    result = m.run_synthetic_fixture(
        {"X": x}, {"X": detail}, {"tick_size": 0.01}, dataset_kind="SYNTHETIC_FIXTURE"
    )
    assert len(result["executions"]) == 1
    execution = result["executions"][0]
    assert execution["state"] == "CLOSED"
    assert [r["effect"] for r in execution["ledger"]] == ["OPEN", "CLOSE"]
    assert float(execution["ledger"][1]["fill_price"]) == pytest.approx(111.49)
    assert execution["ledger"][1]["ts_ms"] >= 52 * m.TF
    assert any(e["status"] == "DECISION_UPDATE_SCHEDULED" for e in execution["events"])
    assert result["new_full_runs"] == 0 and not result["economic_execution_performed"]
    assert all(
        r["execution_evidence"] == "MODEL_NOT_OBSERVED" for r in execution["ledger"]
    )


def test_gap_after_entry_retains_unknown_ownership_without_synthetic_close():
    x, detail = lifecycle_fixture()
    detail = detail.drop(index=3).reset_index(drop=True)
    result = m.run_synthetic_fixture(
        {"X": x}, {"X": detail}, {"tick_size": 0.01}, dataset_kind="SYNTHETIC_FIXTURE"
    )
    execution = result["executions"][0]
    assert execution["state"] == "UNRESOLVED"
    assert [r["effect"] for r in execution["ledger"]] == ["OPEN"]
    assert execution["events"][-1]["status"] == "DETAIL_GAP_NO_SYNTHETIC_FILL"


def test_adapter_rejects_foreign_model_and_rule_binding():
    o = order()
    o["model_id"] = "foreign"
    with pytest.raises(ValueError, match="BINDING"):
        m.create_adapter(o, fee_rate=0.001)
    out = evaluated()
    with pytest.raises(ValueError, match="RULE_DIGEST"):
        m.create_order(out["plans"][0], 10000, "fixture", "wrong")
    changed = copy.deepcopy(out["plans"][0])
    changed["quantity_policy"]["risk_fraction"] = 1
    with pytest.raises(ValueError, match="QUANTITY_POLICY"):
        m.create_order(changed, 10000, "fixture", out["rule_digest"])


def test_fixture_path_requires_explicit_declaration():
    with pytest.raises(ValueError, match="SYNTHETIC_FIXTURE"):
        m.run_synthetic_fixture(
            {"X": source_bars()},
            {"X": pd.DataFrame()},
            {"tick_size": 0.01},
            dataset_kind="GENUINE_HISTORY",
        )


def test_short_conditional_reference_and_preentry_invalidation_are_symmetric():
    x = source_bars()
    before = x.copy()
    for key in ("open", "close"):
        x[key] = 400 - before[key]
    x["high"], x["low"] = 400 - before["low"], 400 - before["high"]
    out = evaluated(x)
    assert len(out["plans"]) == 1
    p = out["plans"][0]
    assert p["side"] == -1 and p["trigger_price"] == pytest.approx(287.79)
    assert p["protective_stop"] == pytest.approx(297.01)
    adapter = m.create_adapter(
        m.create_order(p, 10000, "short-fixture", out["rule_digest"]), fee_rate=0.001
    )
    adapter.process_detail_bar(
        minute(p["order_active_ts_ms"], o=291, h=298, low=290, c=292)
    )
    assert adapter.state == "CANCELLED" and adapter.ledger == []


def test_requalified_plan_is_blocked_by_prior_unresolved_ownership(monkeypatch):
    x = feature_fixture(monkeypatch, [29, 31, 29, 24, 31, 28], touches=(2, 5))
    active = 3 * m.TF + m.MINUTE
    details = pd.DataFrame(
        [
            minute(active, o=115, h=116, low=114, c=115),
            minute(active + 2 * m.MINUTE, o=115, h=116, low=114, c=115),
            minute(6 * m.TF + m.MINUTE, o=115, h=116, low=114, c=115),
        ]
    )
    out = m.run_synthetic_fixture(
        {"X": x}, {"X": details}, {"tick_size": 0.01}, dataset_kind="SYNTHETIC_FIXTURE"
    )
    assert len(out["plans"]) == 2 and len(out["executions"]) == 1
    assert out["executions"][0]["state"] == "UNRESOLVED"
    assert out["dispositions"][0]["status"] == "PRIOR_OWNERSHIP_RETAINED_NO_NEW_ORDER"


@pytest.mark.parametrize("management_only", [False, True])
def test_delayed_source_or_management_feature_clock_is_explicitly_unsupported(
    management_only,
):
    x, details = lifecycle_fixture()
    selected = x.index >= 49 if management_only else x.index >= 0
    x.loc[selected, "available_ts_ms"] += 2 * m.MINUTE
    with pytest.raises(ValueError, match="HG_BAR_CLOSE_FEATURE_CLOCK_REQUIRED"):
        m.compile_model(m.MODEL_ID, {"X": x}, {"tick_size": 0.01})
    with pytest.raises(ValueError, match="HG_BAR_CLOSE_FEATURE_CLOCK_REQUIRED"):
        m.run_synthetic_fixture(
            {"X": x},
            {"X": details},
            {"tick_size": 0.01},
            dataset_kind="SYNTHETIC_FIXTURE",
        )


def test_delayed_detail_delivery_cannot_silently_skip_management_callbacks():
    x, details = lifecycle_fixture()
    details["available_ts_ms"] += 2 * m.MINUTE
    with pytest.raises(ValueError, match="HG_BAR_CLOSE_DETAIL_CLOCK_REQUIRED"):
        m.run_synthetic_fixture(
            {"X": x},
            {"X": details},
            {"tick_size": 0.01},
            dataset_kind="SYNTHETIC_FIXTURE",
        )
