from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6c2_retention_boundary_shim.py"
SPEC = importlib.util.spec_from_file_location("boundary", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_retention_accepts_nonempty_http_and_file_surfaces():
    assert MODULE.retention_surface_available({"closed": 0}, {"closed": 68}, object()) is True


def test_retention_ignores_volatile_alimi_semantic_difference():
    http_payload = {
        "closed": 0,
        "pnl_r": 0,
        "active_writer_count": 0,
        "order_authority": "blocked",
    }
    file_payload = {
        "closed": 68,
        "pnl_r": 53.613052,
        "recent_rows": 43,
        "order_authority": "blocked",
    }
    assert MODULE.retention_surface_available(http_payload, file_payload, object()) is True


def test_retention_rejects_missing_http_payload():
    assert MODULE.retention_surface_available({}, {"closed": 0}, object()) is False


def test_retention_rejects_missing_file_payload():
    assert MODULE.retention_surface_available({"closed": 0}, {}, object()) is False
