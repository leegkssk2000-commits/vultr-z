from pathlib import Path
import importlib.util
from types import SimpleNamespace
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


def test_clean_a1a5a_requires_pass_and_none():
    assert MODULE.clean_a1a5a({"state": "PASS", "runtime_error_class": "NONE"}) is True
    assert MODULE.clean_a1a5a({"state": "HOLD", "runtime_error_class": "NONE"}) is False
    assert MODULE.clean_a1a5a({"state": "PASS", "runtime_error_class": "NETWORK_TIMEOUT"}) is False


def test_first_a1a5_gate_is_recovered_but_later_status_is_real(tmp_path):
    a1a5 = (tmp_path / MODULE.A1A5_STATUS_REL).resolve()
    a1a5a = (tmp_path / MODULE.A1A5A_STATUS_REL).resolve()
    calls = []

    def load_json(path):
        resolved = Path(path).resolve()
        calls.append(resolved)
        if resolved == a1a5a:
            return {"state": "PASS", "runtime_error_class": "NONE"}
        if resolved == a1a5:
            return {"state": "HOLD", "blockers": ["OLD_CANARY_HOLD"]}
        return {}

    fake = SimpleNamespace(load_json=load_json)
    state = MODULE.install_first_gate_recovery(fake, tmp_path)

    first = fake.load_json(a1a5)
    second = fake.load_json(a1a5)

    assert first["state"] == "PASS"
    assert first["gate_source"] == "R7A1A5A_CLEAN_PASS"
    assert second["state"] == "HOLD"
    assert state["used"] is True
    assert calls.count(a1a5a) == 1
