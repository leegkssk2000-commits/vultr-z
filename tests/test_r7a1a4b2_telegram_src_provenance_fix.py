from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4b2_telegram_src_provenance_fix.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4b2", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_main_semantics_accepts_ordered_bindings():
    source = b'''\nimport os\ndef main():\n    token = os.environ.get("ZEL_TELEGRAM_BOT_TOKEN", "")\n    src = "env:ZEL_TELEGRAM_BOT_TOKEN"\n    if not token:\n        print(src)\n    chat_id = os.environ.get("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "")\n    print(src, chat_id)\n'''
    result = MODULE.main_semantics(source)
    assignments = result["assignments"]
    assert assignments["token"][0]["environment_key"] == "ZEL_TELEGRAM_BOT_TOKEN"
    assert assignments["src"][0]["constant_matches_expected_src"] is True
    assert assignments["chat_id"][0]["environment_key"] == "ZEL_TELEGRAM_ALLOWED_CHAT_ID"
    assert result["undefined_src_use_lines"] == []


def test_main_semantics_detects_src_use_before_assignment():
    source = b'''\ndef main():\n    print(src)\n    src = "env:ZEL_TELEGRAM_BOT_TOKEN"\n'''
    result = MODULE.main_semantics(source)
    assert result["undefined_src_use_lines"] == [3]


def test_hardcoded_secret_count():
    assert MODULE.hardcoded_secret_count(b'token = "123456789:abcdefghijklmnopqrstuvwxyzABCDE"') == 1
    assert MODULE.hardcoded_secret_count(b'token = os.environ.get("KEY", "")') == 0
