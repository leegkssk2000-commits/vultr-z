from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.production.zel_production_ai_pre_survivor_next_hypothesis_v1 import (
    ACTIVE_PROPOSAL_PATH,
    next_hypothesis_tick,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_ai_pre_survivor_next_hypothesis_v1.json").read_text())
PROPOSAL_POLICY = json.loads((ROOT / "config/zel_production_ai_proposal_layer_pre_survivor_v1.json").read_text())
FACTORY = json.loads((ROOT / "config/zel_production_alpha_factory_v1.json").read_text())
BASE_TS = 1_780_000_000_000


def feedback(*, trade_count: int = 7, net_pnl: float = -71.9273855204) -> dict:
    return {
        "schema_version": "zel.production_pre_survivor_feedback_bridge.v1",
        "state": "PASS_PRE_SURVIVOR_ACCUMULATING_CONTEXT_PROJECTED",
        "context_kind": "PROVISIONAL_ACCUMULATING",
        "non_terminal_context": True,
        "source_admission_state": "HOLD_AI_ADMISSION_REJECTION_EVIDENCE_INSUFFICIENT",
        "family_id": "funding_volume_elasticity",
        "contract_id": "b" * 32,
        "template_id": "funding_volume_elasticity_v1",
        "progress_direction": "REGRESSED",
        "context_intent": "INFORM_NEXT_NEW_ECONOMIC_FAMILY_WHILE_CURRENT_FAMILY_ACCUMULATES",
        "trade_count": trade_count,
        "win_rate_pct": 42.8571428571,
        "net_expectancy": -10.2753407886,
        "profit_factor": 0.4499134085,
        "net_pnl": net_pnl,
        "max_dd_pct": 0.7321944998,
        "metric_units": {
            "trade_count": "trades",
            "win_rate_pct": "pct",
            "net_expectancy": "bps_per_trade",
            "profit_factor": "ratio",
            "net_pnl": "bps",
            "max_dd_pct": "pct",
        },
        "delta_vs_previous": {
            "trade_count": 1,
            "win_rate_pct": -7.1428571429,
            "net_expectancy_bps": -8.0400499186,
            "net_pnl_bps": -58.5156403004,
            "profit_factor": -0.3644333575,
            "max_drawdown_pct": 0.1568242156,
        },
        "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
        "receipt_sha256": "e" * 64,
    }


def proposal_item() -> dict:
    return {
        "proposal_type": "NEW_ECONOMIC_FAMILY",
        "family_id": "basis_funding_dispersion_next",
        "economic_mechanism": "Cross-market derivative carry disagreement may reveal a distinct repricing pressure not captured by the current family.",
        "required_sources": ["funding", "basis", "open_interest"],
        "causal_reason": "Funding, basis and positioning can diverge when derivative demand and inventory pressure are not aligned.",
        "falsification_test": "Freeze the event definition and reject the hypothesis if the signed effect does not persist in untouched temporal partitions after observed costs.",
        "expected_horizon": "native funding interval",
    }


def test_policy_is_separate_observer_lane() -> None:
    cfg = validate_policy(POLICY)
    assert cfg["role"] == "PARALLEL_NEXT_HYPOTHESIS_OBSERVER_NOT_ROUTE"
    assert cfg["output_path"] != ACTIVE_PROPOSAL_PATH
    assert cfg["selection_authority"] is False
    assert cfg["promotion_authority"] is False
    assert cfg["execution_authority"] == "NONE"
    assert cfg["order_authority"] == "BLOCKED"
    assert cfg["live_trade_authority"] == "BLOCKED"


def test_accumulating_feedback_generates_parallel_next_hypothesis_without_route_authority() -> None:
    called = 0

    def caller(prompt: str):
        nonlocal called
        called += 1
        assert "still accumulating evidence" in prompt
        assert "funding_volume_elasticity" in prompt
        assert "REGRESSED" in prompt
        assert "42.8571428571" in prompt
        assert "MUST NOT be replaced" in prompt
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    result, wrote = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=feedback(),
        factory=FACTORY,
        pool=None,
        previous=None,
        ai_caller=caller,
        now_ms=BASE_TS,
    )
    assert wrote is True
    assert called == 1
    assert result["state"] == "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
    assert result["current_family_id"] == "funding_volume_elasticity"
    assert result["current_progress_direction"] == "REGRESSED"
    assert result["proposal_count"] == 1
    assert result["source_ready_count"] == 1
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"
    assert result["exchange_order_submitted"] is False


def test_same_economic_context_reuses_previous_without_new_ai_call() -> None:
    called = 0

    def caller(_: str):
        nonlocal called
        called += 1
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    first, wrote = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=feedback(),
        factory=FACTORY,
        pool=None,
        previous=None,
        ai_caller=caller,
        now_ms=BASE_TS,
    )
    assert wrote is True and called == 1
    second, wrote2 = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=feedback(),
        factory=FACTORY,
        pool=None,
        previous=first,
        ai_caller=caller,
        now_ms=BASE_TS + 1,
    )
    assert second == first
    assert wrote2 is False
    assert called == 1


def test_changed_economic_context_refreshes_ai_without_touching_active_route() -> None:
    called = 0

    def caller(_: str):
        nonlocal called
        called += 1
        return "models/gemini-fixture", {"status": "PASS", "proposals": [proposal_item()]}

    first, _ = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=feedback(trade_count=7),
        factory=FACTORY,
        pool=None,
        previous=None,
        ai_caller=caller,
        now_ms=BASE_TS,
    )
    changed = feedback(trade_count=8, net_pnl=-80.0)
    changed["receipt_sha256"] = "f" * 64
    second, wrote = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=changed,
        factory=FACTORY,
        pool=None,
        previous=first,
        ai_caller=caller,
        now_ms=BASE_TS + 1,
    )
    assert wrote is True
    assert called == 2
    assert first["context_sha256"] != second["context_sha256"]
    assert first["explore_context_sha256"] != second["explore_context_sha256"]
    assert second["order_authority"] == "BLOCKED"
    assert POLICY["output_path"] != ACTIVE_PROPOSAL_PATH


def test_terminal_or_missing_context_does_not_generate_parallel_hypothesis() -> None:
    terminal = copy.deepcopy(feedback())
    terminal["state"] = "PASS_PRE_SURVIVOR_REJECT_CONTEXT_PROJECTED"
    terminal["context_kind"] = "TERMINAL_REJECT"
    terminal["non_terminal_context"] = False
    called = 0

    def caller(_: str):
        nonlocal called
        called += 1
        raise AssertionError("AI must not be called for terminal context in the parallel lane")

    result, wrote = next_hypothesis_tick(
        POLICY,
        PROPOSAL_POLICY,
        feedback=terminal,
        factory=FACTORY,
        pool=None,
        previous=None,
        ai_caller=caller,
        now_ms=BASE_TS,
    )
    assert result["state"] == "HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_NO_ACCUMULATING_CONTEXT"
    assert wrote is False
    assert called == 0
    assert result["order_authority"] == "BLOCKED"
