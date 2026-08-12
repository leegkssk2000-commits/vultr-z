from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.production.zel_production_survivor_pool_v1 import pool_tick


POLICY = json.loads(Path("config/zel_production_survivor_pool_v1.json").read_text())


def survivor(family: str, score: float, *, suffix: str = "a", dd: float = 5.0, symbol: str = "BTCUSDT") -> dict:
    digit = str((len(family) + len(suffix)) % 10)
    return {
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "symbol_qualified": True,
        "runtime_symbol": symbol,
        "family_id": family,
        "strategy_id": f"{family}_strategy",
        "alpha_id": f"{family}.{suffix}",
        "canary_key": f"canary-{family}-{suffix}",
        "contract_id": f"contract-{family}-{suffix}",
        "contract_receipt_sha256": digit * 64,
        "canary_receipt_sha256": str((int(digit) + 1) % 10) * 64,
        "authority_receipt_sha256": f"sha-{family}-{suffix}",
        "source_hashes": [f"source-{family}"],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "metrics": {
            "score": score,
            "net_expectancy": score / 10.0,
            "profit_factor": 1.0 + score / 100.0,
            "net_pnl": score * 2.0,
            "max_dd_pct": dd,
            "trade_count": 100 + score,
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def test_empty_pool_holds_without_fake_event() -> None:
    pool, event = pool_tick(POLICY, catalog=None, incumbent_registry=None, previous_pool=None, now_ms=1)
    assert pool["state"] == "HOLD_SURVIVOR_POOL_BUILDING"
    assert pool["active_count"] == 0 and pool["reserve_count"] == 0
    assert pool["statistical_independence_claimed"] is False
    assert event is None


def test_distinct_family_top3_plus2_and_target_event_preserve_runtime_symbols() -> None:
    rows = [survivor(f"family{i}", float(10 - i), symbol="BTCUSDT" if i % 2 == 0 else "ETHUSDT") for i in range(5)]
    rows.append(survivor("family0", 1.0, suffix="worse", symbol="ETHUSDT"))
    catalog = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": rows}
    pool, event = pool_tick(POLICY, catalog=catalog, incumbent_registry=None, previous_pool=None, now_ms=2)
    assert pool["state"] == "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2"
    assert [x["family_id"] for x in pool["active"]] == ["family0", "family1", "family2"]
    assert [x["family_id"] for x in pool["reserve"]] == ["family3", "family4"]
    assert len({x["family_id"] for x in pool["active"] + pool["reserve"]}) == 5
    assert all(x["runtime_symbol"] in {"BTCUSDT", "ETHUSDT"} for x in pool["active"] + pool["reserve"])
    assert all(x["contract_receipt_sha256"] for x in pool["active"] + pool["reserve"])
    assert event is not None and event["event_type"] == "POOL_TARGET_3_PLUS_2_REACHED"
    assert event["order_authority"] == "BLOCKED"


def test_pool_change_event_rotates_active_when_rank_changes() -> None:
    first = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": [survivor(f"f{i}", float(5-i)) for i in range(4)]}
    old, _ = pool_tick(POLICY, catalog=first, incumbent_registry=None, previous_pool=None, now_ms=3)
    second_rows = [survivor(f"f{i}", float(5-i)) for i in range(4)] + [survivor("new", 99.0, symbol="ETHUSDT")]
    second = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": second_rows}
    new, event = pool_tick(POLICY, catalog=second, incumbent_registry=None, previous_pool=old, now_ms=4)
    assert new["active"][0]["family_id"] == "new"
    assert new["active"][0]["runtime_symbol"] == "ETHUSDT"
    assert event is not None and event["event_type"] == "POOL_TARGET_3_PLUS_2_REACHED"


def test_legacy_incumbent_is_ingested_as_one_family_with_exact_symbol() -> None:
    registry = {
        "schema_version": "zel.production_incumbent_registry.v1",
        "current_authority": {
            "strategy_id": "seed_strategy",
            "family_id": "seed_family",
            "alpha_id": "seed.alpha",
            "symbol": "BTCUSDT",
            "alpha_state": "SURVIVOR_ACTIVE",
            "receipt_sha256": "authority-sha",
            "source_hashes": ["source-sha"],
            "runtime_authority": {
                "execution_authority": "PAPER_SIM_ONLY",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED"
            }
        },
        "current_metrics": {
            "score": 2.0,
            "net_expectancy": 0.2,
            "profit_factor": 1.2,
            "net_pnl": 4.0,
            "max_dd_pct": 3.0,
            "trade_count": 50.0
        }
    }
    pool, event = pool_tick(POLICY, catalog=None, incumbent_registry=registry, previous_pool=None, now_ms=5)
    assert pool["active_count"] == 1
    assert pool["active"][0]["family_id"] == "seed_family"
    assert pool["active"][0]["runtime_symbol"] == "BTCUSDT"
    assert event is not None and event["event_type"] == "SURVIVOR_POOL_CHANGED"


def test_rejects_unverified_survivor() -> None:
    bad = survivor("bad", 1.0)
    bad["durability_gate_pass"] = False
    catalog = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": [bad]}
    with pytest.raises(RuntimeError, match="SURVIVOR_POOL_CANDIDATE_GATE_FAIL:durability_gate_pass"):
        pool_tick(POLICY, catalog=catalog, incumbent_registry=None, previous_pool=None, now_ms=6)


def test_rejects_catalog_candidate_without_runtime_symbol() -> None:
    bad = survivor("bad", 1.0)
    bad.pop("runtime_symbol")
    catalog = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": [bad]}
    with pytest.raises(RuntimeError, match="SURVIVOR_POOL_RUNTIME_SYMBOL_INVALID"):
        pool_tick(POLICY, catalog=catalog, incumbent_registry=None, previous_pool=None, now_ms=7)
