from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r06_bot_capability_inventory.py"
spec = importlib.util.spec_from_file_location("r06", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_role_terms_cover_all_bots() -> None:
    assert set(module.ROLE_TERMS) == {"LBot", "MBot", "OBot", "SBot"}
    assert all(module.ROLE_TERMS[bot] for bot in module.BOTS)


def test_functional_source_is_absorb(tmp_path: Path) -> None:
    path = tmp_path / "lbot_core.py"
    path.write_text("class LBotCore:\n    trend = True\n    primary = True\n", encoding="utf-8")
    row = module.inspect("LBot", path)
    assert row["disposition"] == "ABSORB"
    assert row["exact_identity_signal"] is True


def test_support_surface_is_reserve(tmp_path: Path) -> None:
    path = tmp_path / "verify_mbot_contract.py"
    path.write_text("class MBotVerifier:\n    method = True\n", encoding="utf-8")
    row = module.inspect("MBot", path)
    assert row["disposition"] == "RESERVE"


def test_backup_surface_is_quarantine(tmp_path: Path) -> None:
    path = tmp_path / "backup" / "obot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text("class OBotCore:\n    breakout = True\n", encoding="utf-8")
    row = module.inspect("OBot", path)
    assert row["disposition"] == "QUARANTINE"


def test_nonfunctional_surface_is_archive(tmp_path: Path) -> None:
    path = tmp_path / "misc.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    row = module.inspect("SBot", path)
    assert row["disposition"] == "ARCHIVE"
