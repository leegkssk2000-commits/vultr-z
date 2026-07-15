from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_sgrade_readiness_audit.py"
RUNNER_PATH = ROOT / "tools/run_q4r3_team_advisor_sgrade_readiness_audit.sh"
SSOT_PATH = ROOT / "backend/config/q4r3_team_advisor_sgrade_readiness_ssot_v1.json"

SPEC = importlib.util.spec_from_file_location("sgrade", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_backup_and_freeze_paths_are_contamination() -> None:
    for value in (
        "/home/z/z/backend/backups/zbot.py",
        "/home/z/z/backend/release_freeze/lico.py",
        "/home/z/z/backend/foo_live_backup_2026/sbot.py",
    ):
        bad, reason = module.contaminated(Path(value))
        assert bad is True
        assert reason


def test_canonical_runtime_path_is_not_contamination() -> None:
    bad, reason = module.contaminated(Path("/home/z/z/backend/engine/lbot_core.py"))
    assert bad is False
    assert reason is None


def test_component_identity_is_detected_from_class_name() -> None:
    tree, error = module.parse_python("class ZBotAdvisor:\n    pass\n", Path("advisor.py"))
    assert error is None
    result = module.component_affiliation(Path("advisor.py"), tree, "class zbotadvisor: pass")
    assert "ZBot" in result


def test_generic_environment_variable_is_not_sensitive() -> None:
    tree, error = module.parse_python(
        "import os\nclass LiCo:\n    root=os.getenv('Z_DATA_ROOT')\n",
        Path("lico.py"),
    )
    assert error is None
    order_calls, credentials = module.ast_authority(tree)
    assert not order_calls
    assert not credentials


def test_zbot_is_not_a_team_component() -> None:
    assert "ZBot" not in module.TEAM_COMPONENTS
    assert module.TEAM_COMPONENTS == {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}


def test_ssot_contains_full_scope_and_forward_levels() -> None:
    payload = json.loads(SSOT_PATH.read_text(encoding="utf-8"))
    for component in ("LBot", "MBot", "OBot", "SBot", "ZBot", "ZICO", "LiCo", "Zlice"):
        assert component in payload["scope"]
    assert payload["readiness_levels"]["S1_FORWARD_INTEGRITY"]["lineage_coverage_pct"] == 100.0
    assert payload["readiness_levels"]["S3_INTEGRATED_S_GRADE"]["minimum_new_close_count"] == 300
    assert payload["decision"]["current_s_grade_claim_allowed"] is False


def test_runner_is_read_only_for_runtime() -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "systemctl restart", "systemctl stop", "systemctl start", "systemctl enable",
        "systemctl disable", "systemctl mask", "systemctl unmask", "sed -i",
        "git reset", "git clean", "git checkout", "git switch", "rm -rf",
    )
    for token in forbidden:
        assert token not in text
    assert "cmp -n" in text
    assert "current_s_grade_claim_allowed" in text
