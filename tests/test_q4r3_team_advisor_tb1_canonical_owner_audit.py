from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_tb1_canonical_owner_audit.py"

spec = importlib.util.spec_from_file_location("tb1", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_component_taxonomy_is_complete() -> None:
    assert set(module.CORE_COMPONENTS) == {"LBot", "MBot", "OBot", "SBot", "ZBot", "ZICO", "LiCo", "Zlice"}
    for lane in ("Alpha", "Beta", "Gamma", "Delta"):
        assert lane in module.COMPONENTS


def test_secret_redaction() -> None:
    text = module.sanitize("api_key=abcdef secret:xyz ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert "abcdef" not in text
    assert "xyz" not in text
    assert "ghp_" not in text


def test_matrix_prefers_canonical_definition() -> None:
    files = [
        {
            "path": "/x/lbot_legacy.py",
            "sha256": "a",
            "components": ["LBot"],
            "definition_signal": True,
            "caller_signal": False,
            "authority_signal": False,
            "canonical_signal": False,
            "stale_signal": True,
        },
        {
            "path": "/x/lbot_canonical_owner.py",
            "sha256": "b",
            "components": ["LBot"],
            "definition_signal": True,
            "caller_signal": True,
            "authority_signal": False,
            "canonical_signal": True,
            "stale_signal": False,
        },
    ]
    matrix = module.build_matrix(files, [])
    assert matrix["LBot"]["top_candidates"][0]["path"].endswith("lbot_canonical_owner.py")
    assert matrix["LBot"]["confidence"] in {"MEDIUM", "HIGH"}


def test_audit_output_has_no_activation_authority(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "tools").mkdir(parents=True)
    (root / "tools/lbot_canonical.py").write_text("class LBotCanonicalOwner: pass\n", encoding="utf-8")
    payload = module.audit(root)
    policy = payload["policy"]
    assert policy["observer_only"] is True
    assert policy["team_advisor_binding_enabled"] is False
    assert policy["paper_enabled"] is False
    assert policy["live_enabled"] is False
    assert policy["order_enabled"] is False
    assert policy["order_authority"] == "blocked"
    assert policy["execution_authority"] == "none"


def test_source_contains_no_mutating_systemctl() -> None:
    text = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        'systemctl", "restart',
        'systemctl", "stop',
        'systemctl", "start',
        'systemctl", "enable',
        'systemctl", "disable',
        'systemctl", "unmask',
    ):
        assert forbidden not in text
