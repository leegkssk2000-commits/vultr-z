from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.production.zel_production_source_acquisition_v1 import source_acquisition_tick, validate_registry


def policy() -> dict:
    return json.loads(Path("config/zel_production_source_acquisition_v1.json").read_text())


def registry() -> dict:
    return json.loads(Path("config/zel_production_source_capability_registry_v1.json").read_text())


def proposal() -> dict:
    return {
        "schema_version": "zel.production_ai_proposal_layer.v1",
        "state": "HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED",
        "proposal_count": 2,
        "source_ready_count": 0,
        "proposals": [
            {
                "proposal_id": "p1",
                "proposal_type": "NEW_ECONOMIC_FAMILY",
                "family_id": "liquidation_cascade_imbalance",
                "economic_mechanism": "forced liquidation dislocation",
                "required_sources": ["basis", "liquidation", "open_interest"],
                "missing_sources": ["liquidation"],
                "source_ready": False,
                "causal_reason": "forced flow",
                "falsification_test": "event study",
                "expected_horizon": "intraday",
                "state": "HOLD_AI_PROPOSAL_SOURCE_UNBOUND",
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
            },
            {
                "proposal_id": "p2",
                "proposal_type": "NEW_ECONOMIC_FAMILY",
                "family_id": "order_book_inventory_asymmetry",
                "economic_mechanism": "depth asymmetry",
                "required_sources": ["basis", "l2_order_book"],
                "missing_sources": ["l2_order_book"],
                "source_ready": False,
                "causal_reason": "inventory skew",
                "falsification_test": "event study",
                "expected_horizon": "sub-minute",
                "state": "HOLD_AI_PROPOSAL_SOURCE_UNBOUND",
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
            },
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "receipt_sha256": "fixture",
    }


def test_current_real_blocker_is_only_unverified_liquidation_source() -> None:
    out, updated = source_acquisition_tick(policy(), proposal=proposal(), registry=registry(), now_ms=1)
    assert out["state"] == "HOLD_SOURCE_ACQUISITION_VERIFIED_SOURCE_REQUIRED"
    assert [x["source_id"] for x in out["queue"]] == ["liquidation"]
    assert out["queue"][0]["acquisition_action"] == "REGISTER_VERIFIED_NATIVE_ENDPOINT_OR_DATA_PROVIDER"
    assert out["missing_source_count"] == 1
    assert out["resolved_source_count"] == 3  # basis + OI + verified L2
    assert updated is not None
    rows = {x["family_id"]: x for x in updated["proposals"]}
    assert rows["order_book_inventory_asymmetry"]["source_ready"] is True
    assert rows["order_book_inventory_asymmetry"]["missing_sources"] == []
    assert rows["liquidation_cascade_imbalance"]["source_ready"] is False
    assert updated["source_ready_count"] == 1
    assert out["order_authority"] == "BLOCKED"
    assert out["exchange_order_submitted"] is False


def test_current_registry_binds_exact_verified_l2_owner_and_endpoint() -> None:
    row = registry()["sources"]["l2_order_book"]
    assert row == {
        "proposal_available": True,
        "native_read_bound": True,
        "owner_path": "backend/production/zel_production_l2_order_book_data_v1.py",
        "native_endpoint": "/openApi/swap/v2/quote/depth",
        "history_state": "PROSPECTIVE_HISTORY_ACCUMULATING",
    }


def test_binding_liquidation_releases_both_proposals_but_never_grants_authority() -> None:
    reg = copy.deepcopy(registry())
    reg["sources"]["liquidation"] = {
        "proposal_available": True,
        "native_read_bound": True,
        "owner_path": "backend/production/verified_liquidation.py",
        "native_endpoint": "/verified/native/liquidation",
        "history_state": "PROSPECTIVE_HISTORY_ACCUMULATING",
    }
    out, updated = source_acquisition_tick(policy(), proposal=proposal(), registry=reg, now_ms=3)
    assert out["state"] == "PASS_SOURCE_ACQUISITION_PROPOSALS_SOURCE_READY"
    assert out["queue"] == []
    assert updated is not None and updated["source_ready_count"] == 2
    assert updated["selection_authority"] is False
    assert updated["promotion_authority"] is False
    assert updated["execution_authority"] == "NONE"
    assert updated["order_authority"] == "BLOCKED"


def test_registry_rejects_false_bound_source() -> None:
    reg = copy.deepcopy(registry())
    reg["sources"]["liquidation"]["proposal_available"] = True
    with pytest.raises(RuntimeError, match="FALSE_BOUND"):
        validate_registry(reg)


def test_unknown_source_fails_closed() -> None:
    p = proposal()
    p["proposals"][0]["required_sources"] = ["basis", "unknown_feed"]
    with pytest.raises(RuntimeError, match="UNKNOWN_SOURCE"):
        source_acquisition_tick(policy(), proposal=p, registry=registry(), now_ms=4)


def test_no_proposal_is_o1_hold() -> None:
    out, updated = source_acquisition_tick(policy(), proposal=None, registry=registry(), now_ms=5)
    assert out["state"] == "HOLD_SOURCE_ACQUISITION_NO_AI_PROPOSAL"
    assert updated is None
