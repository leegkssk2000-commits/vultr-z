"""Independent hand-ledger comparisons plus synthetic actual-runner seams."""

from copy import deepcopy

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_exact25_model_comparison_v1 as compare
from backend.research.rebuild import scalp7_exact25_model_runner_v1 as runner

AXIS = "SUPERTREND_TRAILING_ONLY"
WINDOW = {
    "name": "validation",
    "kind": "VALIDATION",
    "start_ts_ms": 0,
    "end_ts_ms": 1000,
}


def binding(model, *, baseline="parent"):
    return {
        "identity_key": model + "-identity",
        "binding_sha256": model + "-seal",
        "model_id": model,
        "baseline_id": baseline,
        "strategy_id": "synthetic_matched_fixture",
        "data_manifest": {"data_kind": "SYNTHETIC_FIXTURE"},
        "cost": {
            "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
            "per_side_rates": {"X": 0.001},
        },
        "windows": [deepcopy(WINDOW)],
        "initial_cash_usdt": 1000,
        "capital_policy": "same",
        "gap_policy": "same",
        "price_basis": "LAST_PRICE",
        "execution_mode": "DETAIL_CONDITIONAL",
        "config": {},
        "model_module": "same_module",
        "compiler": "compile_model",
        "code_closure": {"same_module.py": "sealed"},
        "environment": {"python": "same"},
    }


def episode(ep, net, stamp=100, *, outcome=200, closed=True):
    return {
        "episode_id": ep,
        "entry_ts_ms": stamp,
        "closed": closed,
        "outcome_available_ts_ms": outcome,
        "net_reference_usdt": net,
    }


def order(ep, clock=10, *, reference=110, day=900, side=1):
    return {
        "order": {
            "position_episode_id": ep,
            "symbol": "X",
            "side": side,
            "setup_ts_ms": clock,
            "session_end_ms": day,
            "reference_edge": reference,
        }
    }


def window(rows, complete=True, dd=10):
    nets = [
        r["net_reference_usdt"]
        for r in rows
        if r["closed"]
        and r["entry_ts_ms"] < 1000
        and r["outcome_available_ts_ms"] < 1000
    ]
    gains = sum(n for n in nets if n > 0)
    loss = -sum(n for n in nets if n < 0)
    return {
        **WINDOW,
        "complete_window": complete,
        "T_resolved": len(nets),
        "WR_resolved_pct": 100 * sum(n > 0 for n in nets) / len(nets) if nets else None,
        "gross_resolved_usdt": sum(nets) + len(nets),
        "net_resolved_reference_usdt": sum(nets),
        "net_per_trade_resolved_reference_usdt": (
            sum(nets) / len(nets) if nets else None
        ),
        "PF_resolved_reference": gains / loss if loss else None,
        "DD_pct": dd,
        "MaxLS_resolved": 1 if loss else 0,
    }


def result(bind, one, two, orders):
    return {
        "identity_key": bind["identity_key"],
        "binding_sha256": bind["binding_sha256"],
        "execution": {"executions": orders},
        "cost_scenarios": {
            "1x": {"episodes": one, "windows": [window(one)]},
            "2x": {"episodes": two, "windows": [window(two)]},
        },
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }


def pair():
    pb, cb = binding("parent"), binding("child")
    p = result(
        pb,
        [episode("p1", 10), episode("p2", 5), episode("p3", 2)],
        [episode("p1", 9), episode("p2", 3), episode("p3", 1)],
        [order("p1", 10), order("p2", 20), order("p3", 30)],
    )
    c = result(
        cb,
        [episode("c1", 2), episode("c2", -3)],
        [episode("c1", 1), episode("c2", -5)],
        [order("c1", 10), order("c2", 20)],
    )
    return p, c, pb, cb


def call(values=None, axis=AXIS):
    return compare.compare_matched(*(pair() if values is None else values), axis=axis)


def test_hand_calculated_winner_damage_cost1x_and2x():
    out = call()
    base = out["cost_scenarios"]["1x"][0]["winner_damage"]
    stress = out["cost_scenarios"]["2x"][0]["winner_damage"]
    assert base["parent_winners"] == 3
    assert base["child_positive_same_setup"] == 1
    assert base["child_negative_same_setup"] == 1
    assert base["child_absent_same_setup"] == 1
    assert base["child_zero_same_setup"] == 0
    assert base["parent_winner_net_usdt"] == 17
    assert base["child_net_on_parent_winning_setups_usdt"] == -1
    assert base["winner_net_delta_usdt"] == -18
    assert base["positive_winner_profit_retention_pct"] == pytest.approx(200 / 17)
    assert stress["parent_winner_net_usdt"] == 13
    assert stress["winner_net_delta_usdt"] == -17
    assert stress["positive_winner_profit_retention_pct"] == pytest.approx(100 / 13)
    assert out["formal_promotion"] == "BLOCKED"
    assert out["funding_status"] == "UNKNOWN_NOT_ZERO"
    assert out["actual_historical_net"] is None


@pytest.mark.parametrize(
    "key",
    [
        "data_manifest",
        "cost",
        "windows",
        "initial_cash_usdt",
        "capital_policy",
        "gap_policy",
        "price_basis",
        "execution_mode",
        "config",
        "model_module",
        "compiler",
        "code_closure",
        "environment",
    ],
)
def test_every_frozen_common_condition_difference_rejected(key):
    values = pair()
    values[3][key] = {"mutated": True}
    with pytest.raises(ValueError, match="MATCHED_CONDITION_DIFFERS:" + key):
        call(values)


@pytest.mark.parametrize(
    "field,expected",
    [("strategy_id", "MATCHED_STRATEGY"), ("baseline_id", "ACTUAL_CONTROL")],
)
def test_child_must_be_actual_same_strategy_control(field, expected):
    values = pair()
    values[3][field] = "wrong"
    with pytest.raises(ValueError, match=expected):
        call(values)


@pytest.mark.parametrize(
    "field,expected",
    [("identity_key", "RESULT_IDENTITY"), ("binding_sha256", "RESULT_FREEZE")],
)
def test_result_must_bind_exact_frozen_identity(field, expected):
    values = pair()
    values[1][field] = "wrong"
    with pytest.raises(ValueError, match=expected):
        call(values)


@pytest.mark.parametrize("which", [0, 1])
def test_unknown_window_withholds_winner_damage_and_joint_claim(which):
    values = pair()
    for scenario in ("1x", "2x"):
        values[which]["cost_scenarios"][scenario]["windows"][0][
            "complete_window"
        ] = False
    out = call(values)
    for rows in out["cost_scenarios"].values():
        assert rows[0]["winner_damage"] is None
        assert rows[0]["strict_T_WR_Net_up_DD_down"] is None
        assert rows[0]["incomplete_resolved_subset_is_not_total_performance"] is True
    assert out["formal_promotion"] == "BLOCKED"


def test_setup_clock_matching_does_not_match_later_unrelated_entry():
    values = pair()
    values[1]["execution"]["executions"][0]["order"]["setup_ts_ms"] += 1
    damage = call(values)["cost_scenarios"]["1x"][0]["winner_damage"]
    assert damage["child_absent_same_setup"] == 2


def test_sr_matching_uses_same_prior_reference_not_entry_clock():
    pb, cb = binding("parent"), binding("child")
    p = result(pb, [episode("p", 10)], [episode("p", 9)], [order("p", 10)])
    c = result(cb, [episode("c", 4, 120)], [episode("c", 3, 120)], [order("c", 25)])
    out = call((p, c, pb, cb), "SR_BREAKOUT_VS_LATER_RETEST")
    damage = out["cost_scenarios"]["1x"][0]["winner_damage"]
    assert damage["child_positive_same_setup"] == 1
    assert damage["not_an_identical_entry_claim"] is True
    c["execution"]["executions"][0]["order"]["reference_edge"] = 111
    damage = call((p, c, pb, cb), "SR_BREAKOUT_VS_LATER_RETEST")["cost_scenarios"][
        "1x"
    ][0]["winner_damage"]
    assert damage["child_absent_same_setup"] == 1


@pytest.mark.parametrize("which", [0, 1])
def test_duplicate_closed_setup_is_rejected(which):
    values = pair()
    values[which]["execution"]["executions"][1]["order"]["setup_ts_ms"] = 10
    with pytest.raises(ValueError, match="AMBIGUOUS_SAME_SETUP"):
        call(values)


def test_duplicate_execution_episode_is_not_silently_overwritten():
    values = pair()
    values[0]["execution"]["executions"].append(
        deepcopy(values[0]["execution"]["executions"][0])
    )
    with pytest.raises(ValueError, match="DUPLICATE_EXECUTION_EPISODE"):
        call(values)


def test_duplicate_result_window_is_not_silently_overwritten():
    values = pair()
    rows = values[0]["cost_scenarios"]["1x"]["windows"]
    rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError, match="DUPLICATE_WINDOW_RESULT"):
        call(values)


def test_both_results_cannot_change_frozen_window_boundary():
    values = pair()
    for result in values[:2]:
        result["cost_scenarios"]["1x"]["windows"][0]["end_ts_ms"] = 999
    with pytest.raises(ValueError, match="WINDOW_BOUNDARY_MISMATCH"):
        call(values)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_episode_winner_net_cannot_generate_retention(value):
    values = pair()
    values[0]["cost_scenarios"]["1x"]["episodes"][0]["net_reference_usdt"] = value
    with pytest.raises(ValueError, match="NONFINITE"):
        call(values)


def test_missing_order_binding_rejected_instead_of_unmatched_winner():
    values = pair()
    values[0]["execution"]["executions"] = []
    with pytest.raises(ValueError, match="EPISODE_SETUP_ORDER_MISSING"):
        call(values)


def test_zero_child_net_is_not_absent_or_converted_loss():
    values = pair()
    values[1]["cost_scenarios"]["1x"]["episodes"][1]["net_reference_usdt"] = 0
    damage = call(values)["cost_scenarios"]["1x"][0]["winner_damage"]
    assert damage["child_zero_same_setup"] == 1
    assert damage["child_negative_same_setup"] == 0
    assert damage["child_absent_same_setup"] == 1


def test_no_parent_winner_retention_is_unknown_not_zero_percent():
    values = pair()
    for r in values[0]["cost_scenarios"]["1x"]["episodes"]:
        r["net_reference_usdt"] = -1
    damage = call(values)["cost_scenarios"]["1x"][0]["winner_damage"]
    assert damage["parent_winners"] == 0
    assert damage["positive_winner_profit_retention_pct"] is None


def test_joint_claim_requires_strict_four_way_improvement_and_known_dd():
    values = pair()
    p = values[0]["cost_scenarios"]["1x"]["windows"][0]
    c = values[1]["cost_scenarios"]["1x"]["windows"][0]
    for k in ("T_resolved", "WR_resolved_pct", "net_resolved_reference_usdt"):
        c[k] = p[k] + 1
    c["DD_pct"] = p["DD_pct"] - 1
    assert call(values)["cost_scenarios"]["1x"][0]["strict_T_WR_Net_up_DD_down"] is True
    c["T_resolved"] = p["T_resolved"]
    assert (
        call(values)["cost_scenarios"]["1x"][0]["strict_T_WR_Net_up_DD_down"] is False
    )
    c["DD_pct"] = None
    assert call(values)["cost_scenarios"]["1x"][0]["strict_T_WR_Net_up_DD_down"] is None


def test_actual_supertrend_runner_retains_setup_and_episode_for_comparison():
    from backend.research.rebuild import scalp7_exact25_indicator_models_v1 as model
    from test_scalp7_exact25_model_runner_v1 import raw_inputs

    bindings, results = [], []
    for mid in (model.CONTROL, model.TRAIL):
        b = runner.freeze_model(
            model_module=model.__name__,
            model_id=mid,
            strategy_id="supertrend_pullback",
            baseline_id=model.CONTROL,
            changed_axis=AXIS,
            config=model.CONFIG,
            data_manifest={
                "data_kind": "SYNTHETIC_FIXTURE",
                "construction_reason": "reuse audited synthetic flip/pullback fixture",
            },
            cost={
                "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
                "per_side_rates": {"X": 0.0001},
                "funding_status": "UNKNOWN_NOT_ZERO",
            },
            windows=[
                {
                    "name": "validation",
                    "kind": "VALIDATION",
                    "start_ts_ms": 0,
                    "end_ts_ms": 430 * 60000,
                }
            ],
            initial_cash_usdt=10000,
        )
        r = runner.run_fixture(
            b, raw_inputs(), expected_binding_sha256=b["binding_sha256"]
        )
        assert all(
            {"position_episode_id", "setup_ts_ms"} <= set(e["order"])
            for e in r["execution"]["executions"]
        )
        bindings.append(b)
        results.append(r)
    out = compare.compare_matched(*results, *bindings, axis=AXIS)
    assert out["cost_scenarios"]["1x"][0]["complete_pair_window"] is True
    assert out["cost_scenarios"]["1x"][0]["metrics"]["T_resolved"]["delta"] == 0


def test_actual_sr_runner_retains_fixed_day_reference_matching_fields():
    from backend.research.rebuild import scalp7_exact25_reference_models_v1 as model
    from test_scalp7_exact25_reference_models_v1 import sr_frame, SYMBOL

    minute = 60000
    day = model.DAY
    rows = []
    for bar in sr_frame().tail(3).to_dict("records"):
        for i in range(30):
            stamp = bar["open_ts_ms"] + i * minute
            opened = bar["open"]
            close = bar["close"] if i == 29 else opened
            high = bar["high"] if i == 1 else max(opened, close)
            low = bar["low"] if i == 2 else min(opened, close)
            rows.append(
                {
                    "open_ts_ms": stamp,
                    "close_ts_ms": stamp + minute,
                    "available_ts_ms": stamp + minute,
                    "segment_id": "fixture",
                    "open": opened,
                    "high": high,
                    "low": low,
                    "close": close,
                }
            )
    stamp = day + 90 * minute
    rows.append(
        {
            "open_ts_ms": stamp,
            "close_ts_ms": stamp + minute,
            "available_ts_ms": stamp + minute,
            "segment_id": "fixture",
            "open": 108,
            "high": 108,
            "low": 108,
            "close": 108,
        }
    )
    last = rows[-1]["close_ts_ms"]
    inputs = {
        "frames": {SYMBOL: sr_frame()},
        "detail_frames": {SYMBOL: pd.DataFrame(rows)},
        "price_snapshots": [
            {"ts_ms": day, "prices": {}},
            {
                "ts_ms": last,
                "prices": {
                    SYMBOL: {
                        "ts_ms": last,
                        "price": 108,
                        "price_basis": "LAST_PRICE",
                        "source_ref": "synthetic",
                    }
                },
            },
        ],
    }
    bindings, results = [], []
    for mid in (model.SR_CONTROL, model.SR):
        b = runner.freeze_model(
            model_module=model.__name__,
            model_id=mid,
            strategy_id="sr_levels",
            baseline_id=model.SR_CONTROL,
            changed_axis="SR_BREAKOUT_VS_LATER_RETEST",
            config={},
            data_manifest={
                "data_kind": "SYNTHETIC_FIXTURE",
                "construction_reason": "synthetic prior-day box reference",
            },
            cost={
                "kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING",
                "per_side_rates": {SYMBOL: 0.0001},
                "funding_status": "UNKNOWN_NOT_ZERO",
            },
            windows=[
                {
                    "name": "validation",
                    "kind": "VALIDATION",
                    "start_ts_ms": day,
                    "end_ts_ms": day + 100 * minute,
                }
            ],
            initial_cash_usdt=10000,
        )
        r = runner.run_fixture(b, inputs, expected_binding_sha256=b["binding_sha256"])
        assert len(r["execution"]["executions"]) == 1
        assert {"position_episode_id", "session_end_ms", "reference_edge"} <= set(
            r["execution"]["executions"][0]["order"]
        )
        bindings.append(b)
        results.append(r)
    out = compare.compare_matched(
        *results, *bindings, axis="SR_BREAKOUT_VS_LATER_RETEST"
    )
    assert out["cost_scenarios"]["1x"][0]["complete_pair_window"] is True
    assert (
        out["cost_scenarios"]["1x"][0]["winner_damage"]["not_an_identical_entry_claim"]
        is True
    )
