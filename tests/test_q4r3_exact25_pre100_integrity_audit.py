from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_pre100_integrity_audit.py"
spec = importlib.util.spec_from_file_location("pre100_integrity", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def observer(**extra):
    value = {
        "state": "PASS",
        "observer_only": True,
        "strategy_modified": False,
        "trade_method_modified": False,
        "skill_registry_modified": False,
        "producer_modified": False,
        "writer_modified": False,
        "formal_ledger_modified": False,
    }
    value.update(extra)
    return value


def base_payloads():
    static_audit = {
        "state": "PASS",
        "verdict": "ACTIVE_IMPORT_CALL_SURFACE_PASS_TRIGGER_LINEAGE_NOT_YET_PROVEN",
        "strategy_import_pass_count": 25,
        "strategy_empty_call_pass_count": 25,
        "method_declaration_count": 6,
        "resolver_pass_count": 18,
        "compatibility_matrix_rows": 2700,
    }
    activation = {
        "activated_at": "2026-07-14T18:00:00+00:00",
        "baseline_ledger_rows": 1,
        "baseline_position_ids": ["base-position"],
        "historical_backfill_allowed": False,
    }
    ledger_rows = [
        {"event_id": "close-base", "position_id": "base-position"},
        {"event_id": "close-1", "position_id": "position-1"},
    ]
    events = [
        {
            "event_id": "trigger-1",
            "event_type": "skill_triggered",
            "event_ts": "2026-07-14T18:01:00+00:00",
            "position_id": "position-1",
        },
        {
            "event_id": "join-1",
            "event_type": "close_outcome_joined",
            "event_ts": "2026-07-14T18:02:00+00:00",
            "position_id": "position-1",
            "close_event_id": "close-1",
        },
    ]
    trigger_status = observer(
        skill_triggered_count=1,
        skill_blocked_count=0,
        close_outcome_joined_count=1,
    )
    coverage = {"matrix_rows": 2700}
    projection_status = observer(
        profile_count=6,
        total_trigger_count=1,
        total_blocked_count=0,
        total_outcome_join_count=1,
    )
    pair_status = observer(
        event_count=2,
        trigger_count=1,
        blocked_count=0,
        close_join_event_count=1,
        exact_pair_count=1,
        pending_close_count=0,
    )
    pairs_report = {
        "pairs": [
            {
                "pair_state": "EXACT_CLOSE_JOINED",
                "exact_join": True,
                "position_id": "position-1",
            }
        ]
    }
    risk_status = observer(scenario_count=12, exact_pair_count=1)
    risk_grid = {"scenario_count": 12, "exact_pair_count": 1, "missing_risk_fields": []}
    scoreboard_status = observer(
        method_count=6,
        methods_with_trigger=1,
        methods_with_outcome=1,
    )
    scoreboard = {
        "rows": [
            {"method_id": "m1", "trigger_count": 1, "outcome_join_count": 1},
            {"method_id": "m2", "trigger_count": 0, "outcome_join_count": 0},
            {"method_id": "m3", "trigger_count": 0, "outcome_join_count": 0},
            {"method_id": "m4", "trigger_count": 0, "outcome_join_count": 0},
            {"method_id": "m5", "trigger_count": 0, "outcome_join_count": 0},
            {"method_id": "m6", "trigger_count": 0, "outcome_join_count": 0},
        ]
    }
    checkpoint = observer(
        target_closed_count=100,
        current_closed_count=2,
        post_activation_closed_count=1,
        activation_baseline_ledger_rows=1,
    )
    return {
        "static_audit": static_audit,
        "storage": {"state": "PASS", "verdict": "STORAGE_REGROWTH_GUARD_HEALTHY"},
        "activation": activation,
        "ledger_rows": ledger_rows,
        "ledger_errors": [],
        "events": events,
        "event_errors": [],
        "open_positions": [],
        "trigger_status": trigger_status,
        "coverage": coverage,
        "projection_status": projection_status,
        "projection": {},
        "pair_status": pair_status,
        "pairs_report": pairs_report,
        "risk_status": risk_status,
        "risk_grid": risk_grid,
        "scoreboard_status": scoreboard_status,
        "scoreboard": scoreboard,
        "checkpoint": checkpoint,
    }


def test_clean_pipeline_passes() -> None:
    status, violations, fix_queue = module.audit(**base_payloads())
    assert status["state"] == "PASS"
    assert status["verdict"] == "PRE100_INTEGRITY_PASS_ACCUMULATING"
    assert status["lineage_coverage_pct"] == 100.0
    assert violations["count"] == 0
    assert fix_queue["state"] == "CLEAR"


def test_closed_position_without_lineage_is_critical() -> None:
    payloads = base_payloads()
    payloads["events"] = []
    payloads["trigger_status"].update(
        skill_triggered_count=0,
        skill_blocked_count=0,
        close_outcome_joined_count=0,
    )
    payloads["projection_status"].update(
        total_trigger_count=0,
        total_blocked_count=0,
        total_outcome_join_count=0,
    )
    payloads["pair_status"].update(
        event_count=0,
        trigger_count=0,
        blocked_count=0,
        close_join_event_count=0,
        exact_pair_count=0,
        pending_close_count=0,
    )
    payloads["pairs_report"] = {"pairs": []}
    payloads["risk_status"]["exact_pair_count"] = 0
    payloads["scoreboard_status"].update(methods_with_trigger=0, methods_with_outcome=0)
    for row in payloads["scoreboard"]["rows"]:
        row.update(trigger_count=0, outcome_join_count=0)

    status, violations, fix_queue = module.audit(**payloads)
    assert status["state"] == "HOLD"
    assert status["verdict"] == "PRE100_INTEGRITY_CRITICAL_GAP"
    assert status["uncovered_close_count"] == 1
    assert any(row["code"] == "POST_ACTIVATION_CLOSE_WITHOUT_SKILL_LINEAGE" for row in violations["violations"])
    assert fix_queue["state"] == "OPEN"


def test_open_without_lineage_is_major_hold() -> None:
    payloads = base_payloads()
    payloads["open_positions"] = [
        {
            "position_id": "position-open",
            "entry_ts": "2026-07-14T18:10:00+00:00",
        }
    ]
    status, violations, _ = module.audit(**payloads)
    assert status["state"] == "HOLD"
    assert status["major_count"] == 1
    assert any(row["code"] == "OPEN_POSITION_WITHOUT_SKILL_LINEAGE_EVENT" for row in violations["violations"])


def test_duplicate_close_event_is_critical() -> None:
    payloads = base_payloads()
    payloads["ledger_rows"].append({"event_id": "close-1", "position_id": "position-2"})
    payloads["checkpoint"]["current_closed_count"] = 3
    payloads["checkpoint"]["post_activation_closed_count"] = 2
    status, violations, _ = module.audit(**payloads)
    assert status["state"] == "HOLD"
    assert status["duplicate_post_close_event_id_count"] == 1
    assert any(row["code"] == "POST_ACTIVATION_DUPLICATE_CLOSE_EVENT_ID" for row in violations["violations"])
