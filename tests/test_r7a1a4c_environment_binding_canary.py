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


def test_parse_env_text_supports_systemd_and_plain_lines():
    text = '''\nEnvironment="EXAMPLE_A=value-a"\nEXAMPLE_B=value-b\n# EXAMPLE_C=ignored\n'''
    assert MODULE.parse_env_text(text) == {"EXAMPLE_A": "value-a", "EXAMPLE_B": "value-b"}


def test_token_and_named_chat_patterns():
    token = "123456789:abcdefghijklmnopqrstuvwxyzABCDE12345"
    text = f'''\nTOKEN={token}\nZEL_TELEGRAM_ALLOWED_CHAT_ID=-123456789\n'''
    assert MODULE.TOKEN_RE.search(text).group(0) == token
    assert MODULE.CHAT_ASSIGN_RE.search(text).group(1) == "-123456789"


def test_write_secret_environment_is_root_only_shape(tmp_path, monkeypatch):
    path = tmp_path / "telegram.env"
    monkeypatch.setattr(os, "chown", lambda *args, **kwargs: None)
    MODULE.write_secret_environment(path, "123456789:abcdefghijklmnopqrstuvwxyzABCDE12345", "123456789")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    text = path.read_text(encoding="utf-8")
    assert text.count("ZEL_TELEGRAM_BOT_TOKEN=") == 1
    assert text.count("ZEL_TELEGRAM_ALLOWED_CHAT_ID=") == 1


def test_protected_snapshot_keys(tmp_path):
    result = MODULE.protected_snapshot(tmp_path)
    assert set(result) == {"formal_ledger", "shadow_snapshot", "view_contract", "deployed_source"}
