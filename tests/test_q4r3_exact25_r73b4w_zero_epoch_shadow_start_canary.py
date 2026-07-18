from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "tools/q4r3_exact25_r73b4w_zero_epoch_shadow_start_canary.py"
SPEC = importlib.util.spec_from_file_location("r73b4w", MODULE)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_scalar_first_key() -> None:
    assert mod.scalar({"a": 1, "b": 2}, "a", "b") == 1


def test_scalar_default() -> None:
    assert mod.scalar({}, "x", default=7) == 7


def test_boolish_values() -> None:
    assert mod.boolish("active") is True
    assert mod.boolish(False) is False
