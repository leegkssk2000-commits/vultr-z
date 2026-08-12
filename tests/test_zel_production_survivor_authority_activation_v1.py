from __future__ import annotations

import copy

import pytest

from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_survivor_authority_activation_v1 import activate_tick


def _receipt(row: dict) -> dict:
    row = dict(row)
    row["receipt_sha256"] = stable_sha(row)
    return row


def _policy() -> dict:
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


def _candidate(n: int, *, primary: bool = False) -> dict:
    return {
        "family_id": f"family_{n}",
        "strategy_id": "l2_inventory_pressure_v1" if primary else "basis_oi_deleveraging_v1",
        "alpha_id": f"alpha_{n}",
        "symbol_qualified": True,
        "runtime_symbol": "BTCUSDT" if n % 2 else "ETHUSDT",
        "canary_key": "a" * 31 + str(n),
        "contract_id": f"contract_{n}",
        "contract_receipt_sha256": str(n) * 64,
        "canary_receipt_sha256": chr(96 + n) * 64,
        "authority_receipt_sha256": "",
        "source_hashes": [chr(70 + n) * 64],
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "metrics": {
            "net_expectancy": 1.0 + n,
            "profit_factor": 1.1 + n / 10,
            "net_pnl": 10.0 + n,
            "max_dd_pct": 2.0,
            "trade_count": 180.0,
        },
        "source": "SURVIVOR_CATALOG",
    }


def _fixtures() -> tuple[dict, dict]:
    active = [_candidate(1, primary=True), _candidate(2), _candidate(3)]
    reserve = [_candidate(4), _candidate(5)]
    primary = active[0]
    result = {
        "schema_version": "zel.production_family_paper_canary_result.v1",
        "state": "PASS_FAMILY_PAPER_CANARY",
        "family_id": primary["family_id"],
        "strategy_id": primary["strategy_id"],
        "alpha_id": primary["alpha_id"],
        "runtime_symbol": primary["runtime_symbol"],
        "symbol_qualified": True,
        "canary_key": primary["canary_key"],
        "contract_id": primary["contract_id"],
        "contract_receipt_sha256": primary["contract_receipt_sha256"],
        "prospective_only": True,
        "admission_history_reuse_allowed": False,
        "windows": {},
        "metrics": {},
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    result = _receipt(result)
    primary["canary_receipt_sha256"] = result["receipt_sha256"]
    canary_state = {
        "schema_version": "zel.production_family_paper_canary_runner.v1",
        "state": "PASS_FAMILY_PAPER_CANARY_RESULT_READY",
        "action": "hold",
        "canaries": {
            primary["canary_key"]: {
                "status": "PASS",
                "family_id": primary["family_id"],
                "strategy_id": primary["strategy_id"],
                "contract_id": primary["contract_id"],
                "contract_receipt_sha256": primary["contract_receipt_sha256"],
                "result": result,
            }
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": 1000,
    }
    canary_state = _receipt(canary_state)
    pool = {
        "schema_version": "zel.production_survivor_pool.v1",
        "state": "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2",
        "action": "hold",
        "active_target": 3,
        "reserve_target": 2,
        "active_count": 3,
        "reserve_count": 2,
        "verified_family_count": 5,
        "active": active,
        "reserve": reserve,
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
    }
    return _receipt(pool), canary_state


def test_symbol_qualified_primary_becomes_executable_paper_authority() -> None:
    pool, canary = _fixtures()
    state, authority = activate_tick(_policy(), pool=pool, canary_state=canary, now_ms=2000)
    assert state["state"] == "PASS_SURVIVOR_PAPER_AUTHORITY_READY"
    assert state["authority_written"] is True
    assert authority is not None
    assert authority["family_id"] == "family_1"
    assert authority["strategy_id"] == "l2_inventory_pressure_v1"
    assert authority["symbol"] == "BTCUSDT"
    assert authority["promotion_authority"] is True
    assert authority["runtime_authority"] == {
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    assert authority["exchange_order_submitted"] is False
    assert authority_is_executable(authority) is True


def test_pool_not_3_plus_2_holds_without_authority() -> None:
    pool, canary = _fixtures()
    pool = copy.deepcopy(pool)
    pool.pop("receipt_sha256")
    pool["state"] = "HOLD_SURVIVOR_POOL_BUILDING"
    pool["active_count"] = 2
    pool["active"] = pool["active"][:2]
    pool = _receipt(pool)
    state, authority = activate_tick(_policy(), pool=pool, canary_state=canary, now_ms=2000)
    assert state["state"] == "HOLD_SURVIVOR_AUTHORITY_NOT_READY"
    assert state["authority_written"] is False
    assert authority is None


def test_tampered_pool_receipt_fails_closed() -> None:
    pool, canary = _fixtures()
    pool["active"][0]["runtime_symbol"] = "ETHUSDT"
    with pytest.raises(RuntimeError, match="POOL_RECEIPT_MISMATCH"):
        activate_tick(_policy(), pool=pool, canary_state=canary, now_ms=2000)


def test_canary_lineage_mismatch_fails_closed() -> None:
    pool, canary = _fixtures()
    canary = copy.deepcopy(canary)
    canary.pop("receipt_sha256")
    key = pool["active"][0]["canary_key"]
    result = canary["canaries"][key]["result"]
    result.pop("receipt_sha256")
    result["runtime_symbol"] = "ETHUSDT"
    result["receipt_sha256"] = stable_sha(result)
    canary["receipt_sha256"] = stable_sha(canary)
    with pytest.raises(RuntimeError, match="CANARY_LINEAGE_MISMATCH:runtime_symbol"):
        activate_tick(_policy(), pool=pool, canary_state=canary, now_ms=2000)


def test_policy_cannot_open_live_or_raise_risk() -> None:
    pool, canary = _fixtures()
    for mutation, message in [
        ({"live_trade_authority": "ENABLED"}, "LIVE_AUTHORITY_FORBIDDEN"),
        ({"order_authority": "ENABLED"}, "LIVE_AUTHORITY_FORBIDDEN"),
        ({"risk_request": {"leverage_x": 20, "position_pct": 20.0}}, "RISK_REQUEST_DRIFT"),
    ]:
        policy = _policy()
        policy.update(mutation)
        with pytest.raises(RuntimeError, match=message):
            activate_tick(policy, pool=pool, canary_state=canary, now_ms=2000)
