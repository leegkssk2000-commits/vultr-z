from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_ai_proposal_layer_v1 import proposal_tick
from backend.production.zel_production_ai_terminal_feedback_v1 import feedback_tick


FAMILY = "l2_terminal_fixture"


def policy() -> dict:
    return json.loads(Path("config/zel_production_ai_terminal_feedback_v1.json").read_text())


def proposal_policy() -> dict:
    return json.loads(Path("config/zel_production_ai_proposal_layer_v1.json").read_text())


def factory() -> dict:
    return json.loads(Path("config/zel_production_alpha_factory_v1.json").read_text())


def economic() -> dict:
    return {
        "schema_version": "zel.production_ai_admission_executor.v1",
        "state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
        "results": [{
            "family_id": FAMILY,
            "contract_id": "contract-fixture",
            "template_id": "l2_inventory_pressure_v1",
            "state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
            "receipt_sha256": "1" * 64,
        }],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "receipt_sha256": "2" * 64,
    }


def proposal() -> dict:
    return {
        "schema_version": "zel.production_ai_proposal_layer.v1",
        "state": "PASS_AI_PROPOSAL_SOURCE_READY",
        "explore_context_sha256": "3" * 64,
        "proposal_count": 1,
        "source_ready_count": 1,
        "proposals": [{
            "proposal_id": "fixture-proposal",
            "proposal_type": "NEW_ECONOMIC_FAMILY",
            "family_id": FAMILY,
            "economic_mechanism": "Returned-book pressure aligned with derivative basis may precede inventory normalization.",
            "required_sources": ["basis", "l2_order_book"],
            "missing_sources": [],
            "source_ready": True,
            "causal_reason": "Inventory pressure can create a temporary price concession.",
            "falsification_test": "Require positive untouched temporal partitions after observed costs.",
            "expected_horizon": "next canonical outcome observation",
            "state": "PASS_AI_PROPOSAL_SOURCE_READY",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }],
        "ai_call_made": True,
        "ai_call_succeeded": True,
        "retry_after_ms": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "receipt_sha256": "4" * 64,
    }


def contracts() -> dict:
    return {
        "schema_version": "zel.production_ai_admission_materializer.v1",
        "state": "PASS_AI_ADMISSION_CONTRACTS_FROZEN",
        "contracts": [{
            "family_id": FAMILY,
            "contract_id": "contract-fixture",
            "template_id": "l2_inventory_pressure_v1",
        }],
        "contract_count": 1,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "receipt_sha256": "5" * 64,
    }


def test_reject_is_catalogued_and_removed_from_live_proposal_and_contract() -> None:
    result = feedback_tick(
        policy(),
        economic=economic(),
        proposal=proposal(),
        contracts=contracts(),
        catalog=None,
        factory=factory(),
        proposal_policy=proposal_policy(),
        now_ms=1000,
    )
    assert result["state"] == "PASS_AI_TERMINAL_REJECT_FEEDBACK_APPLIED"
    assert result["new_terminal_family_ids"] == [FAMILY]
    assert result["terminal_family_count"] == 1
    assert result["dropped_proposal_count"] == 1
    assert result["dropped_contract_count"] == 1
    assert result["sanitized_proposal"]["proposals"] == []
    assert result["sanitized_proposal"]["ai_call_succeeded"] is False
    assert result["sanitized_proposal"]["retry_after_ms"] == 0
    assert result["sanitized_contracts"]["contracts"] == []
    terminal = result["augmented_factory"]["families"][FAMILY]
    assert terminal["reactivation_allowed"] is False
    assert terminal["status"].startswith("TERMINAL_REJECT")
    assert result["augmented_proposal_policy"]["factory_path"] == policy()["augmented_factory_path"]
    assert result["order_authority"] == "BLOCKED"
    assert result["exchange_order_submitted"] is False


def test_terminal_family_is_hard_rejected_if_ai_proposes_it_again() -> None:
    feedback = feedback_tick(
        policy(), economic=economic(), proposal=proposal(), contracts=contracts(), catalog=None,
        factory=factory(), proposal_policy=proposal_policy(), now_ms=1000,
    )
    edge = {
        "schema_version": "zel.production_economic_edge_router.v1",
        "state": "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED",
        "next": "REGISTER_NEW_VERIFIED_ECONOMIC_FAMILY_OR_BIND_MISSING_NATIVE_SOURCE",
        "blockers": [],
        "explore_context_sha256": "a" * 64,
    }

    def caller(_: str):
        return "models/gemini-fixture", {
            "status": "PASS",
            "proposals": [{
                "proposal_type": "NEW_ECONOMIC_FAMILY",
                "family_id": FAMILY,
                "economic_mechanism": "Same rejected family",
                "required_sources": ["basis", "l2_order_book"],
                "causal_reason": "duplicate",
                "falsification_test": "duplicate",
                "expected_horizon": "next observation",
            }],
        }

    result, wrote = proposal_tick(
        feedback["augmented_proposal_policy"],
        edge=edge,
        factory=feedback["augmented_factory"],
        pool=None,
        improvement=None,
        previous=feedback["sanitized_proposal"],
        ai_caller=caller,
        now_ms=2000,
    )
    assert wrote is True
    assert result is not None
    assert result["state"] == "HOLD_AI_PROPOSAL_CALL_FAILED"
    assert "DUPLICATE_FAMILY" in result["error_code"]
    assert result["order_authority"] == "BLOCKED"


def test_catalog_is_idempotent_for_same_economic_reject() -> None:
    first = feedback_tick(
        policy(), economic=economic(), proposal=proposal(), contracts=contracts(), catalog=None,
        factory=factory(), proposal_policy=proposal_policy(), now_ms=1000,
    )
    second = feedback_tick(
        policy(), economic=economic(), proposal=first["sanitized_proposal"], contracts=first["sanitized_contracts"],
        catalog=first["terminal_catalog"], factory=factory(), proposal_policy=proposal_policy(), now_ms=2000,
    )
    assert second["state"] == "HOLD_AI_TERMINAL_FEEDBACK_NO_NEW_REJECT"
    assert second["new_terminal_family_ids"] == []
    assert second["terminal_family_count"] == 1
    assert second["dropped_proposal_count"] == 0
    assert second["dropped_contract_count"] == 0
