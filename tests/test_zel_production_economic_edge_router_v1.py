from __future__ import annotations

import copy

import pytest

from backend.production.zel_production_economic_edge_router_v1 import route_tick


def policy() -> dict:
    return {
        "schema_version": "zel.production_economic_edge_router_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "factory_path": "config/zel_production_alpha_factory_v1.json",
        "bootstrap_state_path": "/home/z/z/ledger/production_performance_bootstrap_state_v1.json",
        "acquisition_state_path": "/home/z/z/ledger/production_economic_edge_acquisition_v1.json",
        "route_change_states": [
            "HOLD_BOOTSTRAP_ROUTE_CHANGE",
            "HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE",
        ],
        "family_priority": ["carry_flow", "trend_momentum", "relative_value_psa"],
        "family_requirements": {
            "carry_flow": ["funding_source_bound", "basis_source_bound", "open_interest_source_bound", "flow_source_bound"],
            "trend_momentum": [],
            "relative_value_psa": [],
        },
        "candidate_budget": 1,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def bootstrap(state: str = "HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE") -> dict:
    return {
        "schema_version": "zel.production_performance_bootstrap.v1",
        "state": state,
        "action": "hold",
        "exchange_order_submitted": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def factory(flow_bound: bool = False) -> dict:
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "state": "NO_ECONOMIC_SURVIVOR_SAFE_IDLE",
        "families": {
            "carry_flow": {
                "strategy_id": "carry_flow_v1",
                "status": "IMPLEMENTED_CARRY_POSITIONING_DATA_PLANE",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "funding_source_bound": True,
                "basis_source_bound": True,
                "open_interest_source_bound": True,
                "flow_source_bound": flow_bound,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
            },
            "trend_momentum": {
                "strategy_id": "trend_momentum_v1",
                "status": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
                "reactivation_allowed": False,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
            },
            "relative_value_psa": {
                "strategy_id": "relative_value_psa_v1",
                "status": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
                "reactivation_allowed": False,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
            },
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def test_current_catalog_exhausted_fail_closed() -> None:
    r = route_tick(policy(), factory=factory(False), bootstrap=bootstrap(), now_ms=1)
    assert r["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert r["acquisition_queue"] == []
    assert r["next"] == "REGISTER_NEW_VERIFIED_ECONOMIC_FAMILY_OR_BIND_MISSING_NATIVE_SOURCE"
    by_id = {x["family_id"]: x for x in r["blockers"]}
    assert by_id["carry_flow"]["classification"] == "SOURCE_UNBOUND"
    assert by_id["carry_flow"]["missing_source_fields"] == ["flow_source_bound"]
    assert by_id["trend_momentum"]["classification"] == "TERMINAL_REJECT"
    assert by_id["relative_value_psa"]["classification"] == "TERMINAL_REJECT"
    assert r["execution_authority"] == "NONE"
    assert r["order_authority"] == "BLOCKED"
    assert r["exchange_order_submitted"] is False


def test_source_ready_family_queues_only_one_without_authority() -> None:
    r = route_tick(policy(), factory=factory(True), bootstrap=bootstrap(), now_ms=2)
    assert r["state"] == "PASS_EDGE_ACQUISITION_SOURCE_READY_QUEUE"
    assert len(r["acquisition_queue"]) == 1
    assert r["acquisition_queue"][0]["family_id"] == "carry_flow"
    assert r["selection_authority"] is False
    assert r["promotion_authority"] is False
    assert r["execution_authority"] == "NONE"


def test_router_does_nothing_before_route_change() -> None:
    r = route_tick(policy(), factory=factory(False), bootstrap=bootstrap("HOLD_BOOTSTRAP_WAIT_ADMISSION_EVIDENCE"), now_ms=3)
    assert r["state"] == "HOLD_EDGE_ACQUISITION_NOT_REQUIRED"
    assert "acquisition_queue" not in r


def test_missing_bootstrap_holds() -> None:
    r = route_tick(policy(), factory=factory(False), bootstrap=None, now_ms=4)
    assert r["state"] == "HOLD_EDGE_ROUTER_BOOTSTRAP_STATE_MISSING"
    assert r["order_authority"] == "BLOCKED"


def test_preexisting_execution_authority_is_rejected() -> None:
    f = factory(True)
    f["families"]["carry_flow"]["execution_authority"] = "PAPER_SIM_ONLY"
    with pytest.raises(RuntimeError, match="PREEXISTING_EXECUTION_AUTHORITY"):
        route_tick(policy(), factory=f, bootstrap=bootstrap(), now_ms=5)


def test_policy_cannot_open_live() -> None:
    p = copy.deepcopy(policy())
    p["live_trade_authority"] = "ALLOWED"
    with pytest.raises(RuntimeError, match="LIVE_AUTHORITY_FORBIDDEN"):
        route_tick(p, factory=factory(False), bootstrap=bootstrap(), now_ms=6)
