from __future__ import annotations

import importlib.util
from pathlib import Path

TARGET = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4s_explicit_binding_plan.py"
SPEC = importlib.util.spec_from_file_location("r73b4s", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CONTRACT = {
    "snapshot": "/tmp/shadow/latest.json",
    "planned_apply_method": "APPLY",
    "planned_rollback_method": "ROLLBACK",
    "next_stage": "R7.3B4T_EXPLICIT_BINDING_CANARY",
}
SNAPSHOT = {
    "owner_id": "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER",
    "state": "PREBIND",
    "sample_count": 0,
    "closed_count": 0,
    "formal_ledger_bound": False,
    "snapshot_sha256": "a" * 64,
}


def records() -> list[dict[str, object]]:
    return [
        {
            "name": "ALIMI_VIEW", "active": "active", "source_path": "/x/alimi.py",
            "rollback_ready": True, "current_snapshot_bound": False,
            "current_formal_ledger_bound": False,
            "required_anchor_any": ["/api/view_contract_latest.json", "view_contract_latest.json"],
            "resolved_anchor_any_count": 1,
            "source_anchor_lines": {"/api/view_contract_latest.json": [10]},
        },
        {
            "name": "TELEGRAM_COMMANDS", "active": "active", "source_path": "/x/telegram.py",
            "rollback_ready": True, "current_snapshot_bound": False,
            "current_formal_ledger_bound": False,
            "required_command_count": 3, "resolved_command_count": 3,
            "source_anchor_lines": {"/pos": [20], "/pnl": [30], "/view": [40]},
        },
    ]


def test_complete_readonly_plan_passes() -> None:
    result = module.build(CONTRACT, SNAPSHOT, records())
    assert result["state"] == "PASS"
    assert result["consumer_count"] == 2
    assert result["source_resolved_count"] == 2
    assert result["rollback_ready_count"] == 2
    assert result["current_snapshot_binding_count"] == 0
    assert result["mutation_count"] == 0


def test_historical_ledger_binding_holds() -> None:
    rows = records()
    rows[1]["current_formal_ledger_bound"] = True
    result = module.build(CONTRACT, SNAPSHOT, rows)
    assert result["state"] == "HOLD"
    assert "FORMAL_LEDGER_CONSUMER_BINDING_FOUND" in result["blockers"]


def test_missing_telegram_command_holds() -> None:
    rows = records()
    rows[1]["resolved_command_count"] = 2
    result = module.build(CONTRACT, SNAPSHOT, rows)
    assert result["state"] == "HOLD"
    assert "TELEGRAM_COMMAND_BINDING_INCOMPLETE" in result["blockers"]


def test_missing_alimi_contract_api_anchor_holds() -> None:
    rows = records()
    rows[0]["resolved_anchor_any_count"] = 0
    result = module.build(CONTRACT, SNAPSHOT, rows)
    assert result["state"] == "HOLD"
    assert "ALIMI_VIEW_CONTRACT_API_ANCHOR_UNRESOLVED" in result["blockers"]


def test_nonzero_snapshot_holds() -> None:
    snapshot = dict(SNAPSHOT, closed_count=1)
    result = module.build(CONTRACT, snapshot, records())
    assert result["state"] == "HOLD"
    assert "SNAPSHOT_ZERO_EPOCH_INVALID" in result["blockers"]
