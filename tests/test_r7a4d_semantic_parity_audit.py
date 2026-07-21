from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "r7a4d_semantic_parity_audit.py"
spec = importlib.util.spec_from_file_location("r7a4d_semantic_parity_audit", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_expected_long_intent_mapping() -> None:
    assert module.expected_intent({"side": "long", "action": "enter"}) == "enter_long"
    assert module.expected_intent({"side": "long", "action": "add"}) == "enter_long"
    assert module.expected_intent({"side": "long", "action": "reduce"}) == "reduce"
    assert module.expected_intent({"side": "long", "action": "exit"}) == "exit_long"
    assert module.expected_intent({"side": "short", "action": "enter"}) == "hold"


def test_signal_normalization_is_order_independent() -> None:
    left = {
        "side": "LONG",
        "action": "ENTER",
        "size": 0.5,
        "entry": 100,
        "sl": 99,
        "tp": 102,
        "why": "Reason",
        "skill": "Alpha",
        "confidence": 0.7,
    }
    right = {
        "confidence": 0.70000000001,
        "skill": "alpha",
        "why": "reason",
        "tp": 102.0,
        "sl": 99.0,
        "entry": 100.0,
        "size": 0.5,
        "action": "enter",
        "side": "long",
    }
    assert module.signal_equal(left, right)


def test_static_scope_detects_long_only_marker() -> None:
    scope = module.static_scope(
        "return StrategyDecision(intent=StrategyIntent.HOLD, "
        "reason='short_signal_generated_but_core_is_long_only', "
        "payload={'legacy_signal': result})"
    )
    assert scope["explicit_long_only_marker"] is True
    assert scope["legacy_signal_payload_present"] is True
    assert scope["enter_short_intent_present"] is False


def test_make_state_variants() -> None:
    flat = module.make_state("flat", 100.0)
    long = module.make_state("long", 100.0)
    short = module.make_state("short", 100.0)
    assert flat["position_qty"] == 0.0
    assert long["position_side"] == "long" and long["avg_entry"] == 99.0
    assert short["position_side"] == "short" and short["avg_entry"] == 101.0
