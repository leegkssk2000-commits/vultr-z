from __future__ import annotations

from backend.production.zel_production_ai_family_canary_handoff_v1 import handoff_tick


def policy():
    return {
        "schema_version": "zel.production_ai_family_canary_handoff_policy.v1",
        "mode": "PAPER",
        "economic_result_path": "/tmp/economic.json",
        "contract_state_path": "/tmp/contracts.json",
        "family_evidence_policy_path": "/tmp/family-policy.json",
        "request_path": "/tmp/request.json",
        "state_path": "/tmp/state.json",
        "max_requests_per_tick": 2,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def family_policy():
    return {
        "schema_version": "zel.production_family_paper_evidence_producer_policy.v1",
        "mode": "PAPER",
        "survivor_contract": {
            "min_trades_per_window": 60,
            "min_profit_factor": 1.0,
            "min_expectancy_exclusive": 0.0,
            "min_net_pnl_exclusive": 0.0,
            "min_payoff_ratio": 1.0,
            "min_retention": 0.60,
            "max_dd_pct": 10.0,
            "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def contracts():
    return {
        "schema_version": "zel.production_ai_admission_materializer.v1",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "contracts": [
            {
                "contract_id": "contract-1",
                "family_id": "basis_oi_deleveraging",
                "proposal_id": "proposal-1",
                "proposal_receipt_sha256": "a" * 64,
                "template_id": "basis_oi_deleveraging_v1",
                "template_sha256": "b" * 64,
                "source_registry_sha256": "c" * 64,
                "required_sources": ["basis", "open_interest"],
                "outcome_source": "ohlcv",
                "mechanism_class": "POSITIONING_DELEVERAGING",
                "event_anchor": "NATIVE_CARRY_SNAPSHOT_CHANGE",
                "direction_rule": "FADE_BASIS_CHANGE_SIGN_WHEN_OI_EXPANDS",
                "context_rule": "REQUIRE_OPEN_INTEREST_INCREASE_AND_NONZERO_BASIS_CHANGE",
                "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
                "negative_controls": ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"],
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
                "receipt_sha256": "d" * 64,
            }
        ],
    }


def economic(state="PASS_AI_ADMISSION_ECONOMIC_CANDIDATE"):
    result_state = "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" if state == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE" else state
    return {
        "schema_version": "zel.production_ai_admission_executor.v1",
        "state": state,
        "updated_at_ms": 1000,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "receipt_sha256": "e" * 64,
        "results": [
            {
                "state": result_state,
                "economic_candidate": state == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE",
                "family_id": "basis_oi_deleveraging",
                "contract_id": "contract-1",
                "template_id": "basis_oi_deleveraging_v1",
                "execution_cost_bps": 4.5,
                "receipt_sha256": "f" * 64,
            }
        ],
    }


def test_pass_candidate_emits_lineage_locked_independent_request():
    state, batch = handoff_tick(
        policy(),
        economic_result=economic(),
        contract_state=contracts(),
        family_evidence_policy=family_policy(),
        now_ms=2000,
    )
    assert state["state"] == "PASS_AI_FAMILY_CANARY_HANDOFF_READY"
    assert state["next"] == "RUN_INDEPENDENT_PROSPECTIVE_FAMILY_PAPER_CANARY"
    assert batch is not None and batch["request_count"] == 1
    req = batch["requests"][0]
    assert req["state"] == "READY_INDEPENDENT_FAMILY_PAPER_CANARY"
    assert req["required_sources"] == ["basis", "open_interest"]
    assert req["independence_contract"] == {
        "prospective_only": True,
        "admission_history_reuse_allowed": False,
        "not_before_ms": 1001,
        "windows": ["W1", "W2", "W3"],
    }
    assert req["survivor_contract"]["min_trades_per_window"] == 60
    assert req["survivor_contract"]["max_dd_pct"] == 10.0
    assert req["selection_authority"] is False
    assert req["promotion_authority"] is False
    assert req["execution_authority"] == "NONE"
    assert req["order_authority"] == "BLOCKED"
    assert req["live_trade_authority"] == "BLOCKED"
    assert req["exchange_order_submitted"] is False


def test_non_candidate_does_not_emit_request():
    state, batch = handoff_tick(
        policy(),
        economic_result=economic("HOLD_AI_ADMISSION_HISTORY_ACCUMULATING"),
        contract_state=contracts(),
        family_evidence_policy=family_policy(),
        now_ms=2000,
    )
    assert state["state"] == "HOLD_AI_FAMILY_CANARY_NO_ECONOMIC_CANDIDATE"
    assert state["request_count"] == 0
    assert batch is None


def test_request_identity_is_idempotent_for_same_lineage():
    _, a = handoff_tick(policy(), economic_result=economic(), contract_state=contracts(), family_evidence_policy=family_policy(), now_ms=2000)
    _, b = handoff_tick(policy(), economic_result=economic(), contract_state=contracts(), family_evidence_policy=family_policy(), now_ms=9000)
    assert a is not None and b is not None
    assert a["requests"][0]["request_id"] == b["requests"][0]["request_id"]
