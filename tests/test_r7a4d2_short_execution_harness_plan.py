from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7a4d2_short_execution_harness_plan.py"
spec = importlib.util.spec_from_file_location("short_plan", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def valid_entry_proof() -> dict:
    return {
        "state": "PASS_ENTRY_CHAIN_MINIMAL_PATCH",
        "blocker_count": 0,
        "targeted_scenario_count": 120,
        "completed_scenario_count": 120,
        "failed_scenario_count": 0,
        "strategy_trade_counts": {"vwap_revert": 6},
        "orphan_add_block_count": 0,
        "evaluation_bar_invalid_count": 0,
        "source_registry_parity": True,
        "side_effect_attempts": [],
        "mutation_paths": [],
    }


def valid_semantic() -> dict:
    reports = []
    for index in range(25):
        reports.append(
            {
                "strategy_id": f"strategy_{index}",
                "short_downgrade_count": 2 if index < 11 else 0,
            }
        )
    return {
        "strategy_count": 25,
        "adapter_error_count": 0,
        "direct_payload_mismatch_count": 0,
        "long_mapping_mismatch_count": 0,
        "short_scope_gap_strategy_count": 11,
        "strategy_reports": reports,
    }


def test_entry_chain_proof_contract() -> None:
    assert module.validate_entry_chain_proof(valid_entry_proof()) == []
    broken = valid_entry_proof()
    broken["orphan_add_block_count"] = 1
    assert module.validate_entry_chain_proof(broken)


def test_short_target_extraction_is_exact() -> None:
    targets, downgrade_count, errors = module.short_targets(valid_semantic())
    assert errors == []
    assert len(targets) == 11
    assert downgrade_count == 22


def test_plan_preserves_long_and_defines_short_math() -> None:
    targets = [f"strategy_{index}" for index in range(11)]
    plan = module.build_plan(targets, 22)
    assert plan["state"] == "PASS_SHORT_EXECUTION_HARNESS_PLAN"
    assert plan["mutation_scope"]["production_adapter_mutation_allowed"] is False
    assert plan["short_state_machine"]["entry_geometry"] == "tp < fill < stop and quantity > 0"
    assert plan["short_state_machine"]["collision_policy"] == "STOP_FIRST_CONSERVATIVE"
    assert plan["preserved_contracts"]["long_result_regression_allowed"] is False
    assert plan["targeted_verification"]["scenario_count"] == 600
    assert plan["next_stage"] == "R7.A4D2_SHORT_EXECUTION_HARNESS_MINIMAL_PATCH"


def test_runner_markers_fail_closed() -> None:
    source = '''
short_shadow_signal_count = 0
short_signal_generated_but_core_is_long_only = True
if kind in {"enter", "add"}:
    pass
if intent == "enter_long":
    pass
elif intent == "reduce":
    pass
elif intent == "exit_long":
    pass
stop_hit = low_price <= float(position["stop"])
tp_hit = high_price >= float(position["tp"])
'''
    assert module.validate_runner_source(source) == []
    assert module.validate_runner_source(source.replace("short_shadow_signal_count", "missing"))
