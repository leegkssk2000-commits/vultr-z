from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_tb12_contamination_eradication_audit.py"
SPEC = importlib.util.spec_from_file_location("tb12", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def analyze(tmp_path: Path, relative: str, source: str):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path, module.analyze_python(path, source)


def test_backup_and_release_freeze_are_contamination(tmp_path: Path) -> None:
    for relative in (
        "backend/backups/tv_webhook.py",
        "backend/release_freeze/20260420/tv_webhook.py",
        "backend/_LIVE_BACKUP_2026/lbot.py",
        "backend/archive/zbot.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("class LBot: pass", encoding="utf-8")
        flagged, reason = module.contaminated(path)
        assert flagged is True
        assert reason


def test_canonical_runtime_is_not_contamination(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/exchange_adapter_bingx.py"
    path.parent.mkdir(parents=True)
    path.write_text("class BingXAdapter: pass", encoding="utf-8")
    assert module.contaminated(path) == (False, None)


def test_generic_environment_access_is_not_private_execution(tmp_path: Path) -> None:
    _, row = analyze(
        tmp_path,
        "backend/main.py",
        "import os\nclass ZBotCore: pass\nroot=os.getenv('Z_HOME')\n",
    )
    assert row["generic_env_accesses"]
    assert row["credential_accesses"] == []
    assert row["direct_execution_semantic"] is False


def test_tv_secret_file_is_not_exchange_private_execution(tmp_path: Path) -> None:
    _, row = analyze(
        tmp_path,
        "backend/config/constants.py",
        "import os\nclass LBotConfig: pass\npath=os.getenv('TV_SECRET_FILE')\n",
    )
    assert row["credential_accesses"] == []
    assert row["direct_execution_semantic"] is False


def test_sensitive_credential_without_exchange_constructor_is_not_direct(tmp_path: Path) -> None:
    _, row = analyze(
        tmp_path,
        "backend/config/keys.py",
        "import os\nclass ZBotConfig: pass\nkey=os.getenv('BINGX_API_KEY')\n",
    )
    assert row["credential_accesses"]
    assert row["exchange_constructors"] == []
    assert row["direct_execution_semantic"] is False


def test_exchange_constructor_plus_sensitive_credential_is_direct(tmp_path: Path) -> None:
    _, row = analyze(
        tmp_path,
        "backend/engine/zbot_core.py",
        "import os\nclass BingXClient: pass\nclass ZBotCore:\n    def run(self):\n        key=os.getenv('BINGX_API_KEY')\n        return BingXClient(key)\n",
    )
    assert row["credential_accesses"]
    assert row["exchange_constructors"]
    assert row["direct_execution_semantic"] is True


def test_actual_create_order_call_is_direct(tmp_path: Path) -> None:
    _, row = analyze(
        tmp_path,
        "backend/engine/lbot_core.py",
        "class LBotCore:\n    def run(self, exchange):\n        return exchange.create_order('BTC/USDT')\n",
    )
    assert row["direct_order_calls"]
    assert row["direct_execution_semantic"] is True


def test_support_script_is_not_runtime_owner(tmp_path: Path) -> None:
    path, row = analyze(
        tmp_path,
        "backend/scripts/verify_zlice_contract.py",
        "class ZliceVerifier: pass\n",
    )
    assert module.support_surface(path) is True
    assert row["kind"] == "support"
