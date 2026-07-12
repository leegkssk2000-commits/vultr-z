from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_runtime_write_pid_trace_v2.py"
    spec = importlib.util.spec_from_file_location("q4r3_runtime_write_pid_trace_v2_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()
EXPECTED = "FROZEN_OBSERVER_RESERVE"


def test_top_level_state_is_promoted_to_legacy_guard_key() -> None:
    payload = {"status": "PASS_Q4R3_RASCHKE_FREEZE_MANIFEST", "state": EXPECTED}
    normalized = MODULE.normalize_freeze_manifest(payload)
    assert normalized["raschke_state"] == EXPECTED
    assert payload.get("raschke_state") is None


def test_nested_full_state_is_promoted() -> None:
    payload = {"full": {"state": EXPECTED}}
    normalized = MODULE.normalize_freeze_manifest(payload)
    assert normalized["raschke_state"] == EXPECTED


def test_consistent_legacy_and_current_state_are_accepted() -> None:
    payload = {"raschke_state": EXPECTED, "state": EXPECTED, "full": {"state": EXPECTED}}
    assert MODULE.freeze_state(payload) == EXPECTED


def test_conflicting_state_paths_are_not_promoted() -> None:
    payload = {"raschke_state": "ACTIVE", "state": EXPECTED, "full": {"state": EXPECTED}}
    normalized = MODULE.normalize_freeze_manifest(payload)
    assert normalized["raschke_state"] == "ACTIVE"
    assert MODULE.freeze_state(payload) is None


def test_nonfrozen_state_is_not_promoted() -> None:
    payload = {"state": "ACTIVE"}
    normalized = MODULE.normalize_freeze_manifest(payload)
    assert "raschke_state" not in normalized
