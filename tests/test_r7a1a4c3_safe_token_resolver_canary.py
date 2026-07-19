from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a4c3_safe_token_resolver_canary.py"
SPEC = importlib.util.spec_from_file_location("r7a1a4c3", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeBase:
    DEPLOYED_SOURCE = Path("/usr/local/bin/zel_q4r3_telegram_pos_adapter_v2.py")

    @staticmethod
    def sha256_file(path):
        return "sha:" + str(path)

    @staticmethod
    def process_environment():
        return {}


def test_scoped_snapshot_excludes_only_view_contract(tmp_path):
    result = MODULE.scoped_protected_snapshot(tmp_path, FakeBase)
    assert set(result) == {"formal_ledger", "shadow_snapshot", "deployed_source"}
    assert "view_contract" not in result


def test_process_token_preferred_when_valid():
    class Base:
        @staticmethod
        def process_environment():
            return {"TELEGRAM_BOT_TOKEN": "123456789:abcdefghijklmnopqrstuvwxyzABCDE12345"}

    assert MODULE.token_from_active_process(Base).startswith("123456789:")


def test_ast_resolver_does_not_execute_module_main(tmp_path):
    source = tmp_path / "adapter.py"
    marker = tmp_path / "main_ran"
    source.write_text(
        "import os, re\n"
        "from pathlib import Path\n"
        "def find_token():\n"
        "    return '123456789:abcdefghijklmnopqrstuvwxyzABCDE12345', 'test'\n"
        "def main():\n"
        f"    Path({str(marker)!r}).write_text('ran')\n"
        "main()\n",
        encoding="utf-8",
    )
    token = MODULE.token_from_isolated_find_token(source, timeout_seconds=5)
    assert token.startswith("123456789:")
    assert not marker.exists()


def test_ast_resolver_timeout_is_bounded(tmp_path):
    source = tmp_path / "adapter.py"
    source.write_text(
        "def find_token():\n"
        "    while True:\n"
        "        pass\n",
        encoding="utf-8",
    )
    try:
        MODULE.token_from_isolated_find_token(source, timeout_seconds=1)
    except RuntimeError as exc:
        assert str(exc) == "DEPLOYED_TOKEN_RESOLVER_TIMEOUT"
    else:
        raise AssertionError("timeout expected")
