from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r03_team_assignment_recovery.py"
spec = importlib.util.spec_from_file_location("r03", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write(tmp_path: Path, text: str) -> tuple[Path, str]:
    path = tmp_path / "source.py"
    path.write_text(text, encoding="utf-8")
    return path, module.sha256(path)


def test_complete_explicit_assignment_is_recovered(tmp_path: Path) -> None:
    path, digest = write(
        tmp_path,
        "TEAM = {'team_id':'AlphaTeam','main_bot':'LBot','support_bot':'MBot',"
        "'watchers':['OBot','SBot'],'helper_bot':'OBot','helper_trigger':'retest'}\n",
    )
    source = module.analyze_source(path, digest)
    teams = module.merge_team_evidence([source])
    assert teams["AlphaTeam"]["state"] == "EXPLICIT_ASSIGNMENT_RECOVERED"
    assert teams["AlphaTeam"]["canonical_assignment_candidate"]["main_bot"] == "LBot"
    assert teams["AlphaTeam"]["canonical_assignment_candidate"]["watchers"] == ["OBot", "SBot"]


def test_weight_profile_is_not_promoted_to_role_proof(tmp_path: Path) -> None:
    path, digest = write(
        tmp_path,
        "WEIGHTS={'BetaTeam':{'LBot':0.25,'MBot':0.45,'OBot':0.20,'SBot':0.10}}\n",
    )
    source = module.analyze_source(path, digest)
    teams = module.merge_team_evidence([source])
    assert teams["BetaTeam"]["state"] == "WEIGHT_PROFILE_ONLY_NOT_ROLE_PROOF"
    assert teams["BetaTeam"]["canonical_assignment_candidate"] is None


def test_nested_explicit_team_map_is_detected(tmp_path: Path) -> None:
    path, digest = write(
        tmp_path,
        "TEAMS={'Gamma':{'main':'OBot','support':'LBot','watchers':['MBot','SBot']}}\n",
    )
    source = module.analyze_source(path, digest)
    teams = module.merge_team_evidence([source])
    assert teams["GammaTeam"]["state"] == "EXPLICIT_ASSIGNMENT_RECOVERED"


def test_conflicting_complete_assignments_hold(tmp_path: Path) -> None:
    path, digest = write(
        tmp_path,
        "A={'team_id':'Delta','main':'SBot','support':'MBot','watchers':['LBot','OBot']}\n"
        "B={'team_id':'Delta','main':'LBot','support':'SBot','watchers':['MBot','OBot']}\n",
    )
    source = module.analyze_source(path, digest)
    teams = module.merge_team_evidence([source])
    assert teams["DeltaTeam"]["state"] == "CONFLICTING_EXPLICIT_ASSIGNMENTS"
    assert teams["DeltaTeam"]["canonical_assignment_candidate"] is None


def test_sha_change_is_visible(tmp_path: Path) -> None:
    path, _ = write(tmp_path, "VALUE=1\n")
    source = module.analyze_source(path, "0" * 64)
    assert source["sha_match"] is False


def test_sensitive_literal_is_not_published(tmp_path: Path) -> None:
    path, digest = write(
        tmp_path,
        "TEAM={'team_id':'Alpha','main':'LBot','support':'MBot','watchers':['OBot','SBot'],"
        "'helper_trigger':'API_KEY'}\n",
    )
    source = module.analyze_source(path, digest)
    records = source["explicit_records"]
    assert records
    assert "helper_trigger" not in records[0]


def test_missing_source_is_blocking_evidence(tmp_path: Path) -> None:
    source = module.analyze_source(tmp_path / "missing.py", "0" * 64)
    assert source["exists"] is False
    assert source["parse_error"] == "FILE_MISSING"
