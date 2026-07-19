from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import r7a3_strategy25_s_grade_audit as m


def valid_a2():
    return {
        "official_stage": "R7.A2",
        "state": "PASS",
        "blocker_count": 0,
        "axis_count": 7,
        "axis_contracts_frozen": 7,
        "protected_change_count": 0,
        "runtime_mutation_count": 0,
        "next_stage": "R7.A3_STRATEGY25_S_GRADE",
    }


def test_prior_a2_valid_exact():
    assert m.prior_a2_valid(valid_a2())
    bad = valid_a2()
    bad["axis_contracts_frozen"] = 6
    assert not m.prior_a2_valid(bad)


def test_list_ids_mixed():
    value = ["A", {"strategy_id": "B"}, {"id": "C"}, {"name": "D"}, {"x": "E"}]
    assert m.list_ids(value) == ["A", "B", "C", "D"]


def test_path_kind():
    assert m.path_kind("backend/strategies/a.py") == "production"
    assert m.path_kind("backend/contracts/a.json") == "contract"
    assert m.path_kind("tests/test_a.py") == "test"
    assert m.path_kind("README.md") == "contract"


def test_grade_static_s_ready():
    refs = ["backend/strategies/a.py", "tests/test_a.py"]
    texts = {
        refs[0]: "strategy_id source_sha event_id feature_ts signal invalidation trigger risk fee replay",
        refs[1]: "test replay",
    }
    tree = {refs[0]: {"blob_sha": "abc"}, refs[1]: {"blob_sha": "def"}}
    row = m.grade_strategy("STRAT_A", refs, texts, tree)
    assert row["grade"] == "S_STATIC_READY"
    assert row["static_s_ready"] is True


def test_grade_a_when_cost_replay_receipt_missing():
    refs = ["backend/strategies/a.py", "tests/test_a.py"]
    texts = {refs[0]: "trigger invalidation risk", refs[1]: "test"}
    tree = {refs[0]: {"blob_sha": "abc"}, refs[1]: {"blob_sha": "def"}}
    row = m.grade_strategy("A", refs, texts, tree)
    assert row["grade"] == "A"
    assert "cost" in row["missing"]


def test_grade_b_c_d():
    tree = {"backend/strategies/a.py": {"blob_sha": "abc"}}
    b = m.grade_strategy("A", ["backend/strategies/a.py"], {"backend/strategies/a.py": "signal"}, tree)
    c = m.grade_strategy("B", ["backend/contracts/b.json"], {"backend/contracts/b.json": "strategy"}, {})
    d = m.grade_strategy("C", [], {}, {})
    assert b["grade"] == "B"
    assert c["grade"] == "C"
    assert d["grade"] == "D"
