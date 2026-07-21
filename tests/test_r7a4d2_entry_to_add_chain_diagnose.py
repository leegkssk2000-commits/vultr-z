from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/r7a4d2_entry_to_add_chain_diagnose.py"
spec = importlib.util.spec_from_file_location("entry_to_add_diag", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def valid_geometry() -> dict:
    return {"invalid_geometry_count": 0}


def valid_call_window() -> dict:
    return {
        "state": "HOLD_INPUT_INVALID",
        "blockers": ["PRIOR_GEOMETRY_NOT_CLOSED"],
        "target_strategy_count": 5,
        "flat_executable_long_enter_count": 0,
        "flat_terminal_long_enter_count": 0,
        "long_state_add_count": 74,
        "targeted_replay_trade_count": 0,
        "classification_histogram": {
            "ORPHAN_ADD_ONLY_WITHOUT_FLAT_ENTRY": 5
        },
    }


def test_accepts_known_false_geometry_blocker_when_geometry_is_zero() -> None:
    assert module.prior_call_window_acceptable(valid_call_window(), valid_geometry())


def test_rejects_real_geometry_gap() -> None:
    geometry = {"invalid_geometry_count": 1}
    assert not module.prior_call_window_acceptable(valid_call_window(), geometry)


def test_rejects_flat_entry_or_trade_presence() -> None:
    call_window = valid_call_window()
    call_window["flat_executable_long_enter_count"] = 1
    assert not module.prior_call_window_acceptable(call_window, valid_geometry())

    call_window = valid_call_window()
    call_window["targeted_replay_trade_count"] = 1
    assert not module.prior_call_window_acceptable(call_window, valid_geometry())


def test_action_literal_ast_collection() -> None:
    source = '''
def strategy(flag):
    if flag:
        return build(action="enter")
    return build(action="add")
'''
    values = module.action_literals(source)
    assert values["enter"] == 1
    assert values["add"] == 1


def test_chain_classification_requires_role_authority() -> None:
    assert (
        module.classify_chain(
            enter_literal_count=0, add_literal_count=2, role_present=False
        )
        == "STRUCTURAL_ADD_OVERLAY_ROLE_UNDECLARED"
    )
    assert (
        module.classify_chain(
            enter_literal_count=1, add_literal_count=2, role_present=False
        )
        == "STANDALONE_CAPABLE_ROLE_UNDECLARED_CHAIN_UNREACHABLE"
    )
    assert (
        module.classify_chain(
            enter_literal_count=1, add_literal_count=2, role_present=True
        )
        == "STANDALONE_CAPABLE_SELECTED_MARKET_CHAIN_UNREACHABLE"
    )
