from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools/r7a4d2_entry_trigger_chain_causality_diagnose.py"
)
spec = importlib.util.spec_from_file_location("r7a4d2_entry_chain_test_module", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_missing_entry_predicates_models() -> None:
    assert module.missing_entry_predicates(
        "break_and_continue",
        {
            "up_break": True,
            "tight_box": True,
            "long_breakout_now": False,
            "long_reclaim": True,
            "trend_long": False,
        },
    ) == ["long_breakout_now", "trend_long"]
    assert module.missing_entry_predicates(
        "rbreaker_like", {"long_break": False, "long_reversal": False}
    ) == ["long_break_or_long_reversal"]
    assert module.missing_entry_predicates(
        "squeeze_break", {"released": False, "long_break": False, "trend_long": True}
    ) == ["released", "long_break"]
    assert module.missing_entry_predicates(
        "trend_ma_macd", {"trend_long": True, "hist_cross_up": False}
    ) == ["hist_cross_up"]
    assert module.missing_entry_predicates(
        "vwap_revert",
        {"long_extension": True, "long_reclaim": False, "long_beam": False},
    ) == ["long_reclaim_or_long_beam"]


def test_classification_presegment_dependency() -> None:
    report = {
        "strategy_id": "squeeze_break",
        "strategy_error_count": 0,
        "selected_flat_enter_count": 0,
        "presegment_flat_enter_count": 3,
        "baseline_trade_count": 0,
        "extended_trade_count": 2,
        "selected_synthetic_add_count": 4,
    }
    assert module.classify_report(report) == "PRESEGMENT_ENTRY_CHAIN_DEPENDENCY"


def test_classification_strategy_specific_causes() -> None:
    base = {
        "strategy_error_count": 0,
        "selected_flat_enter_count": 0,
        "presegment_flat_enter_count": 0,
        "baseline_trade_count": 0,
        "extended_trade_count": 0,
        "selected_synthetic_add_count": 2,
    }
    assert module.classify_report(
        {**base, "strategy_id": "break_and_continue"}
    ) == "ENTRY_FILTER_STRICTER_THAN_ADD"
    assert module.classify_report(
        {**base, "strategy_id": "trend_ma_macd"}
    ) == "ONE_SHOT_EVENT_TO_ADD_CHAIN_GAP"
    assert module.classify_report(
        {**base, "strategy_id": "vwap_revert"}
    ) == "SYNTHETIC_POSITION_ADD_ARTIFACT"


def test_execution_gap_has_priority() -> None:
    report = {
        "strategy_id": "rbreaker_like",
        "strategy_error_count": 0,
        "selected_flat_enter_count": 1,
        "presegment_flat_enter_count": 0,
        "baseline_trade_count": 0,
        "extended_trade_count": 0,
        "selected_synthetic_add_count": 1,
    }
    assert module.classify_report(report) == "SIMULATION_ENTRY_EXECUTION_GAP"
