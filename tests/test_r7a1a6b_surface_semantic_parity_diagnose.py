from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6b_surface_semantic_parity_diagnose.py"
SPEC = importlib.util.spec_from_file_location("r7a1a6b", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_row_count_prefers_recent_rows_scalar():
    assert MODULE.row_count({"recent_rows": 43, "rows": []}) == 43


def test_row_count_uses_list_length():
    assert MODULE.row_count({"rows": [{}, {}, {}]}) == 3


def test_critical_diff_reports_only_changed_fields():
    left = {"closed": 0.0, "pnl_r": 0.0, "configured_writer_count": 7}
    right = {"closed": 0.0, "pnl_r": 2.5, "configured_writer_count": 7}
    diff = MODULE.critical_diff(left, right)
    assert list(diff) == ["pnl_r"]
    assert diff["pnl_r"] == {"http": 0.0, "file": 2.5}


def test_critical_subset_reads_nested_safety_and_writers():
    payload = {
        "safety": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
        },
        "writers7": {"configured_writer_count": 7, "active_writer_count": 0},
        "summary": {"closed": 0, "pnl_r": "0R", "recent_rows": 0},
    }
    subset = MODULE.critical_subset(payload)
    assert subset["configured_writer_count"] == 7
    assert subset["active_writer_count"] == 0
    assert subset["closed"] == 0.0
    assert subset["pnl_r"] == 0.0
    assert subset["recent_rows"] == 0
    assert subset["order_authority"] == ("blocked",)


def test_normalized_preserves_false_boolean():
    assert MODULE.normalized(False) is False
