from __future__ import annotations

import importlib.util
from pathlib import Path

TARGET = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4r_shadow_snapshot_prebind.py"
SPEC = importlib.util.spec_from_file_location("r73b4r", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

CONTRACT = {
    "future_owner": {
        "owner_id": "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER",
        "planned_unit": "q4r3-exact25-shadow-aggregate-snapshot-writer.service",
        "writer_count": 1,
        "enabled_now": False,
    },
    "epoch": {"epoch_id": "q4r3.exact25.shadow.pending", "sample_count": 0, "closed_count": 0},
    "next_stage": "R7.3B4S_ALIMI_TELEGRAM_EXPLICIT_BINDING_PLAN",
}
PARENT = {"state": "PASS", "cleanup_applied": True}
VALIDATION = {"state": "PASS", "receipt_verified": True}


def test_zero_epoch_snapshot_passes() -> None:
    snapshot, status = module.build(CONTRACT, PARENT, VALIDATION)
    assert status["state"] == "PASS"
    assert snapshot["closed_count"] == 0
    assert snapshot["net_r"] == 0.0
    assert snapshot["formal_ledger_bound"] is False
    assert snapshot["runtime_active"] is False
    assert len(snapshot["snapshot_sha256"]) == 64


def test_parent_failure_holds() -> None:
    _, status = module.build(CONTRACT, {"state": "HOLD", "cleanup_applied": False}, VALIDATION)
    assert status["state"] == "HOLD"
    assert "R73B3_STATUS_INVALID" in status["blockers"]


def test_nonzero_epoch_holds() -> None:
    contract = dict(CONTRACT)
    contract["epoch"] = dict(CONTRACT["epoch"], closed_count=1)
    _, status = module.build(contract, PARENT, VALIDATION)
    assert status["state"] == "HOLD"
    assert "INITIAL_EPOCH_NOT_ZERO" in status["blockers"]
