from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/q4r3_team_advisor_tb11_owner_narrowing_audit_fixed.py"

spec = importlib.util.spec_from_file_location("tb11_fixed", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fixed_classifier_is_bound_into_original_module() -> None:
    assert module.classify_kind is module._fixed_classify_kind
    assert module._original.classify_kind is module._fixed_classify_kind
    assert module.classify_kind.__module__ == "tb11_fixed"


def test_backup_restore_rollback_paths_are_excluded(tmp_path: Path) -> None:
    for name in (
        ".backup_restore_v23/file.py",
        "_LIVE_BACKUP_20260531/file.py",
        "_LOCKED_BASELINE_20260531/file.py",
        "_restore_backup_app/file.py",
        "_rollback_before_fix/file.py",
        "archive/file.py",
        "dist/file.js",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("LBot canonical owner", encoding="utf-8")
        assert module.contaminated_path(path) is True


def test_canonical_backend_file_is_not_excluded(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/lbot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text("class LBotCore: pass", encoding="utf-8")
    assert module.contaminated_path(path) is False


def test_policy_flags_do_not_count_as_direct_authority(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/lbot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "class LBotCore:\n    paper_enabled = False\n    live_enabled = False\n    order_enabled = False\n",
        encoding="utf-8",
    )
    row = module.analyze_file(path)
    assert row is not None
    assert row["policy_reference_signal"] is True
    assert row["direct_order_signal"] is False
    assert row["private_credential_signal"] is False


def test_direct_order_code_is_semantic_authority(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/lbot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "class LBotCore:\n    def act(self, exchange):\n        return exchange.create_order('BTC/USDT', 'market', 'buy', 1)\n",
        encoding="utf-8",
    )
    row = module.analyze_file(path)
    assert row is not None
    assert row["direct_order_signal"] is True


def test_credential_name_reference_is_not_private_execution(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/lico_core.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "class LiCoCore:\n    api_key = None\n    secret = None\n",
        encoding="utf-8",
    )
    row = module.analyze_file(path)
    assert row is not None
    assert row["private_credential_reference_signal"] is True
    assert row["private_credential_access_signal"] is False
    authority = module.authority_matrix([row], [])
    assert authority["direct_execution_candidate_count"] == 0
    assert authority["credential_reference_only_count"] == 1


def test_environment_credential_access_is_private_execution(tmp_path: Path) -> None:
    path = tmp_path / "backend/engine/zbot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "import os\nclass ZBotCore:\n    api_key = os.environ.get('BINGX_API_KEY')\n",
        encoding="utf-8",
    )
    row = module.analyze_file(path)
    assert row is not None
    assert row["kind"] == "runtime_definition"
    assert row["private_credential_access_signal"] is True
    authority = module.authority_matrix([row], [])
    assert authority["direct_execution_candidate_count"] == 1


def test_pytest_temp_parent_does_not_demote_runtime_owner(tmp_path: Path) -> None:
    parent = tmp_path / "test_environment_credential_ac0"
    path = parent / "backend/engine/zbot_core.py"
    path.parent.mkdir(parents=True)
    path.write_text("class ZBotCore: pass", encoding="utf-8")
    row = module.analyze_file(path)
    assert row is not None
    assert row["kind"] == "runtime_definition"


def test_all_support_prefixes_in_ancestor_do_not_demote_runtime_owner(tmp_path: Path) -> None:
    prefixes = ("test", "verify", "apply", "install", "bootstrap", "run", "audit", "probe", "smoke", "check")
    for prefix in prefixes:
        path = tmp_path / f"{prefix}_temporary_parent" / "backend/engine/zbot_core.py"
        path.parent.mkdir(parents=True)
        path.write_text("class ZBotCore: pass", encoding="utf-8")
        row = module.analyze_file(path)
        assert row is not None, prefix
        assert row["kind"] == "runtime_definition", prefix


def test_actual_support_basename_is_support_surface(tmp_path: Path) -> None:
    for name in ("verify_zbot_contract.py", "run_zbot_probe.py", "audit_zbot_owner.py"):
        path = tmp_path / "backend/engine" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("class ZBotCore: pass", encoding="utf-8")
        row = module.analyze_file(path)
        assert row is not None
        assert row["kind"] == "support_verifier_installer", name


def test_exact_support_directory_is_support_surface(tmp_path: Path) -> None:
    path = tmp_path / "backend/scripts/zbot_contract.py"
    path.parent.mkdir(parents=True)
    path.write_text("class ZBotCore: pass", encoding="utf-8")
    row = module.analyze_file(path)
    assert row is not None
    assert row["kind"] == "support_verifier_installer"


def test_support_verifier_is_not_owner(tmp_path: Path) -> None:
    path = tmp_path / "backend/scripts/verify_zlice_contract.py"
    path.parent.mkdir(parents=True)
    path.write_text("def verify_zlice(): return True", encoding="utf-8")
    row = module.analyze_file(path)
    assert row is not None
    assert row["kind"] == "support_verifier_installer"
    assert module.score("Zlice", row, set()) < 10
    matrix = module.build_matrix([row], [])
    assert matrix["Zlice"]["unique_candidate_count"] == 0
    assert matrix["Zlice"]["excluded_support_surface_count"] == 1


def test_same_sha_candidates_are_deduplicated() -> None:
    rows = [
        {"path": "/a/lbot_core.py", "sha256": "x", "score": 20},
        {"path": "/b/lbot_core.py", "sha256": "x", "score": 18},
        {"path": "/c/lbot_core.py", "sha256": "y", "score": 17},
    ]
    result = module.dedupe_candidates(rows)
    assert len(result) == 2
    assert result[0]["path"] == "/a/lbot_core.py"
    assert result[0]["same_sha_paths"] == ["/b/lbot_core.py"]


def test_raw_systemd_parser_does_not_truncate_fields() -> None:
    long_exec = "/home/z/z/" + "a" * 1000
    fields = module.parse_show(f"ActiveState=active\nExecStart={long_exec}\n")
    assert fields["ActiveState"] == "active"
    assert len(fields["ExecStart"]) > 900
