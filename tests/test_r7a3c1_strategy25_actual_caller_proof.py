from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "r7a3c1_strategy25_actual_caller_proof.py"
spec = importlib.util.spec_from_file_location("r7a3c1", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def strategy_rows():
    rows = []
    for i in range(25):
        sid = f"S{i:02d}"
        rows.append({
            "strategy_id": sid,
            "implementation_refs": ["backend/strategy_router.py", f"backend/strategies/{sid}.py"],
            "test_refs": [] if i >= 15 else ["tests/test_existing.py"],
            "missing": ["receipt", "replay"] + (["tests"] if i >= 15 else []),
            "source_shas": {f"backend/strategies/{sid}.py": f"sha{i}"},
        })
    return rows


def test_prior_a3b_valid_mixed():
    value = {
        "official_stage": "R7.A3B",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": 25,
        "protected_change_count": 0,
        "runtime_mutation_count": 0,
        "next_stage": "R7.A3C_STRATEGY25_MIXED_STATIC_CLOSURE",
        "plan": {
            "closure_mode": "MIXED",
            "missing_test_count": 10,
            "shared_gap_candidates": ["receipt", "replay"],
        },
    }
    assert mod.prior_a3b_valid(value, 25)


def test_ast_shape_detects_executable_surface():
    shape = mod.ast_shape("def evaluate(x):\n    return x\n")
    assert shape["parse_ok"] is True
    assert shape["functions"] == ["evaluate"]


def test_normalize_rows_preserves_25_unique():
    rows, blockers = mod.normalize_rows({"strategies": strategy_rows()}, 25)
    assert len(rows) == 25
    assert blockers == []


def test_derive_patch_targets_requires_adapter_without_proven_caller():
    a3b = {"plan": {"missing_test_strategy_ids": [f"S{i:02d}" for i in range(15, 25)]}}
    callers = [{
        "path": "backend/strategy_router.py",
        "actual_shared_caller_candidate": False,
        "strategy_coverage_count": 25,
    }]
    plan = mod.derive_patch_targets(strategy_rows(), callers, [], a3b)
    assert plan["classification"] == "SHARED_ADAPTER_AND_TEST_CLOSURE_REQUIRED"
    assert plan["missing_test_count"] == 10
    assert plan["patch_boundaries"]["strategy_logic_edit_allowed"] is False


def test_derive_patch_targets_existing_binding_needs_tests():
    a3b = {"plan": {"missing_test_strategy_ids": ["S24"]}}
    callers = [{
        "path": "backend/strategy_router.py",
        "actual_shared_caller_candidate": True,
        "strategy_coverage_count": 25,
    }]
    plan = mod.derive_patch_targets(strategy_rows(), callers, [], a3b)
    assert plan["classification"] == "TEST_CLOSURE_REQUIRED"
    assert plan["next_stage"] == "R7.A3C2_STRATEGY25_REAL_ENTRYPOINT_TEST_CLOSURE"


def test_marker_score_is_explicit():
    score, found = mod.marker_score("strategy_receipt event_id source_sha", mod.RECEIPT_MARKERS)
    assert score == 4
    assert found == ["event_id", "receipt", "source_sha", "strategy_receipt"]
