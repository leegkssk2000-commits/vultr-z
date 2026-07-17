from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b1_build_single_owner_plan_v2.py"
SPEC = importlib.util.spec_from_file_location("r73b1_v2", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CONTRACT = {
    "future_owner": {"writer_count": 1, "enabled_now": False},
    "rules": {
        "measurement_writer_markers": ["persistent-single-event-writer"],
        "read_only_consumer_markers": ["telegram-pos-adapter", "readonly"],
        "legacy_display_markers": ["surface-writer", "display-mirror", "6c_lock"],
        "static_lock_disposition": "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION",
    },
    "next_stage": "R7.3B2_MINIMAL_ISOLATION_ROLLBACK_PLAN",
}


def rec(path: str, classification: str = "CANONICAL_OWNER_CANDIDATE") -> dict[str, object]:
    return {"path": path, "classification": classification, "active_name_match": True, "hits": []}


def inventory() -> dict[str, object]:
    candidates = [
        rec("/etc/systemd/system/zico-ceo-canonical-adapter.service"),
        rec("/etc/systemd/system/multi-user.target.wants/zico-ceo-canonical-adapter.service"),
        rec("/etc/systemd/system/q4r3-exact25-shadow-producer.service"),
        rec("/etc/systemd/system/multi-user.target.wants/q4r3-exact25-shadow-producer.service"),
        rec("/etc/systemd/system/zel-alimi-paper-control-api-w208.service"),
        rec("/etc/systemd/system/multi-user.target.wants/zel-alimi-paper-control-api-w208.service"),
        rec("/etc/systemd/system/q4r3-exact25-persistent-single-event-writer.service", "ACTIVE_OVERWRITER_CANDIDATE"),
        rec("/etc/systemd/system/multi-user.target.wants/q4r3-exact25-persistent-single-event-writer.service", "ACTIVE_OVERWRITER_CANDIDATE"),
        rec("/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service"),
    ]
    locks = [
        rec("/etc/systemd/system/zel-s4g8r7f8t-telegram-6c-lock-only.service", "STATIC_DISPLAY_LOCK"),
        rec("/etc/systemd/system/zel-s4g8r7f8t-telegram-6c-lock-only.timer", "STATIC_DISPLAY_LOCK"),
    ]
    return {"groups": {"writer_candidates": candidates, "static_lock_hits": locks, "active_units": [], "active_timers": []}}


def test_symlinks_are_not_separate_units() -> None:
    status = {"state": "PASS", "blocker_count": 0, "cleanup_applied": False, "writer_candidate_count": 9, "static_lock_count": 2}
    result = module.build(CONTRACT, status, inventory())
    assert result["state"] == "PASS"
    assert result["raw_writer_candidate_count"] == 9
    assert result["canonical_writer_unit_count"] == 5


def test_core_runtime_is_preserved() -> None:
    status = {"state": "PASS", "blocker_count": 0, "cleanup_applied": False, "writer_candidate_count": 9, "static_lock_count": 2}
    result = module.build(CONTRACT, status, inventory())
    by_unit = {item["unit"]: item["disposition"] for item in result["writer_candidates"]}
    assert by_unit["zico-ceo-canonical-adapter.service"] == "PRESERVE_CORE_RUNTIME"
    assert by_unit["q4r3-exact25-shadow-producer.service"] == "PRESERVE_CORE_RUNTIME"
    assert by_unit["zel-alimi-paper-control-api-w208.service"] == "PRESERVE_CORE_RUNTIME"
    assert result["planned_isolation_count"] == 0


def test_measurement_and_readonly_surfaces_are_preserved() -> None:
    status = {"state": "PASS", "blocker_count": 0, "cleanup_applied": False, "writer_candidate_count": 9, "static_lock_count": 2}
    result = module.build(CONTRACT, status, inventory())
    by_unit = {item["unit"]: item["disposition"] for item in result["writer_candidates"]}
    assert by_unit["q4r3-exact25-persistent-single-event-writer.service"] == "PRESERVE_MEASUREMENT_WRITER"
    assert by_unit["zel-q4r3-telegram-pos-adapter-v2.service"] == "PRESERVE_READ_ONLY_CONSUMER"
