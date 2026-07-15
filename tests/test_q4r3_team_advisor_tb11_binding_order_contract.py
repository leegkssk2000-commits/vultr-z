from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_tb11_owner_narrowing_audit_fixed.py"

spec = importlib.util.spec_from_file_location("tb11_binding_contract", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_original_module_global_points_to_fixed_classifier() -> None:
    assert module.classify_kind is module._fixed_classify_kind
    assert module._original.classify_kind is module._fixed_classify_kind


def test_parent_prefix_matrix_is_never_support(tmp_path: Path) -> None:
    for prefix in ("test", "verify", "apply", "install", "bootstrap", "run", "audit", "probe", "smoke", "check"):
        path = tmp_path / f"{prefix}_parent" / "backend/engine/zbot_core.py"
        path.parent.mkdir(parents=True)
        path.write_text("class ZBotCore: pass", encoding="utf-8")
        row = module.analyze_file(path)
        assert row is not None, prefix
        assert row["kind"] == "runtime_definition", prefix


def test_only_exact_support_directory_or_final_basename_is_support(tmp_path: Path) -> None:
    support_dir = tmp_path / "backend/scripts/zbot_core.py"
    support_dir.parent.mkdir(parents=True)
    support_dir.write_text("class ZBotCore: pass", encoding="utf-8")
    assert module.analyze_file(support_dir)["kind"] == "support_verifier_installer"

    support_file = tmp_path / "backend/engine/verify_zbot_core.py"
    support_file.parent.mkdir(parents=True, exist_ok=True)
    support_file.write_text("class ZBotCore: pass", encoding="utf-8")
    assert module.analyze_file(support_file)["kind"] == "support_verifier_installer"
