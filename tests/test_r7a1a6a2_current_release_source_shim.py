from pathlib import Path
import importlib.util
import pytest


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6a2_current_release_source_shim.py"
SPEC = importlib.util.spec_from_file_location("shim", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_selects_current_git_pinned_release_source():
    argv = [
        "/usr/bin/python3",
        "/opt/zel/releases/abc123/telegram/zel_q4r3_telegram_pos_adapter_v2.py",
    ]
    assert MODULE.select_current_source(argv) == Path(argv[1])


def test_selects_legacy_source_when_still_active():
    argv = ["/usr/bin/python3", "/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py"]
    assert MODULE.select_current_source(argv) == Path(argv[1])


def test_rejects_ambiguous_sources():
    with pytest.raises(RuntimeError, match="CURRENT_EXEC_SOURCE_COUNT_2"):
        MODULE.select_current_source([
            "/a/zel_q4r3_telegram_pos_adapter_v2.py",
            "/b/zel_q4r3_telegram_pos_adapter_v2.py",
        ])
