from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).parents[1] / "tools/r7a4d2_strategy_role_authority_closure.py"
    spec = importlib.util.spec_from_file_location("role_closure", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_registry(module):
    entries = []
    for index in range(25):
        strategy_id = (
            module.TARGET_IDS[index]
            if index < len(module.TARGET_IDS)
            else f"other_{index}"
        )
        entries.append(
            {
                "strategy_id": strategy_id,
                "active_allowed": False,
                "fail_closed": True,
                "config_ref": f"config#/{strategy_id}",
                "canonical_engine": {
                    "implementation_path": f"backend/strategies/{strategy_id}.py",
                    "source_sha256": f"sha-{strategy_id}",
                    "callable": "Strategy.decide",
                },
            }
        )
    return {
        "schema": "canonical_strategy25_registry_v1",
        "strategy_count": 25,
        "entries": entries,
    }


def test_closure_adds_role_only_to_targets():
    module = load_module()
    before = make_registry(module)
    after = module.build_closed_registry(before)
    module.verify_closed(before, after)

    by_id = {row["strategy_id"]: row for row in after["entries"]}
    for strategy_id in module.TARGET_IDS:
        row = by_id[strategy_id]
        assert row["strategy_role"] == "standalone"
        assert row["execution_scope"] == "independent_entry_add_reduce_exit"
        assert row["role_authority_source"] == "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"

    assert "strategy_role" not in by_id["other_5"]


def test_closure_is_idempotent():
    module = load_module()
    before = make_registry(module)
    once = module.build_closed_registry(before)
    twice = module.build_closed_registry(once)
    assert once == twice


def test_conflicting_role_is_rejected():
    module = load_module()
    before = make_registry(module)
    before["entries"][0]["strategy_role"] = "overlay"
    try:
        module.build_closed_registry(before)
    except ValueError as exc:
        assert "CONFLICTING_ROLE" in str(exc)
    else:
        raise AssertionError("conflicting role must fail closed")


def test_non_target_mutation_is_rejected():
    module = load_module()
    before = make_registry(module)
    after = module.build_closed_registry(before)
    after["entries"][5]["active_allowed"] = True
    try:
        module.verify_closed(before, after)
    except ValueError as exc:
        assert "ACTIVE_ALLOWED" in str(exc) or "NON_TARGET_ENTRY_CHANGED" in str(exc)
    else:
        raise AssertionError("non-target mutation must fail closed")
