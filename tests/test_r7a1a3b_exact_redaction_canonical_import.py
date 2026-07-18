from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a3b_exact_redaction_canonical_import.py"
SPEC = importlib.util.spec_from_file_location("r7a1a3b_importer", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def sample() -> str:
    return '''#!/usr/bin/env python3
from __future__ import annotations

class Adapter:
    pass

def pos_text():
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"
    chat_id = 123456789
    commands = ["/pos", "/pnl", "/view"]
    return token, chat_id, commands
'''


def test_exact_redaction_preserves_surface_and_commands() -> None:
    original = sample()
    redactions = {
        "token": "ZEL_TELEGRAM_BOT_TOKEN",
        "chat_id": "ZEL_TELEGRAM_ALLOWED_CHAT_ID",
    }
    sanitized, meta = MOD.sanitize_telegram(original, redactions)
    assert meta["target_count"] == 2
    assert meta["surface_preserved"] is True
    assert 'os.environ.get("ZEL_TELEGRAM_BOT_TOKEN", "")' in sanitized
    assert 'os.environ.get("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "")' in sanitized
    assert "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd" not in sanitized
    assert MOD.hardcoded_secret_count(sanitized, redactions) == 0
    for command in ("/pos", "/pnl", "/view"):
        assert sanitized.count(command) == original.count(command)
    compile(sanitized, "telegram_adapter.py", "exec")


def test_duplicate_redaction_target_is_rejected() -> None:
    original = sample() + '\ntoken = "987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZ_efgh"\n'
    redactions = {
        "token": "ZEL_TELEGRAM_BOT_TOKEN",
        "chat_id": "ZEL_TELEGRAM_ALLOWED_CHAT_ID",
    }
    try:
        MOD.sanitize_telegram(original, redactions)
    except ValueError as exc:
        assert "duplicates" in str(exc)
    else:
        raise AssertionError("duplicate token assignment was not rejected")
