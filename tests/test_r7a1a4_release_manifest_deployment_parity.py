from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4_release_manifest_deployment_parity.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_discover_environment_keys_without_values():
    source = b'''\nimport os\na = os.environ.get("EXAMPLE_ALPHA", "")\nb = os.getenv("EXAMPLE_BETA", "")\n'''
    assert MODULE.discover_environment_keys(source) == ["EXAMPLE_ALPHA", "EXAMPLE_BETA"]


def test_sensitive_assignment_detection():
    unsafe = b'token = "literal-value"\nchat_id = "literal-id"\n'
    safe = b'import os\ntoken = os.environ.get("EXAMPLE_ALPHA", "")\nchat_id = os.environ.get("EXAMPLE_BETA", "")\n'
    assert MODULE.hardcoded_sensitive_assignment_count(unsafe) == 2
    assert MODULE.hardcoded_sensitive_assignment_count(safe) == 0


def test_command_surface_counts():
    source = b'if text.startswith("/pos"): pass\n# /pnl\n# /view\n'
    assert MODULE.command_counts(source, ["/pos", "/pnl", "/view"]) == {
        "/pos": 1,
        "/pnl": 1,
        "/view": 1,
    }
