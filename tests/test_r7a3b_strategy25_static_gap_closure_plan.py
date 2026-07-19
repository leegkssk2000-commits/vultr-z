from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import r7a3b_strategy25_static_gap_closure_plan as m


def contract():
    return {
        "required_evidence": ["implementation", "tests", "source_sha", "trigger", "invalidation", "risk", "cost", "replay", "receipt"],
        "shared_gap_keys": ["cost", "replay", "receipt"],
        "per_strategy_gap_keys": ["implementation", "tests", "source_sha", "trigger", "invalidation", "risk"],
        "next_stage_on_shared_gap": "SHARED",
        "next_stage_on_per_strategy_gap": "PER",
        "next_stage_on_mixed_gap": "MIXED",
        "next_stage_on_no_gap": "A4",
    }


def prior_a3():
    return {
        "official_stage": "R7.A3",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": 25,
        "implementation_count": 25,
        "protected_change_count": 0,
        "runtime_mutation_count": 0,
        "next_stage": "R7.A3B_STRATEGY25_STATIC_GAP_CLOSURE",
    }


def rows(missing_tests=10, shared=True):
    result = []
    for i in range(25):
        missing = []
        if i < missing_tests:
            missing.append("tests")
        if shared:
            missing += ["cost", "replay", "receipt"]
        result.append({
            "strategy_id": f"S{i:02d}",
            "grade": "A" if i >= missing_tests else "B",
            "missing": missing,
            "implementation_refs": [f"backend/strategies/s{i:02d}.py"],
            "test_refs": [] if i < missing_tests else [f"tests/test_s{i:02d}.py"],
        })
    return result


def test_prior_gate():
    assert m.prior_a3_valid(prior_a3(), 25)
    bad = prior_a3()
    bad["implementation_count"] = 24
    assert not m.prior_a3_valid(bad, 25)


def test_duplicate_detection():
    source = rows(0, False)
    source[-1]["strategy_id"] = source[0]["strategy_id"]
    normalized, blockers = m.normalize_strategy_rows(source, 25)
    assert len(normalized) == 24
    assert blockers


def test_mixed_plan():
    plan = m.derive_plan(rows(), contract())
    assert plan["closure_mode"] == "MIXED"
    assert plan["missing_test_count"] == 10
    assert plan["shared_gap_candidates"] == ["cost", "receipt", "replay"]
    assert len(plan["per_strategy_gap_ids"]) == 10


def test_shared_threshold():
    source = rows(0, False)
    for i in range(19):
        source[i]["missing"] = ["receipt"]
    assert m.derive_plan(source, contract())["shared_gap_candidates"] == []
    for i in range(20):
        source[i]["missing"] = ["receipt"]
    assert m.derive_plan(source, contract())["shared_gap_candidates"] == ["receipt"]


def test_no_gap_to_a4():
    plan = m.derive_plan(rows(0, False), contract())
    assert plan["closure_mode"] == "NO_GAP"
    assert plan["next_stage"] == "A4"
