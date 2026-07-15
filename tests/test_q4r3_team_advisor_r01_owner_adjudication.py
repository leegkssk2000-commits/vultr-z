from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_r01_owner_adjudication.py"
spec = importlib.util.spec_from_file_location("r01", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_canonical_display_names() -> None:
    assert module.canonical_component("ZICO") == "Zico"
    assert module.canonical_component("LiCo") == "Lico"
    assert module.canonical_component("LICO") == "Lico"


def test_shell_root_expansion_repairs_prior_absolute_parse(tmp_path: Path) -> None:
    root = tmp_path / "z"
    script = root / "scripts/lico_cf_source_bind_v13.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")
    record = {
        "exec_start": 'ROOT=' + str(root) + '; /usr/bin/python3 "$ROOT/scripts/lico_cf_source_bind_v13.py"',
        "working_directory": str(root),
        "resolved_script_paths": ["/scripts/lico_cf_source_bind_v13.py"],
    }
    assert module.script_paths_from_unit(record, root) == [str(script.resolve())]


def test_ast_team_assignment_is_extracted_without_source_text(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "team_lane.py"
    path.write_text(
        "TEAM = {'team_id':'AlphaTeam','main_bot':'LBot','support_bot':'MBot',"
        "'watchers':['OBot','SBot'],'helper_bot':'MBot','helper_trigger':'retest'}\n",
        encoding="utf-8",
    )
    manifest = module.source_manifest(path, root)
    assert manifest["role_assignments"][0]["team_id"] == "AlphaTeam"
    assert manifest["source_text_included"] is False
    assert "TEAM =" not in json.dumps(manifest)


def test_package_grouping_keeps_files_together(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    rows = [
        {"path": str(root / "backend/engine/lbot_core.py"), "score": 55, "git": {"tracked": False}},
        {"path": str(root / "backend/engine/lbot_models.py"), "score": 55, "git": {"tracked": False}},
    ]
    groups = module.group_candidates("LBot", rows, root)
    assert len(groups) == 1
    assert groups[0]["candidate_count"] == 2


def test_active_external_zico_routes_to_git_mirror() -> None:
    owner_state = {
        "proven_owners": [{
            "path": "/opt/zico-ceo-canonical-adapter/adapter.py",
            "git": {"tracked": False},
        }]
    }
    route, reasons = module.adjudication_route(
        "Zico", owner_state, [], [], ["/opt/zico-ceo-canonical-adapter/adapter.py"], [], 44.4
    )
    assert route == "MIRROR_ACTIVE_RUNTIME_TO_GIT"
    assert reasons


def test_team_with_assignment_routes_to_recovery() -> None:
    route, _ = module.adjudication_route(
        "AlphaTeam", {}, [], [], ["/usr/local/bin/team.py"],
        [{"role_assignments": [{"team_id": "AlphaTeam", "main_bot": "LBot"}]}], None,
    )
    assert route == "RECOVER_TEAM_PACKAGE_FROM_ACTIVE_RUNTIME"


def test_role_words_alone_do_not_create_owner() -> None:
    route, _ = module.adjudication_route("MBot", {}, [], [], [], [], None)
    assert route == "CANONICAL_IMPLEMENTATION_MISSING"


def test_zbot_incomplete_policy_requires_provider_package() -> None:
    route, _ = module.adjudication_route("ZBot", {}, [{"path": "/x/zbot.py"}], [], [], [], 15.3846)
    assert route == "CONSOLIDATE_ZBOT_AND_BUILD_PROVIDER_POLICY_PACKAGE"


def test_authority_is_read_only() -> None:
    report = module.build_report(
        Path("/tmp/nonexistent-root"),
        {
            "state": "HOLD",
            "verdict": "R0_CANONICAL_TRUTH_UNRESOLVED",
            "canonical_owner_count": 1,
            "candidate_inventory": {},
            "owner_matrix": {},
        },
        {},
        [],
    )
    assert report["authority"] == {
        "observer_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "runtime_mutation_performed": False,
        "historical_backfill_performed": False,
    }
