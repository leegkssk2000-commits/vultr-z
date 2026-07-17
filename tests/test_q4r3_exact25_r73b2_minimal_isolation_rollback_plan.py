from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b2_build_minimal_isolation_rollback_plan.py"
SPEC = importlib.util.spec_from_file_location("r73b2", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture(tmp_path: Path):
    service = tmp_path / "zel-s4g8r7f8t-telegram-6c-lock-only.service"
    timer = tmp_path / "zel-s4g8r7f8t-telegram-6c-lock-only.timer"
    service.write_text("[Unit]\nDescription=legacy lock\n", encoding="utf-8")
    timer.write_text("[Timer]\nOnBootSec=1\n", encoding="utf-8")
    contract = {
        "dependencies": {
            "r73b1_state": "PASS",
            "r73b1_blocker_count": 0,
            "r73b1_cleanup_applied": False,
            "raw_writer_candidate_count": 9,
            "canonical_writer_unit_count": 5,
            "static_lock_count": 2,
        },
        "required_preserved_dispositions": [
            "PRESERVE_CORE_RUNTIME",
            "PRESERVE_MEASUREMENT_WRITER",
            "PRESERVE_READ_ONLY_CONSUMER",
        ],
        "target_disposition": "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION",
        "planned_method": "COPY_HASH_VERIFY_THEN_RENAME_OUT_OF_SYSTEMD_PATH",
        "rollback_method": "RESTORE_ORIGINAL_PATH_VERIFY_HASH_DAEMON_RELOAD",
        "quarantine_root": str(tmp_path / "quarantine"),
        "pass_conditions": {
            "target_count": 2,
            "protected_unit_count": 5,
            "target_protected_overlap_count": 0,
            "missing_target_count": 0,
            "hash_ready_count": 2,
            "rollback_ready_count": 2,
        },
        "next_stage": "R7.3B3_STATIC_LOCK_QUARANTINE_CANARY",
    }
    status = {
        "state": "PASS",
        "blocker_count": 0,
        "cleanup_applied": False,
        "raw_writer_candidate_count": 9,
        "canonical_writer_unit_count": 5,
        "static_lock_count": 2,
    }
    disposition = {
        **status,
        "writer_candidates": [
            {"unit": "zico.service", "path": "/x/zico", "disposition": "PRESERVE_CORE_RUNTIME"},
            {"unit": "producer.service", "path": "/x/producer", "disposition": "PRESERVE_CORE_RUNTIME"},
            {"unit": "control.service", "path": "/x/control", "disposition": "PRESERVE_CORE_RUNTIME"},
            {"unit": "writer.service", "path": "/x/writer", "disposition": "PRESERVE_MEASUREMENT_WRITER"},
            {"unit": "telegram.service", "path": "/x/telegram", "disposition": "PRESERVE_READ_ONLY_CONSUMER"},
        ],
        "static_locks": [
            {"unit": service.name, "path": str(service), "disposition": "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION"},
            {"unit": timer.name, "path": str(timer), "disposition": "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION"},
        ],
    }
    return contract, status, disposition, service, timer


def probe(unit: str, mode: str) -> str:
    return "inactive" if mode == "is-active" else "disabled"


def test_complete_plan_passes(tmp_path: Path) -> None:
    contract, status, disposition, _, _ = fixture(tmp_path)
    result = module.build(contract, status, disposition, probe=probe)
    assert result["state"] == "PASS"
    assert result["protected_unit_count"] == 5
    assert result["target_count"] == 2
    assert result["hash_ready_count"] == 2
    assert result["rollback_ready_count"] == 2
    assert result["mutation_count"] == 0


def test_missing_target_holds(tmp_path: Path) -> None:
    contract, status, disposition, service, _ = fixture(tmp_path)
    service.unlink()
    result = module.build(contract, status, disposition, probe=probe)
    assert result["state"] == "HOLD"
    assert "TARGET_FILE_MISSING" in result["blockers"]


def test_protected_overlap_holds(tmp_path: Path) -> None:
    contract, status, disposition, service, _ = fixture(tmp_path)
    disposition["writer_candidates"][0]["unit"] = service.name
    result = module.build(contract, status, disposition, probe=probe)
    assert result["state"] == "HOLD"
    assert "TARGET_PROTECTED_OVERLAP" in result["blockers"]


def test_dependency_count_mismatch_holds(tmp_path: Path) -> None:
    contract, status, disposition, _, _ = fixture(tmp_path)
    status["canonical_writer_unit_count"] = 4
    result = module.build(contract, status, disposition, probe=probe)
    assert result["state"] == "HOLD"
    assert "R73B1_CANONICAL_WRITER_UNIT_COUNT_MISMATCH" in result["blockers"]
