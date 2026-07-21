from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "r7a4d2_targeted_trigger_geometry_diagnose.py"
SPEC = importlib.util.spec_from_file_location("r7a4d2_targeted_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_valid_geometry_long_and_short() -> None:
    assert module.valid_geometry({"side": "long", "action": "enter", "size": 0.5, "entry": 100, "sl": 98, "tp": 104})
    assert module.valid_geometry({"side": "short", "action": "add", "size": 0.2, "entry": 100, "sl": 103, "tp": 96})
    assert not module.valid_geometry({"side": "long", "action": "enter", "size": 0.5, "entry": 100, "sl": 101, "tp": 104})
    assert not module.valid_geometry({"side": "short", "action": "enter", "size": 0.5, "entry": 100, "sl": 103, "tp": 101})
    assert module.valid_geometry({"side": None, "action": "hold", "size": 0, "entry": 0, "sl": 0, "tp": 0})


def test_classify_strategy_priority() -> None:
    base = {
        "adapter_errors": 0,
        "direct_errors": 0,
        "direct_payload_mismatches": 0,
        "long_mapping_mismatches": 0,
        "invalid_geometry": 0,
        "long_active": 0,
        "short_active": 0,
    }

    item = dict(base, invalid_geometry=2, short_active=5)
    assert module.classify_strategy(item, 0) == "PAYLOAD_GEOMETRY_FAIL"

    item = dict(base, long_active=3)
    assert module.classify_strategy(item, 0) == "A4D_ZERO_WITH_FULL_SCAN_LONG_TRIGGER"

    item = dict(base, short_active=7)
    assert module.classify_strategy(item, 0) == "FULL_SCAN_SHORT_ONLY_TRIGGER"

    assert module.classify_strategy(base, 0) == "FULL_SCAN_NO_ACTIVE_TRIGGER"

    item = dict(base, long_active=2, short_active=3)
    assert module.classify_strategy(item, 4) == "FULL_SCAN_BOTH_SIDES_TRIGGER"
