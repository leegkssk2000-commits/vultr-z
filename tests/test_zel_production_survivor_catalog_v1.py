from __future__ import annotations

import pytest

from backend.production.zel_production_survivor_catalog_v1 import catalog_tick
from backend.production.zel_production_survivor_pool_v1 import pool_tick


def catalog_policy() -> dict:
    return {
        "schema_version": "zel.production_survivor_catalog_policy.v1",
        "mode": "PAPER",
        "legacy_incumbent_registry_path": "/tmp/incumbent.json",
        "verified_survivor_intake_path": "/tmp/intake.json",
        "catalog_path": "/tmp/catalog.json",
        "event_path": "/tmp/event.json",
        "distinct_family_required": True,
        "ranking_method": "LEXICOGRAPHIC_NO_WEIGHT",
        "ranking_fields": ["net_expectancy_desc", "profit_factor_desc", "max_dd_pct_asc", "net_pnl_desc", "trade_count_desc"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def pool_policy() -> dict:
    return {
        "schema_version": "zel.production_survivor_pool_policy.v1",
        "mode": "PAPER",
        "active_target": 3,
        "reserve_target": 2,
        "candidate_catalog_path": "/tmp/catalog.json",
        "legacy_incumbent_registry_path": "/tmp/incumbent.json",
        "pool_state_path": "/tmp/pool.json",
        "pool_event_path": "/tmp/pool-event.json",
        "distinct_family_required": True,
        "ranking_method": "LEXICOGRAPHIC_NO_WEIGHT",
        "ranking_fields": ["net_expectancy_desc", "profit_factor_desc", "max_dd_pct_asc", "net_pnl_desc", "trade_count_desc"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def survivor(i: int, expectancy: float | None = None) -> dict:
    exp = float(i) / 100 if expectancy is None else float(expectancy)
    return {
        "schema_version": "zel.production_verified_survivor_receipt.v1",
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": f"family_{i}",
        "strategy_id": f"strategy_{i}",
        "alpha_id": f"alpha_{i}_{exp}",
        "authority_receipt_sha256": f"authority-{i}-{exp}",
        "source_hashes": [f"source-{i}"],
        "metrics": {
            "net_expectancy": exp,
            "profit_factor": 1.0 + exp,
            "max_dd_pct": 10.0 - i,
            "net_pnl": 10.0 * i,
            "trade_count": 100.0 + i,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def test_accumulates_distinct_families_and_reaches_3_plus_2() -> None:
    catalog = None
    for i in range(1, 6):
        catalog, event = catalog_tick(catalog_policy(), catalog=catalog, incumbent_registry=None, intake=survivor(i), now_ms=i)
        assert event is not None
        assert catalog["family_count"] == i
    pool, event = pool_tick(pool_policy(), catalog=catalog, incumbent_registry=None, previous_pool=None, now_ms=10)
    assert pool["state"] == "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2"
    assert pool["active_count"] == 3
    assert pool["reserve_count"] == 2
    assert len({x["family_id"] for x in pool["active"] + pool["reserve"]}) == 5
    assert event is not None and event["event_type"] == "POOL_TARGET_3_PLUS_2_REACHED"


def test_same_family_only_better_survivor_replaces() -> None:
    first, _ = catalog_tick(catalog_policy(), catalog=None, incumbent_registry=None, intake=survivor(1, 0.20), now_ms=1)
    worse = survivor(1, 0.10)
    second, event = catalog_tick(catalog_policy(), catalog=first, incumbent_registry=None, intake=worse, now_ms=2)
    assert second["family_count"] == 1
    assert second["survivors"][0]["metrics"]["net_expectancy"] == pytest.approx(0.20)
    better = survivor(1, 0.30)
    third, event = catalog_tick(catalog_policy(), catalog=second, incumbent_registry=None, intake=better, now_ms=3)
    assert third["survivors"][0]["metrics"]["net_expectancy"] == pytest.approx(0.30)
    assert event is not None


def test_failed_gate_cannot_enter_catalog() -> None:
    row = survivor(1)
    row["durability_gate_pass"] = False
    with pytest.raises(RuntimeError, match="SURVIVOR_CATALOG_GATE_FAIL:durability_gate_pass"):
        catalog_tick(catalog_policy(), catalog=None, incumbent_registry=None, intake=row, now_ms=1)
