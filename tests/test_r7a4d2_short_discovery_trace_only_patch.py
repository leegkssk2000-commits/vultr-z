from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_DISCOVERY_PATCH"])
    spec = importlib.util.spec_from_file_location("discovery_patch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_source() -> str:
    return '''SHORT_CANDIDATE_TRACE_V1 = True
SHORT_POLICY_ALLOWED_REGIMES = frozenset({"trend_down"})

def simulate():
    short_candidate_trace: list[dict[str, Any]] = []
    strategy_call_count = 0
    for _ in [0]:
        intent_histogram[intent] += 1
        if intent not in allowed_intents:
            raise ValueError(f"OUTPUT_INTENT_NOT_ALLOWED:{intent}")
    return {
        "short_candidate_trace": short_candidate_trace,
        "short_closed_trade_count": sum(
            1 for trade in trades if str(trade.get("side") or "") == "short"
        ),
    }
'''


def test_canonical_long_intents_are_skipped_only_in_discovery() -> None:
    module = load_module()
    patched = module.apply_patch(synthetic_source())
    assert 'DISCOVERY_NON_SHORT_INTENTS = frozenset({"enter_long", "reduce", "exit_long"})' in patched
    assert "if SHORT_DISCOVERY_TRACE_ONLY_V1 and intent in DISCOVERY_NON_SHORT_INTENTS:" in patched
    assert "discovery_non_short_intent_skip_count += 1" in patched
    assert '"discovery_non_short_intent_skip_count": discovery_non_short_intent_skip_count' in patched


def test_unknown_intent_remains_fail_closed() -> None:
    module = load_module()
    patched = module.apply_patch(synthetic_source())
    assert 'raise ValueError(f"OUTPUT_INTENT_NOT_ALLOWED:{intent}")' in patched
    assert "DISCOVERY_NON_SHORT_INTENTS" in patched
    assert "unknown" not in patched


def test_all_short_execution_remains_blocked() -> None:
    module = load_module()
    patched = module.apply_patch(synthetic_source())
    assert "SHORT_POLICY_ALLOWED_REGIMES = frozenset()" in patched
