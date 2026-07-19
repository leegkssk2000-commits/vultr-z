from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6c2_retention_boundary_shim.py"
SPEC = importlib.util.spec_from_file_location("boundary", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeParity:
    @staticmethod
    def writer_counts(payload):
        writers = payload.get("writers7", {})
        return writers.get("configured_writer_count"), writers.get("active_writer_count")


def payload(active_present=True):
    writers = {"configured_writer_count": 7}
    if active_present:
        writers["active_writer_count"] = 0
    return {
        "safety": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
        },
        "summary": {
            "closed": 0,
            "pnl_r": "0R",
        },
        "writers7": writers,
    }


def test_ignores_volatile_active_writer_shape_only():
    assert MODULE.semantic_surface_equal(payload(True), payload(False), FakeParity) is True


def test_ignores_duplicate_nested_safety_multiplicity():
    left = payload(True)
    left["duplicate"] = {
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
    }
    assert MODULE.semantic_surface_equal(left, payload(False), FakeParity) is True


def test_rejects_closed_mismatch():
    right = payload(False)
    right["summary"]["closed"] = 1
    assert MODULE.semantic_surface_equal(payload(True), right, FakeParity) is False


def test_rejects_unsafe_execution_authority():
    right = payload(False)
    right["safety"]["execution_authority"] = "paper"
    assert MODULE.semantic_surface_equal(payload(True), right, FakeParity) is False


def test_rejects_real_order_enabled():
    right = payload(False)
    right["safety"]["real_order_enabled"] = True
    assert MODULE.semantic_surface_equal(payload(True), right, FakeParity) is False
