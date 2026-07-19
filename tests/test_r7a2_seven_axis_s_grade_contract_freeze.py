from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import r7a2_seven_axis_s_grade_contract_freeze as m

CONTRACT_PATH = Path(__file__).parents[1] / "backend/contracts/ZOS_R7A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE_v1.json"


def contract():
    return json.loads(CONTRACT_PATH.read_text())


def test_contract_exactly_seven_axes_and_funnel():
    ok, blockers = m.contract_valid(contract())
    assert ok
    assert blockers == []
    assert len(contract()["axes"]) == 7


def test_contract_rejects_axis_loss():
    value = contract()
    value["axes"] = value["axes"][:-1]
    ok, blockers = m.contract_valid(value)
    assert not ok
    assert "AXIS_COUNT_NOT_7" in blockers


def test_contract_rejects_material_funnel_drift():
    value = contract()
    value["material_funnel"]["s_material_min"] = 5
    ok, blockers = m.contract_valid(value)
    assert not ok
    assert "MATERIAL_FUNNEL_MISMATCH" in blockers


def test_find_refs_is_regex_and_deduplicated():
    inventory = {
        "backend/a.py": "class LBot: pass",
        "tests/test_a.py": "LBot",
        "docs/no.txt": "nothing",
    }
    assert m.find_refs(["LBot", "lead_bot"], inventory) == ["backend/a.py", "tests/test_a.py"]


def test_freeze_axes_does_not_claim_s_grade():
    value = contract()
    inventory = {
        "backend/all.py": " ".join(
            pattern
            for axis in value["axes"]
            for component in axis["required_components"]
            for pattern in component["patterns"]
        )
    }
    rows = m.freeze_axes(value, inventory, {"records": []})
    assert len(rows) == 7
    assert all(row["contract_frozen"] is True for row in rows)
    assert all(row["s_grade_promoted"] is False for row in rows)


def test_prior_gate_requires_both_receipts(tmp_path):
    value = contract()
    (tmp_path / "runtime/exact25_edge_v1/r7a1a6c6b_writer_count_contract_correction").mkdir(parents=True)
    (tmp_path / "runtime/exact25_edge_v1/r7a1a6c6c_telegram_contract_lock").mkdir(parents=True)
    (tmp_path / value["prior_receipts"]["c6b"]).write_text(json.dumps({
        "state": "PASS",
        "blocker_count": 0,
        "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE",
    }))
    (tmp_path / value["prior_receipts"]["c6c"]).write_text(json.dumps({
        "result": "PASS_R7A1A6C6C_CLOSED",
        "telegram_contract_pass": True,
        "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE",
    }))
    ok, _, blockers = m.prior_gate(tmp_path, value)
    assert ok
    assert blockers == []
