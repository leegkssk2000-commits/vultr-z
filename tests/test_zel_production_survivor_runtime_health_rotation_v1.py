from __future__ import annotations

import copy

import pytest

from backend.production import zel_production_survivor_runtime_health_v1 as health
from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_survivor_authority_activation_v1 import activate_tick as activate_v1
from backend.production.zel_production_survivor_authority_activation_v2 import activate_tick as activate_v2
from backend.production.zel_production_survivor_pool_v2 import pool_tick as pool_v2_tick
from backend.production.zel_production_survivor_rotation_v1 import rotate_tick


def _receipt(row: dict) -> dict:
    row = dict(row)
    row["receipt_sha256"] = stable_sha(row)
    return row


def _activation_policy() -> dict:
    return {
        "schema_version": "zel.production_survivor_authority_activation_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "pool_path": "/tmp/pool.json",
        "canary_state_path": "/tmp/canary.json",
        "authority_path": "/tmp/authority.json",
        "state_path": "/tmp/state.json",
        "required_pool_state": "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2",
        "active_slot_index": 0,
        "selection_rule": "POOL_RANKED_ACTIVE_SLOT_0_NO_RESELECTION",
        "require_symbol_qualified": True,
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def _rotation_policy() -> dict:
    return {
        "schema_version": "zel.production_survivor_rotation_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "authority_path": "/tmp/authority.json",
        "pool_path": "/tmp/pool.json",
        "canary_state_path": "/tmp/canary.json",
        "health_result_path": "/tmp/health.json",
        "quarantine_path": "/tmp/quarantine.json",
        "state_path": "/tmp/rotation.json",
        "rotation_order": ["active", "reserve"],
        "selection_rule": "EXISTING_POOL_ORDER_EXCLUDING_CURRENT_AND_QUARANTINED_NO_RERANK",
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def _candidate(n: int) -> dict:
    strategy = ["l2_inventory_pressure_v1", "basis_oi_deleveraging_v1", "funding_l2_inventory_exhaustion_v1"][(n - 1) % 3]
    return {
        "family_id": f"family_{n}",
        "strategy_id": strategy,
        "alpha_id": f"alpha_{n}",
        "symbol_qualified": True,
        "runtime_symbol": "BTCUSDT" if n % 2 else "ETHUSDT",
        "canary_key": (str(n) * 32)[:32],
        "contract_id": f"contract_{n}",
        "contract_receipt_sha256": str(n) * 64,
        "canary_receipt_sha256": "",
        "authority_receipt_sha256": "",
        "source_hashes": [chr(64 + n) * 64],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "metrics": {
            "net_expectancy": 10.0 - n,
            "profit_factor": 2.0 - n / 10.0,
            "net_pnl": 20.0 - n,
            "max_dd_pct": 1.0 + n / 10.0,
            "trade_count": 180.0,
        },
        "source": "SURVIVOR_CATALOG",
    }


def _fixtures() -> tuple[dict, dict, list[dict]]:
    candidates = [_candidate(i) for i in range(1, 6)]
    canaries = {}
    for candidate in candidates:
        result = {
            "schema_version": "zel.production_family_paper_canary_result.v1",
            "state": "PASS_FAMILY_PAPER_CANARY",
            "family_id": candidate["family_id"],
            "strategy_id": candidate["strategy_id"],
            "alpha_id": candidate["alpha_id"],
            "runtime_symbol": candidate["runtime_symbol"],
            "symbol_qualified": True,
            "canary_key": candidate["canary_key"],
            "contract_id": candidate["contract_id"],
            "contract_receipt_sha256": candidate["contract_receipt_sha256"],
            "prospective_only": True,
            "admission_history_reuse_allowed": False,
            "windows": {},
            "metrics": candidate["metrics"],
            "risk_request": candidate["risk_request"],
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
        }
        result = _receipt(result)
        candidate["canary_receipt_sha256"] = result["receipt_sha256"]
        canaries[candidate["canary_key"]] = {
            "status": "PASS",
            "family_id": candidate["family_id"],
            "strategy_id": candidate["strategy_id"],
            "contract_id": candidate["contract_id"],
            "contract_receipt_sha256": candidate["contract_receipt_sha256"],
            "result": result,
        }
    canary_state = _receipt({
        "schema_version": "zel.production_family_paper_canary_runner.v1",
        "state": "PASS_FAMILY_PAPER_CANARY_RESULT_READY",
        "action": "hold",
        "canaries": canaries,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": 1000,
    })
    pool = _receipt({
        "schema_version": "zel.production_survivor_pool.v1",
        "state": "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2",
        "action": "hold",
        "active_target": 3,
        "reserve_target": 2,
        "active_count": 3,
        "reserve_count": 2,
        "verified_family_count": 5,
        "active": candidates[:3],
        "reserve": candidates[3:],
        "ranking_method": "LEXICOGRAPHIC_NO_WEIGHT",
        "ranking_fields": ["net_expectancy_desc", "profit_factor_desc", "max_dd_pct_asc", "net_pnl_desc", "trade_count_desc"],
        "diversity_state": "STRUCTURAL_FAMILY_DISTINCT_ONLY",
        "statistical_independence_claimed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": 1000,
    })
    return pool, canary_state, candidates


def _authority(pool: dict, canary_state: dict) -> dict:
    state, authority = activate_v1(_activation_policy(), pool=pool, canary_state=canary_state, now_ms=2000)
    assert state["authority_written"] is True and authority is not None
    return authority


def _health_reject(authority: dict) -> dict:
    row = {
        "schema_version": "zel.production_survivor_runtime_health_result.v1",
        "state": "REJECT_SURVIVOR_RUNTIME_HEALTH",
        "health_key": "h" * 32,
        "epoch_index": 0,
        "epoch_not_before_ms": 2000,
        "authority_receipt_sha256": authority["receipt_sha256"],
        "family_id": authority["family_id"],
        "strategy_id": authority["strategy_id"],
        "alpha_id": authority["alpha_id"],
        "runtime_symbol": authority["runtime_symbol"],
        "canary_key": authority["canary_key"],
        "contract_id": authority["contract_id"],
        "contract_receipt_sha256": authority["contract_receipt_sha256"],
        "original_canary_receipt_sha256": authority["canary_receipt_sha256"],
        "symbol_qualified": True,
        "economic_gate_pass": False,
        "durability_gate_pass": False,
        "integrity_pass": True,
        "windows": {},
        "metrics": {},
        "source_hashes": ["f" * 64],
        "prospective_only": True,
        "canary_history_reuse_allowed": False,
        "admission_history_reuse_allowed": False,
        "contract_source": "ORIGINAL_SYMBOL_QUALIFIED_CANARY_SURVIVOR_CONTRACT",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "completed_at_ms": 5000,
    }
    return _receipt(row)


def test_activation_v2_does_not_rewrite_healthy_authority() -> None:
    pool, canary_state, _ = _fixtures()
    authority = _authority(pool, canary_state)
    state, replacement = activate_v2(
        _activation_policy(),
        pool=pool,
        canary_state=canary_state,
        existing_authority=authority,
        now_ms=9000,
    )
    assert state["state"] == "HOLD_SURVIVOR_AUTHORITY_ALREADY_EXECUTABLE"
    assert state["authority_receipt_sha256"] == authority["receipt_sha256"]
    assert replacement is None


def test_runtime_health_reject_quarantines_and_rotates_by_existing_pool_order() -> None:
    pool, canary_state, _ = _fixtures()
    authority = _authority(pool, canary_state)
    state, replacement, quarantine = rotate_tick(
        _rotation_policy(),
        authority=authority,
        health_result=_health_reject(authority),
        pool=pool,
        canary_state=canary_state,
        quarantine_catalog=None,
        now_ms=6000,
    )
    assert state["state"] == "PASS_SURVIVOR_RUNTIME_ROTATED"
    assert state["action"] == "route_change"
    assert replacement is not None and quarantine is not None
    assert replacement["family_id"] == "family_2"
    assert replacement["pool_rank"] == 1
    assert authority_is_executable(replacement) is True
    assert quarantine["quarantined_count"] == 1
    assert quarantine["entries"][0]["family_id"] == "family_1"


def test_rotation_fails_closed_on_stale_health_lineage() -> None:
    pool, canary_state, _ = _fixtures()
    authority = _authority(pool, canary_state)
    bad = _health_reject(authority)
    bad.pop("receipt_sha256")
    bad["alpha_id"] = "other"
    bad = _receipt(bad)
    with pytest.raises(RuntimeError, match="HEALTH_LINEAGE_MISMATCH:alpha_id"):
        rotate_tick(
            _rotation_policy(),
            authority=authority,
            health_result=bad,
            pool=pool,
            canary_state=canary_state,
            quarantine_catalog=None,
            now_ms=6000,
        )


def test_quarantine_aware_pool_removes_failed_exact_lineage() -> None:
    pool, canary_state, candidates = _fixtures()
    authority = _authority(pool, canary_state)
    _, _, quarantine = rotate_tick(
        _rotation_policy(),
        authority=authority,
        health_result=_health_reject(authority),
        pool=pool,
        canary_state=canary_state,
        quarantine_catalog=None,
        now_ms=6000,
    )
    assert quarantine is not None
    catalog_rows = []
    for candidate in candidates:
        row = dict(candidate)
        row.update({
            "state": "PASS_ECONOMIC_SURVIVOR",
            "economic_gate_pass": True,
            "durability_gate_pass": True,
            "integrity_pass": True,
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        })
        catalog_rows.append(row)
    catalog = {"schema_version": "zel.production_survivor_catalog.v1", "survivors": catalog_rows}
    policy = {
        "schema_version": "zel.production_survivor_pool_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "active_target": 3,
        "reserve_target": 2,
        "candidate_catalog_path": "/tmp/catalog.json",
        "legacy_incumbent_registry_path": "/tmp/registry.json",
        "quarantine_path": "/tmp/quarantine.json",
        "pool_state_path": "/tmp/pool.json",
        "pool_event_path": "/tmp/event.json",
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
    state, _ = pool_v2_tick(
        policy,
        catalog=catalog,
        incumbent_registry=None,
        quarantine_catalog=quarantine,
        previous_pool=None,
        now_ms=7000,
    )
    assert state["quarantined_candidate_count"] == 1
    assert state["verified_family_count"] == 4
    assert state["active"][0]["family_id"] == "family_2"
    assert all(x["family_id"] != "family_1" for x in state["active"] + state["reserve"])


def test_health_tick_uses_frozen_180_trade_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    pool, canary_state, _ = _fixtures()
    authority = _authority(pool, canary_state)
    policy = {
        "schema_version": "zel.production_survivor_runtime_health_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "authority_path": "/tmp/authority.json",
        "canary_state_path": "/tmp/canary.json",
        "l2_snapshot_path": "/tmp/l2.json",
        "carry_snapshot_path": "/tmp/carry.json",
        "history_dir": "/tmp/health",
        "state_path": "/tmp/state.json",
        "result_path": "/tmp/result.json",
        "windows": ["W1", "W2", "W3"],
        "trades_per_window": 60,
        "contract_source": "ORIGINAL_SYMBOL_QUALIFIED_CANARY_SURVIVOR_CONTRACT",
        "prospective_only": True,
        "canary_history_reuse_allowed": False,
        "admission_history_reuse_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }
    meta = {
        "execution_cost_bps": 1.0,
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "survivor_contract": {
            "min_trades_per_window": 60,
            "min_profit_factor": 1.0,
            "min_expectancy_exclusive": 0.0,
            "min_net_pnl_exclusive": 0.0,
            "min_payoff_ratio": 1.0,
            "min_retention": 0.60,
            "max_dd_pct": 10.0,
            "source": "fixture",
        },
    }
    monkeypatch.setattr(health, "_health_meta", lambda *args, **kwargs: meta)
    monkeypatch.setattr(health.canary_v1, "_verify_history", lambda rows, m: list(rows))
    monkeypatch.setattr(health.canary_v1, "_new_observations", lambda *args, **kwargs: [])
    monkeypatch.setattr(health.canary_v1, "_trade_rows", lambda *args, **kwargs: [
        {"symbol": "BTC-USDT", "equity_return_pct": 0.10} for _ in range(180)
    ])
    monkeypatch.setattr(health.canary_v1, "_source_hashes", lambda *args, **kwargs: ["a" * 64])
    state, appends, result = health.tick(
        policy,
        authority=authority,
        canary_state=canary_state,
        l2_snapshot=None,
        carry_snapshot=None,
        existing_state=None,
        history=[],
        candles_by_symbol={},
        now_ms=9000,
    )
    assert appends == []
    assert state["status"] == "PASS"
    assert state["trade_count"] == 180
    assert result is not None
    assert result["state"] == "PASS_SURVIVOR_RUNTIME_HEALTH"
    assert result["prospective_only"] is True
    assert result["canary_history_reuse_allowed"] is False
