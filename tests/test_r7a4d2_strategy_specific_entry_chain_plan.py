from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "tools/r7a4d2_strategy_specific_entry_chain_plan.py"
    spec = importlib.util.spec_from_file_location("r7a4d2_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valid_evidence_contract() -> None:
    module = load_module()
    reports = []
    for strategy_id, classification in module.TARGETS.items():
        reports.append(
            {
                "strategy_id": strategy_id,
                "classification": classification,
                "selected_flat_enter_count": 17 if strategy_id == "vwap_revert" else 0,
                "selected_synthetic_add_count": {
                    "break_and_continue": 4,
                    "rbreaker_like": 33,
                    "squeeze_break": 17,
                    "trend_ma_macd": 10,
                    "vwap_revert": 69,
                }[strategy_id],
            }
        )
    evidence = {
        "state": "HOLD_ENTRY_TRIGGER_REDESIGN_REQUIRED",
        "blocker_count": 0,
        "strategy_reports": reports,
    }
    assert module.validate_evidence(evidence) == []


def test_plan_is_fail_closed_and_ordered() -> None:
    module = load_module()
    plan = module.build_plan()
    assert plan["state"] == "PASS_STRATEGY_SPECIFIC_ENTRY_CHAIN_PLAN"
    assert plan["simulation_preroll_plan"]["indicator_preroll_bars"] == 320
    assert plan["simulation_preroll_plan"]["evaluation_bars"] == 320
    assert "do not relax any entry threshold or market filter" in plan["entry_lineage_plan"]["rules"]
    assert plan["verification_order"][-2] == "rerun the full 3600 matrix from a new result directory"
    assert plan["next_stage"] == "R7.A4D2_ENTRY_CHAIN_MINIMAL_PATCH"


def test_bad_classification_is_rejected() -> None:
    module = load_module()
    evidence = {
        "state": "HOLD_ENTRY_TRIGGER_REDESIGN_REQUIRED",
        "blocker_count": 0,
        "strategy_reports": [
            {
                "strategy_id": strategy_id,
                "classification": "WRONG",
                "selected_flat_enter_count": 0,
                "selected_synthetic_add_count": 0,
            }
            for strategy_id in module.TARGETS
        ],
    }
    assert module.validate_evidence(evidence)
