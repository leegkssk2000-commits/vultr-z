from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_multitarget_roadmap.py"
    spec = importlib.util.spec_from_file_location("raschke_v3_multitarget_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def event(index: int, *, mfe: float, label: str, window: str, side: str):
    return {
        "event_id": str(index),
        "mfe_R": mfe,
        "mae_R": 0.4,
        "label": label,
        "window": window,
        "side": side,
        "symbol": "BTCUSDT",
        "net_R_0.15": 1.0 if label == "TP_FIRST" else -0.5,
    }


def test_wilson_interval_contains_observed_probability() -> None:
    lower, upper = MODULE.wilson_interval(11, 155)
    observed = 11 / 155
    assert 0 < lower < observed < upper < 1


def test_expected_total_for_positive_target() -> None:
    prevalence = 11 / 155
    assert MODULE.expected_total_for_positive_target(30, prevalence) == 423
    assert MODULE.expected_total_for_positive_target(0, prevalence) == 0
    assert MODULE.expected_total_for_positive_target(30, 0.0) is None


def test_binary_report_separates_windows_and_sides() -> None:
    events = []
    index = 0
    for window in MODULE.WINDOWS:
        for side in MODULE.SIDES:
            for _ in range(12):
                events.append(event(index, mfe=1.2, label="TIMEOUT", window=window, side=side))
                index += 1
            for _ in range(12):
                events.append(event(index, mfe=0.2, label="SL_FIRST", window=window, side=side))
                index += 1
    report = MODULE.binary_label_report(
        events,
        name="MFE_GE_1R",
        predicate=lambda row: row["mfe_R"] >= 1.0,
    )
    assert report["positive"] == 48
    assert report["negative"] == 48
    assert report["readiness"]["penalized_pilot_ready"] is True


def test_label_ladder_prefers_highest_feasible_mfe_threshold() -> None:
    events = []
    index = 0
    for window in MODULE.WINDOWS:
        for side in MODULE.SIDES:
            for _ in range(10):
                events.append(event(index, mfe=1.6, label="TIMEOUT", window=window, side=side))
                index += 1
            for _ in range(10):
                events.append(event(index, mfe=0.3, label="SL_FIRST", window=window, side=side))
                index += 1
    ladder = MODULE.label_ladder(events)
    assert ladder["preferred_diagnostic_label"] == "MFE_GE_1.5R"


def test_tp_sample_plan_retires_fixed_200_gate() -> None:
    events = []
    for index in range(155):
        label = "TP_FIRST" if index < 11 else ("SL_FIRST" if index < 81 else "TIMEOUT")
        events.append(
            event(
                index,
                mfe=2.1 if label == "TP_FIRST" else 0.4,
                label=label,
                window=MODULE.WINDOWS[index % 2],
                side=MODULE.SIDES[index % 2],
            )
        )
    plan = MODULE.tp_sample_plan(events)
    assert plan["current"]["tp_events"] == 11
    assert plan["scenarios"]["diagnostic_univariate"]["expected_total_at_observed_prevalence"] == 423
    assert "former fixed 200" in plan["correction"].lower()


def test_competing_risk_nonparametric_gate() -> None:
    events = []
    index = 0
    for label in ("TP_FIRST", "SL_FIRST", "TIMEOUT"):
        for _ in range(12):
            events.append(
                event(
                    index,
                    mfe=2.1 if label == "TP_FIRST" else 0.5,
                    label=label,
                    window=MODULE.WINDOWS[index % 2],
                    side=MODULE.SIDES[index % 2],
                )
            )
            index += 1
    report = MODULE.competing_risk_report(events)
    assert report["nonparametric_cumulative_incidence_ready"] is True
    assert report["cause_specific_model_ready"] is False
