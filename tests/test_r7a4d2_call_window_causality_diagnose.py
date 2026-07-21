from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "tools/r7a4d2_call_window_causality_diagnose.py"
    spec = importlib.util.spec_from_file_location("r7a4d2_window_diag", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classifies_current_source_replay_trade_first() -> None:
    module = load_module()
    classification = module.classify_causality(
        {
            "targeted_replay_trade_count": 2,
            "flat_executable_long_enter_count": 1,
            "long_state_add_count": 9,
        }
    )
    assert classification == "CURRENT_SOURCE_TARGETED_REPLAY_TRADES_PRESENT"


def test_classifies_fill_geometry_rejection() -> None:
    module = load_module()
    classification = module.classify_causality(
        {
            "flat_executable_long_enter_count": 3,
            "targeted_replay_enter_signal_count": 3,
            "targeted_replay_invalid_signal_count": 3,
            "targeted_replay_trade_count": 0,
        }
    )
    assert classification == "EXECUTABLE_ENTRY_REJECTED_AT_FILL_GEOMETRY"


def test_classifies_terminal_only_entry() -> None:
    module = load_module()
    classification = module.classify_causality(
        {
            "flat_executable_long_enter_count": 0,
            "flat_terminal_long_enter_count": 4,
            "long_state_add_count": 8,
            "targeted_replay_trade_count": 0,
        }
    )
    assert classification == "TERMINAL_BAR_ONLY_NON_EXECUTABLE_ENTRY"


def test_classifies_orphan_add_only() -> None:
    module = load_module()
    classification = module.classify_causality(
        {
            "flat_executable_long_enter_count": 0,
            "flat_terminal_long_enter_count": 0,
            "long_state_add_count": 12,
            "targeted_replay_trade_count": 0,
        }
    )
    assert classification == "ORPHAN_ADD_ONLY_WITHOUT_FLAT_ENTRY"


def test_classifies_short_entry_scope_only() -> None:
    module = load_module()
    classification = module.classify_causality(
        {
            "flat_executable_long_enter_count": 0,
            "flat_terminal_long_enter_count": 0,
            "long_state_add_count": 0,
            "flat_executable_short_enter_count": 7,
            "targeted_replay_trade_count": 0,
        }
    )
    assert classification == "SHORT_ENTRY_SCOPE_ONLY"


def test_synthetic_positions_match_a4d_shape() -> None:
    module = load_module()
    flat = module.synthetic_position("flat", 100.0)
    long = module.synthetic_position("long", 100.0)
    short = module.synthetic_position("short", 100.0)
    assert set(flat) == {"side", "qty", "avg_entry", "add_count", "last_add_price"}
    assert flat["qty"] == 0.0
    assert long["side"] == "long" and long["avg_entry"] == 99.0
    assert short["side"] == "short" and short["avg_entry"] == 101.0
