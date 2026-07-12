from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_competing_risk_bocpd.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_competing_risk_bocpd_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def event(index: int, label: str, duration: int, net_r: float, mfe: float, *, window: str = "prior_holdout_90d", side: str = "long", symbol: str = "BTCUSDT"):
    return {
        "event_id": f"E{index}",
        "signal_ts": 1_700_000_000_000 + index * 60_000,
        "signal_utc": f"event-{index}",
        "window": window,
        "side": side,
        "symbol": symbol,
        "label": label,
        "duration_min": duration,
        "net_R_0.15": net_r,
        "mfe_R": mfe,
        "mae_R": 0.4,
        "minutes_to_mfe": max(1, duration // 2),
    }


def test_aalen_johansen_final_incidence_sums_to_one() -> None:
    rows = [
        event(0, "TP_FIRST", 10, 1.8, 2.1),
        event(1, "SL_FIRST", 20, -0.6, 0.2),
        event(2, "TIMEOUT", 480, 0.1, 0.8),
        event(3, "SL_FIRST", 30, -0.6, 0.4),
    ]
    report = MODULE.aalen_johansen(rows)
    total = sum(report["final_cif"].values()) + report["survival_after_last_event"]
    assert abs(total - 1.0) < 1e-9
    assert round(report["final_cif"]["TP"], 6) == 0.25
    assert round(report["final_cif"]["SL"], 6) == 0.50
    assert round(report["final_cif"]["TIMEOUT"], 6) == 0.25


def test_aalen_johansen_checkpoint_excludes_later_events() -> None:
    rows = [
        event(0, "TP_FIRST", 10, 1.8, 2.1),
        event(1, "SL_FIRST", 20, -0.6, 0.2),
        event(2, "TIMEOUT", 480, 0.1, 0.8),
    ]
    report = MODULE.aalen_johansen(rows)
    assert report["checkpoint_cif"]["15"]["TP"] > 0
    assert report["checkpoint_cif"]["15"]["SL"] == 0
    assert report["checkpoint_cif"]["240"]["TIMEOUT"] == 0


def test_threshold_report_cross_window_and_side_readiness() -> None:
    rows = []
    index = 0
    for window in MODULE.WINDOWS:
        for side in MODULE.SIDES:
            for _ in range(10):
                rows.append(event(index, "TIMEOUT", 480, 0.1, 1.2, window=window, side=side))
                index += 1
            for _ in range(10):
                rows.append(event(index, "SL_FIRST", 30, -0.6, 0.2, window=window, side=side))
                index += 1
    report = MODULE.threshold_report(rows, 1.0)
    assert report["positive"] == 40
    assert report["readiness"]["cross_window_univariate"] is True
    assert report["readiness"]["side_separated_pilot"] is True


def test_giveback_detects_reached_then_nonpositive() -> None:
    rows = [
        event(0, "TIMEOUT", 480, -0.1, 1.2),
        event(1, "SL_FIRST", 90, -0.6, 1.1),
        event(2, "TP_FIRST", 100, 1.8, 2.1),
        event(3, "TIMEOUT", 480, 0.4, 1.3),
    ]
    report = MODULE.giveback_report(rows)
    one_r = next(row for row in report["thresholds"] if row["threshold_R"] == 1.0)
    assert one_r["reached_events"] == 4
    assert one_r["finished_nonpositive_events"] == 2
    assert one_r["timeout_nonpositive_events"] == 1
    assert one_r["sl_after_reach_events"] == 1


def test_beta_bernoulli_bocpd_returns_probabilities() -> None:
    observations = [0] * 30 + [1] * 30
    probabilities = MODULE.beta_bernoulli_bocpd(observations, hazard=1.0 / 20.0)
    assert len(probabilities) == len(observations)
    assert all(0.0 <= value <= 1.0 for value in probabilities)
    assert max(probabilities[25:40]) > 0.0


def test_gaussian_bocpd_returns_probabilities() -> None:
    observations = [-0.5] * 25 + [0.5] * 25
    probabilities = MODULE.gaussian_mean_bocpd(observations, hazard=1.0 / 20.0)
    assert len(probabilities) == len(observations)
    assert all(0.0 <= value <= 1.0 for value in probabilities)


def test_choose_diagnostic_path_uses_highest_ready_threshold() -> None:
    thresholds = [
        {"threshold_R": 0.5, "readiness": {"cross_window_univariate": True, "side_separated_pilot": True}},
        {"threshold_R": 1.0, "readiness": {"cross_window_univariate": True, "side_separated_pilot": False}},
        {"threshold_R": 1.5, "readiness": {"cross_window_univariate": False, "side_separated_pilot": False}},
    ]
    competing = {
        "subgroups": {
            "all": {
                "cumulative_incidence": {
                    "final_cif": {"TP": 0.10, "SL": 0.45, "TIMEOUT": 0.45}
                }
            }
        }
    }
    giveback = {
        "thresholds": [
            {"threshold_R": 1.0, "finished_nonpositive_pct": 30.0}
        ]
    }
    decision = MODULE.choose_diagnostic_path(thresholds, competing, giveback)
    assert decision["preferred_intermediate_label"] == "MFE_GE_1.0R"
    assert "MFE_GE_0.5R" in decision["side_separated_pilot_labels"]
    assert "CONDITIONAL_PROFIT_REALIZATION_DIAGNOSTIC" in decision["next_modules"]
    assert decision["tp2r_binary_model_allowed"] is False
