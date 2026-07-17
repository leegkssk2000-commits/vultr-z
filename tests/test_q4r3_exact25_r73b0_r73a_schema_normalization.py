from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b0_audit_display_binding_residue_v4.py"
SPEC = importlib.util.spec_from_file_location("r73b0_v4", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_nested_runtime_active_is_promoted() -> None:
    payload = {"state": "PASS", "report": {"runtime_active": False}}
    normalized = module.normalize_r73a(payload)
    assert normalized["state"] == "PASS"
    assert normalized["runtime_active"] is False


def test_top_level_runtime_active_is_preserved() -> None:
    payload = {"state": "PASS", "runtime_active": False, "report": {"runtime_active": True}}
    normalized = module.normalize_r73a(payload)
    assert normalized["runtime_active"] is False
