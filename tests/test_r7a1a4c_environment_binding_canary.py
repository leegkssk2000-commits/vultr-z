from pathlib import Path
import importlib.util
import os
import stat


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4c_environment_binding_canary.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4c", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_env_text_supports_plain_lines():
    text = '''\nEXAMPLE_A=value-a\nEXAMPLE_B=value-b\n# EXAMPLE_C=ignored\n'''
    assert MODULE.parse_env_text(text) == {"EXAMPLE_A": "value-a", "EXAMPLE_B": "value-b"}


def test_direct_environment_keys_are_derived_from_ast():
    source = b'''\nimport os\ndef main():\n    token = os.environ.get("KEY_A", "")\n    src = "env:KEY_A"\n    chat_id = os.environ.get("KEY_B", "")\n'''
    assert MODULE.direct_environment_keys(source) == {"token": "KEY_A", "chat_id": "KEY_B"}


def test_extract_bind_chat_id_accepts_private_self_sender_only():
    payload = {
        "ok": True,
        "result": [
            {
                "update_id": 10,
                "message": {
                    "text": "/bind",
                    "chat": {"id": 123456, "type": "private"},
                    "from": {"id": 123456},
                },
            }
        ],
    }
    chat_id, offset, seen = MODULE.extract_bind_chat_id(payload)
    assert chat_id == "123456"
    assert offset == 11
    assert seen == 1


def test_write_environment_is_root_only_shape(tmp_path, monkeypatch):
    path = tmp_path / "telegram.env"
    monkeypatch.setattr(os, "chown", lambda *args, **kwargs: None)
    MODULE.write_environment(path, "KEY_A", "opaque-value", "KEY_B", "123456")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == "KEY_A=opaque-value\nKEY_B=123456\n"


def test_protected_snapshot_keys(tmp_path):
    result = MODULE.protected_snapshot(tmp_path)
    assert set(result) == {"formal_ledger", "shadow_snapshot", "view_contract", "deployed_source"}
