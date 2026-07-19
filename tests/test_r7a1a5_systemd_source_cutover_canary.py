from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a5_systemd_source_cutover_canary.py"
SPEC = importlib.util.spec_from_file_location("r7a1a5", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_replace_source_arg_replaces_exactly_one_source():
    old = Path("/usr/local/bin/adapter.py")
    new = Path("/opt/zel/releases/abc/adapter.py")
    argv = ["/usr/bin/python3", str(old), "--example"]
    assert MODULE.replace_source_arg(argv, old, new) == ["/usr/bin/python3", str(new), "--example"]
    assert argv[1] == str(old)


def test_replace_source_arg_rejects_ambiguous_or_missing_source():
    old = Path("/usr/local/bin/adapter.py")
    new = Path("/opt/zel/releases/abc/adapter.py")
    for argv in (["python3"], ["python3", str(old), str(old)]):
        try:
            MODULE.replace_source_arg(list(argv), old, new)
        except ValueError as exc:
            assert "LEGACY_EXEC_SOURCE_COUNT" in str(exc)
        else:
            raise AssertionError("ambiguous source must be rejected")


def test_source_dropin_resets_and_pins_execstart():
    text = MODULE.source_dropin_text(["/usr/bin/python3", "/opt/zel/releases/abc/adapter.py"])
    assert text.startswith("[Service]\nExecStart=\nExecStart=")
    assert '"/usr/bin/python3"' in text
    assert '"/opt/zel/releases/abc/adapter.py"' in text


def test_canonical_analysis_requires_commands_and_env_without_secret():
    source = b'''\nimport os\ntoken = os.environ.get("ZEL_TELEGRAM_BOT_TOKEN", "")\nchat_id = os.environ.get("ZEL_TELEGRAM_ALLOWED_CHAT_ID", "")\n# /pos /pnl /view\n'''
    result = MODULE.canonical_analysis(source)
    assert result["compile_ok"] is True
    assert result["secret_literal_count"] == 0
    assert all(result["command_counts"][command] == 1 for command in MODULE.REQUIRED_COMMANDS)
    assert set(MODULE.REQUIRED_ENV_KEYS).issubset(result["environment_keys"])


def test_report_semantics_rejects_authority_drift():
    good = {
        "status": "PASS_TELEGRAM_POS_ADAPTER_V2_RUNNING",
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
    }
    assert MODULE.report_semantics(good) == (True, [])
    bad = dict(good, order_authority="enabled")
    ok, blockers = MODULE.report_semantics(bad)
    assert ok is False
    assert "ORDER_AUTHORITY_NOT_BLOCKED" in blockers
