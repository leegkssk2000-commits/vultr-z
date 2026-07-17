from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b1_build_single_owner_plan.py"
SPEC = importlib.util.spec_from_file_location("r73b1", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


CONTRACT = {
    "future_owner": {
        "owner_id": "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER",
        "writer_count": 1,
        "enabled_now": False,
    },
    "rules": {
        "measurement_writer_markers": ["persistent-single-event-writer", "formal_exact5_measurement"],
        "read_only_consumer_markers": ["telegram-pos-adapter", "readonly", "read-only"],
        "legacy_display_markers": ["6c_lock", "surface-writer", "display", "mirror", "history", "view"],
        "static_lock_disposition": "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION",
    },
    "next_stage": "R7.3B2_MINIMAL_ISOLATION_ROLLBACK_PLAN",
}
STATUS = {
    "state": "PASS",
    "blocker_count": 0,
    "cleanup_applied": False,
    "writer_candidate_count": 3,
    "static_lock_count": 2,
}
INVENTORY = {
    "groups": {
        "writer_candidates": [
            {"path": "/etc/systemd/system/q4r3-exact25-persistent-single-event-writer.service", "classification": "ACTIVE_OVERWRITER_CANDIDATE", "active_name_match": True, "hits": []},
            {"path": "/etc/systemd/system/zel-q4r3-telegram-pos-adapter-v2.service", "classification": "CANONICAL_OWNER_CANDIDATE", "active_name_match": True, "hits": []},
            {"path": "/etc/systemd/system/zel-q4r3-surface-writer-single-owner.service", "classification": "ACTIVE_OVERWRITER_CANDIDATE", "active_name_match": True, "hits": []},
        ],
        "static_lock_hits": [
            {"path": "/home/z/z/runtime/telegram_only_6c_lock.json", "classification": "STATIC_DISPLAY_LOCK", "active_name_match": False, "hits": []},
            {"path": "/home/z/z/runtime/view_6c_lock.json", "classification": "STATIC_DISPLAY_LOCK", "active_name_match": False, "hits": []},
        ],
        "active_units": [],
        "active_timers": [],
    }
}


def test_complete_plan_passes() -> None:
    result = module.build(CONTRACT, STATUS, INVENTORY)
    assert result["state"] == "PASS"
    assert result["future_owner_count"] == 1
    assert result["writer_candidate_count"] == 3
    assert result["static_lock_count"] == 2
    dispositions = {item["disposition"] for item in result["writer_candidates"]}
    assert "PRESERVE_MEASUREMENT_WRITER" in dispositions
    assert "PRESERVE_READ_ONLY_CONSUMER" in dispositions
    assert "PLAN_ISOLATION_BEFORE_NEW_EPOCH" in dispositions


def test_static_locks_are_never_promoted() -> None:
    result = module.build(CONTRACT, STATUS, INVENTORY)
    assert all(item["disposition"] == "RETAIN_EVIDENCE_THEN_PLAN_ISOLATION" for item in result["static_locks"])


def test_failed_audit_holds() -> None:
    status = dict(STATUS, state="HOLD", blocker_count=1)
    result = module.build(CONTRACT, status, INVENTORY)
    assert result["state"] == "HOLD"
    assert "R73B0_NOT_PASS" in result["blockers"]


def test_count_mismatch_holds() -> None:
    status = dict(STATUS, writer_candidate_count=9)
    result = module.build(CONTRACT, status, INVENTORY)
    assert result["state"] == "HOLD"
    assert "WRITER_CANDIDATE_COUNT_MISMATCH" in result["blockers"]


def test_future_owner_must_remain_disabled() -> None:
    contract = dict(CONTRACT)
    contract["future_owner"] = dict(CONTRACT["future_owner"], enabled_now=True)
    result = module.build(contract, STATUS, INVENTORY)
    assert result["state"] == "HOLD"
    assert "FUTURE_OWNER_CONTRACT_INVALID" in result["blockers"]


def test_duplicate_paths_are_deduplicated() -> None:
    inventory = {"groups": dict(INVENTORY["groups"])}
    inventory["groups"]["writer_candidates"] = INVENTORY["groups"]["writer_candidates"] + [INVENTORY["groups"]["writer_candidates"][0]]
    status = dict(STATUS)
    result = module.build(CONTRACT, status, inventory)
    assert result["writer_candidate_count"] == 3
