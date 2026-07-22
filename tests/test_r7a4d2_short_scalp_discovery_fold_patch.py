from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SCALP_DISCOVERY_FOLD_PATCH"])
    spec = importlib.util.spec_from_file_location("scalp_discovery_fold_patch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_source() -> str:
    return '''def scan():
    for symbol in sorted(frames):
        trigger = frames[symbol][trigger_minutes]
        structure = frames[symbol][structure_minutes]
        for start in window_starts(len(trigger)):
            sample = trigger.iloc[start:start + WINDOW_BARS].reset_index(drop=True)
            scenario_id = f"{architecture_id}:{symbol}:{start}"
            scenario = {
                "scenario_id": scenario_id,
                "strategy_id": "scalp_snap",
                "segment_id": f"{architecture_id}:{symbol}:{start}",
            }
'''


def test_patch_adds_window_enumeration_and_fold_key() -> None:
    module = load_module()
    patched = module.apply_patch(fixture_source())
    assert "for fold, start in enumerate(window_starts(len(trigger))):" in patched
    assert '"fold": fold,' in patched
    assert patched.count('"fold": fold') == 1


def test_patch_fail_closes_when_anchor_missing() -> None:
    module = load_module()
    try:
        module.apply_patch("def unrelated():\n    pass\n")
    except ValueError as exc:
        assert "FOLD_LOOP_ANCHOR_COUNT_INVALID" in str(exc)
    else:
        raise AssertionError("missing anchor must fail")


def test_patch_rejects_already_patched_source() -> None:
    module = load_module()
    patched = module.apply_patch(fixture_source())
    try:
        module.apply_patch(patched)
    except ValueError as exc:
        assert "FOLD_LOOP_ANCHOR_COUNT_INVALID" in str(exc) or "FOLD_ALREADY_PRESENT" in str(exc)
    else:
        raise AssertionError("second patch must fail")
