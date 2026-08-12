from __future__ import annotations

from backend.production.zel_production_ai_proposal_layer_v1 import build_context
from backend.production.zel_production_ai_proposal_repair_v1 import (
    TRIGGER_ERROR,
    corrective_prompt,
    repair_tick,
)


def policy() -> dict:
    return {
        "schema_version": "zel.production_ai_proposal_policy.v1",
        "state": "FROZEN_PAPER_ONLY",
        "mode": "PAPER",
        "trigger_states": ["HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"],
        "acquisition_state_path": "/tmp/edge.json",
        "factory_path": "/tmp/factory.json",
        "survivor_pool_path": "/tmp/pool.json",
        "improvement_evidence_path": "/tmp/improvement.json",
        "proposal_state_path": "/tmp/proposal.json",
        "candidate_budget": 2,
        "proposal_retry_cooldown_ms": 3600000,
        "source_vocabulary": ["funding", "basis", "open_interest", "ohlcv", "volume", "l2_order_book"],
        "models": ["models/test"],
        "max_output_tokens": 1024,
        "temperature": 0.1,
        "raw_trades_sent": False,
        "private_code_sent": False,
        "account_data_sent": False,
        "credentials_sent": False,
        "numeric_threshold_proposals_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def edge() -> dict:
    return {
        "schema_version": "zel.production_economic_edge_router.v1",
        "state": "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED",
        "next": "REGISTER_NEW_VERIFIED_ECONOMIC_FAMILY_OR_BIND_MISSING_NATIVE_SOURCE",
        "blockers": [],
        "acquisition_queue": [],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def factory() -> dict:
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "state": "NO_ECONOMIC_SURVIVOR_SAFE_IDLE",
        "families": {
            "carry_positioning": {
                "strategy_id": "carry_positioning_v1",
                "status": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
                "reactivation_allowed": False,
                "funding_source_bound": True,
                "basis_source_bound": True,
                "open_interest_source_bound": True,
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
            }
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def previous(error_code: str = TRIGGER_ERROR) -> dict:
    p = policy()
    e = edge()
    f = factory()
    context = build_context(p, edge=e, factory=f, pool=None, improvement=None)
    return {
        "schema_version": "zel.production_ai_proposal_layer.v1",
        "state": "HOLD_AI_PROPOSAL_CALL_FAILED",
        "error_class": "RuntimeError",
        "error_code": error_code,
        "explore_context_sha256": context["explore_context_sha256"],
        "proposal_count": 0,
        "source_ready_count": 0,
        "proposals": [],
        "ai_call_made": True,
        "ai_call_succeeded": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def valid_response() -> dict:
    return {
        "status": "PASS",
        "proposals": [
            {
                "proposal_type": "NEW_ECONOMIC_FAMILY",
                "family_id": "funding_basis_reversion",
                "economic_mechanism": "Funding dislocation relative to basis can encode crowded positioning that mean reverts after inventory pressure normalizes.",
                "required_sources": ["funding", "basis"],
                "causal_reason": "Funding and basis jointly reflect leverage demand and futures positioning pressure.",
                "falsification_test": "Reject if forward returns do not differ from the frozen negative controls across the durability split.",
                "expected_horizon": "multi-hour futures positioning normalization",
            }
        ],
    }


def test_trigger_error_gets_exactly_one_corrective_call_and_passes() -> None:
    calls: list[str] = []

    def caller(prompt: str):
        calls.append(prompt)
        return "models/test", valid_response()

    result, written = repair_tick(
        policy(), edge=edge(), factory=factory(), pool=None, improvement=None, previous=previous(), ai_caller=caller, now_ms=10
    )
    assert written is True
    assert result is not None
    assert result["state"] == "PASS_AI_PROPOSAL_SOURCE_READY"
    assert result["repair_attempt_count"] == 1
    assert result["ai_call_succeeded"] is True
    assert result["proposal_count"] == 1
    assert len(calls) == 1
    assert set(result["proposals"][0]["required_sources"]) <= set(policy()["source_vocabulary"])
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"
    assert result["exchange_order_submitted"] is False


def test_second_invalid_source_response_fails_closed_without_third_attempt() -> None:
    calls = 0

    def caller(prompt: str):
        nonlocal calls
        calls += 1
        bad = valid_response()
        bad["proposals"][0]["required_sources"] = ["liquidation_heatmap"]
        return "models/test", bad

    result, written = repair_tick(
        policy(), edge=edge(), factory=factory(), pool=None, improvement=None, previous=previous(), ai_caller=caller, now_ms=20
    )
    assert written is True
    assert result is not None
    assert result["state"] == "HOLD_AI_PROPOSAL_CORRECTIVE_RETRY_FAILED"
    assert result["error_code"] == TRIGGER_ERROR
    assert result["ai_call_succeeded"] is False
    assert calls == 1
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"


def test_unrelated_validation_failure_is_not_retried() -> None:
    calls = 0

    def caller(prompt: str):
        nonlocal calls
        calls += 1
        return "models/test", valid_response()

    result, written = repair_tick(
        policy(),
        edge=edge(),
        factory=factory(),
        pool=None,
        improvement=None,
        previous=previous("AI_PROPOSAL_SCHEMA_MISMATCH:0"),
        ai_caller=caller,
        now_ms=30,
    )
    assert result is None
    assert written is False
    assert calls == 0


def test_corrective_prompt_freezes_exact_vocabulary_and_forbids_substitution() -> None:
    p = policy()
    context = build_context(p, edge=edge(), factory=factory(), pool=None, improvement=None)
    text = corrective_prompt(context, p["candidate_budget"], p["source_vocabulary"])
    for source in p["source_vocabulary"]:
        assert source in text
    assert "EVERY_REQUIRED_SOURCE_MUST_BE_EXACT_MEMBER_OF_ALLOWED_SOURCE_VOCABULARY" in text
    assert '"outside_vocabulary_sources": "FORBIDDEN"' in text
    assert '"silent_source_substitution": "FORBIDDEN"' in text
    assert "liquidation_heatmap" not in text
