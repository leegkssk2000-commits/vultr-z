from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r51_zbot_sgrade_gap_audit.py"
spec = importlib.util.spec_from_file_location("r51_zbot_audit_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def write_r46(path: Path, *, passed: bool = True) -> None:
    payload = {
        "state": "PASS" if passed else "HOLD",
        "report": {
            "sgrade_ready": passed,
            "final_surface_count": 16 if passed else 0,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def complete_body() -> str:
    markers = []
    for surface, values in module.rules.SURFACES.items():
        if surface != "unique_canonical_owner":
            markers.append(values[0])
    return "class ZBotCore:\n    pass\n" + "\n".join(f"{value} = True" for value in markers) + "\n"


def test_complete_fixture_passes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    owner = root / "canonical/zbot.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(complete_body(), encoding="utf-8")
    r46 = tmp_path / "r46.json"
    write_r46(r46)

    payload = module.analyze(root, r46)
    assert payload["state"] == "PASS"
    assert payload["report"]["canonical_owner_count"] == 1
    assert payload["report"]["ready_surface_count"] == 24
    assert payload["report"]["missing_surface_count"] == 0


def test_missing_provider_and_budget_are_classified(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    owner = root / "canonical/zbot.py"
    owner.parent.mkdir(parents=True)
    body = complete_body().replace("openai = True\n", "").replace("gemini = True\n", "").replace("token_budget = True\n", "")
    owner.write_text(body, encoding="utf-8")
    r46 = tmp_path / "r46.json"
    write_r46(r46)

    payload = module.analyze(root, r46)
    assert payload["state"] == "HOLD"
    missing = set(payload["report"]["missing_surfaces"])
    assert {"openai_provider_adapter", "gemini_provider_adapter", "budget_token_accounting"}.issubset(missing)


def test_backup_tree_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    owner = root / "canonical/zbot.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(complete_body(), encoding="utf-8")
    backup = root / "backend/backup/zbot_old.py"
    backup.parent.mkdir(parents=True)
    backup.write_text(complete_body(), encoding="utf-8")
    r46 = tmp_path / "r46.json"
    write_r46(r46)

    payload = module.analyze(root, r46)
    assert payload["report"]["candidate_count"] == 1
    assert payload["report"]["canonical_owner_count"] == 1


def test_duplicate_canonical_owner_blocks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    first = root / "canonical/zbot.py"
    second = root / "canonical/zbot/adapter.py"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(complete_body(), encoding="utf-8")
    second.write_text("class ZBotAdapter: pass\n", encoding="utf-8")
    r46 = tmp_path / "r46.json"
    write_r46(r46)

    payload = module.analyze(root, r46)
    assert payload["state"] == "HOLD"
    assert payload["report"]["canonical_owner_count"] == 2
    assert "ZBOT_DUPLICATE_CANONICAL_OWNER" in payload["blockers"]


def test_r46_prerequisite_is_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    owner = root / "canonical/zbot.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(complete_body(), encoding="utf-8")
    r46 = tmp_path / "r46.json"
    write_r46(r46, passed=False)

    payload = module.analyze(root, r46)
    assert payload["state"] == "HOLD"
    assert "R46_LICO_SGRADE_LOCK_NOT_PROVEN" in payload["blockers"]
