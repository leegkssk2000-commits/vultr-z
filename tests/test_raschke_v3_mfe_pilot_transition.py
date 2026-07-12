from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_mfe_pilot_transition.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_mfe_pilot_transition_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def event(
    index: int,
    *,
    window: str,
    side: str,
    feature: float,
    mfe: float,
    net_r: float,
    second_feature: float | None = None,
):
    stamp = 1_700_000_000_000 + index * 3_600_000
    return {
        "event_id": f"{window}|{side}|{index}",
        "window": window,
        "side": side,
        "symbol": "BTCUSDT",
        "signal_ts": stamp,
        "signal_utc": str(stamp),
        "label": "TP_FIRST" if mfe >= 2.0 else ("SL_FIRST" if net_r < -0.2 else "TIMEOUT"),
        "mfe_R": mfe,
        "mae_R": 0.3,
        "minutes_to_mfe": 45 if mfe >= 1.0 else 180,
        "duration_min": 240,
        "net_R_0.15": net_r,
        "features": {
            "ema_distance_atr": feature,
            "ema_slope_atr": feature if second_feature is None else second_feature,
            "adx": 20.0 + feature,
        },
    }


def attribution() -> dict:
    rows = [
        {"feature": feature, "drift_score": 0.05, "stable_candidate": True}
        for feature in MODULE.NUMERIC_FEATURES
    ]
    return {
        "numeric_feature_attribution": {
            "all": rows,
            "long": rows,
            "short": rows,
        }
    }


def balanced_events() -> list[dict]:
    rows: list[dict] = []
    index = 0
    for window in MODULE.WINDOWS:
        for side in MODULE.SIDES:
            for position in range(24):
                positive = position < 12
                feature = 2.0 + position * 0.01 if positive else -2.0 - position * 0.01
                mfe = 1.6 if positive else 0.3
                net_r = 0.4 if positive else -0.3
                rows.append(
                    event(
                        index,
                        window=window,
                        side=side,
                        feature=feature,
                        mfe=mfe,
                        net_r=net_r,
                    )
                )
                index += 1
    return rows


def test_rank_auc_perfect_order() -> None:
    labels = [1, 1, 0, 0]
    scores = [4.0, 3.0, 2.0, 1.0]
    assert MODULE.rank_auc(labels, scores) == 1.0


def test_feature_screen_detects_cross_window_direction() -> None:
    rows = balanced_events()
    report = MODULE.screen_features(
        rows,
        attribution(),
        threshold_r=1.5,
        side="long",
    )
    candidate = next(row for row in report if row["feature"] == "ema_distance_atr")
    assert candidate["sign_consistent"] is True
    assert candidate["stable_candidate"] is True
    assert candidate["direction"] == "higher_values_favor_target"


def test_nonredundant_selection_rejects_correlated_feature() -> None:
    rows = balanced_events()
    reports = [
        {"feature": "ema_distance_atr", "stable_candidate": True},
        {"feature": "ema_slope_atr", "stable_candidate": True},
        {"feature": "adx", "stable_candidate": True},
    ]
    selection = MODULE.select_nonredundant_features(reports, rows, maximum=2)
    assert selection["selected"][0] == "ema_distance_atr"
    assert any(row["feature"] == "ema_slope_atr" for row in selection["rejected_redundant"])


def test_ridge_logistic_learns_separation() -> None:
    matrix = np.asarray(
        [
            [1.0, -2.0],
            [1.0, -1.0],
            [1.0, 1.0],
            [1.0, 2.0],
        ]
    )
    labels = np.asarray([0.0, 0.0, 1.0, 1.0])
    beta = MODULE.fit_ridge_logistic(matrix, labels, l2=1.0)
    probabilities = MODULE.sigmoid(matrix @ beta)
    assert probabilities[0] < probabilities[-1]
    assert beta[1] > 0


def test_transport_fit_is_evaluable_and_economic() -> None:
    rows = balanced_events()
    report = MODULE.transport_fit(
        rows,
        side="long",
        features=["ema_distance_atr"],
        threshold_r=1.0,
        train_window=MODULE.WINDOWS[0],
        test_window=MODULE.WINDOWS[1],
    )
    assert report["evaluable"] is True
    assert report["predictive"]["auc"] > 0.9
    assert report["economics"]["top_half"]["avg_net_R"] > report["economics"]["all"]["avg_net_R"]
    assert report["promotion_allowed"] is False


def test_transition_scope_measures_giveback() -> None:
    rows = [
        event(1, window=MODULE.WINDOWS[0], side="long", feature=1.0, mfe=2.1, net_r=1.8),
        event(2, window=MODULE.WINDOWS[0], side="long", feature=1.0, mfe=1.6, net_r=-0.2),
        event(3, window=MODULE.WINDOWS[0], side="long", feature=0.0, mfe=0.4, net_r=-0.4),
    ]
    report = MODULE.transition_scope(rows)
    assert report["threshold_counts"]["1.0"] == 2
    assert report["threshold_counts"]["2.0"] == 1
    assert report["conditional_probability"]["p_2.0_given_1.5"] == 0.5
    assert report["giveback"]["finished_nonpositive_after_1R"] == 1


def test_build_decision_never_promotes() -> None:
    feature_screen = {
        "screen_1.5R": {
            "all": [{"stable_candidate": True}],
            "long": [],
            "short": [],
        }
    }
    pilots = {
        "results": {
            "long": {"stable_transport": True},
            "short": {"stable_transport": False},
        }
    }
    transition = {
        "scopes": {
            "all": {
                "conditional_probability": {"p_2.0_given_1.5": 0.4},
                "giveback": {"finished_nonpositive_after_1R_pct": 30.0},
            }
        }
    }
    decision = MODULE.build_decision(
        feature_screen,
        pilots,
        transition,
        {"top_cp_overlaps_worst_month": True},
        {
            "preferred_intermediate_label": "MFE_GE_1.5R",
            "side_separated_pilot_labels": ["MFE_GE_0.5R", "MFE_GE_1.0R"],
        },
    )
    assert decision["stable_transport_sides"] == ["long"]
    assert decision["hard_rules"]["model_or_strategy_promotion_now"] is False
    assert "CONTINUATION_FAILURE_ANALYSIS_1.5R_TO_2R" in decision["next_modules"]
