from pathlib import Path
import importlib.util
import sys


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6c3_runtime_shim.py"
SPEC = importlib.util.spec_from_file_location("r7a1a6c3_runtime_shim", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_numeric_zero_accepts_zero_encodings():
    assert MODULE.numeric_zero(0)
    assert MODULE.numeric_zero(0.0)
    assert MODULE.numeric_zero("0R")
    assert MODULE.numeric_zero([])


def test_numeric_zero_rejects_stale_values():
    assert not MODULE.numeric_zero(43)
    assert not MODULE.numeric_zero("53.613052R")
    assert not MODULE.numeric_zero([{}])


def test_zero_semantics_rejects_nested_stale_projection():
    payload = {"summary": {"closed": 68, "pnl_r": 53.613052, "recent_rows": 43}}
    assert MODULE.zero_semantics(payload) is False


def test_zero_semantics_ignores_unrelated_chart_rows():
    payload = {"chart": {"rows": 300}, "summary": {"closed": 0, "pnl_r": 0, "recent_rows": 0}}
    assert MODULE.zero_semantics(payload) is True


def test_zero_semantics_accepts_zero_epoch():
    payload = {"summary": {"closed": 0, "pnl_r": "0R", "recent_rows": 0}}
    assert MODULE.zero_semantics(payload) is True
