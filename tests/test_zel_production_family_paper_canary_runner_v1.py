from __future__ import annotations

import copy

import pytest

from backend.production.zel_production_family_paper_canary_runner_v1 import (
    evaluate_canary,
    tick,
)
from backend.production.zel_production_improvement_controller_v1 import stable_sha


POLICY = {
    "schema_version": "zel.production_family_paper_canary_runner_policy.v1",
    "state": "FROZEN_PAPER_ONLY",
    "mode": "PAPER",
    "request_path": "/tmp/request.json",
    "handoff_state_path": "/tmp/handoff.json",
    "contract_state_path": "/tmp/contracts.json",
    "template_registry_path": "/tmp/templates.json",
    "l2_snapshot_path": "/tmp/l2.json",
    "carry_snapshot_path": "/tmp/carry.json",
    "history_dir": "/tmp/canary-history",
    "state_path": "/tmp/state.json",
    "result_path": "/tmp/result.json",
    "terminal_result_path": "/tmp/terminal.json",
    "family_evidence_policy_path": "/tmp/evidence-policy.json",
    "risk_policy_path": "/tmp/risk-policy.json",
    "symbols": ["BTC-USDT", "ETH-USDT"],
    "outcome_timeframe": "1h",
    "windows": ["W1", "W2", "W3"],
    "trades_per_window": 60,
    "retention_semantics": "WINDOW_EXPECTANCY_DIV_W1_EXPECTANCY",
    "risk_basis": "MINIMUM_FROZEN_PAPER_EXPOSURE",
    "numeric_signal_thresholds": [],
    "parameter_search": False,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "source_code_mutation_allowed": False,
    "self_modification_allowed": False,
}


SURVIVOR = {
    "min_trades_per_window": 60,
    "min_profit_factor": 1.0,
    "min_expectancy_exclusive": 0.0,
    "min_net_pnl_exclusive": 0.0,
    "min_payoff_ratio": 1.0,
    "min_retention": 0.60,
    "max_dd_pct": 10.0,
    "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
}


FAMILY_POLICY = {
    "schema_version": "zel.production_family_paper_evidence_producer_policy.v1",
    "state": "FROZEN_PAPER_ONLY",
    "mode": "PAPER",
    "survivor_contract": SURVIVOR,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
}


RISK_POLICY = {
    "schema_version": "zel.production_risk_sizing_policy.v1",
    "state": "FROZEN_PAPER_ONLY",
    "mode": "PAPER",
    "allowed_leverage_x": [10, 15, 20],
    "allowed_position_pct": [5, 10, 15, 20],
    "execution_authority": "PAPER_SIM_ONLY",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
}


def template() -> dict:
    return {
        "required_sources_exact": ["basis", "open_interest"],
        "mechanism_class": "POSITIONING_DELEVERAGING",
        "event_anchor": "NATIVE_CARRY_SNAPSHOT_CHANGE",
        "direction_rule": "FADE_BASIS_CHANGE_SIGN_WHEN_OI_EXPANDS",
        "context_rule": "REQUIRE_OPEN_INTEREST_INCREASE_AND_NONZERO_BASIS_CHANGE",
        "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
        "temporal_durability_split": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT",
        "outcome_source": "ohlcv",
        "negative_controls": ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"],
        "numeric_signal_thresholds": [],
        "parameter_search": False,
        "executor_state": "FROZEN_DETERMINISTIC_ADMISSION",
    }


def contract() -> dict:
    t = template()
    row = {
        "schema_version": "zel.production_ai_admission_contract.v1",
        "contract_id": "contract-1",
        "family_id": "basis_oi_deleveraging",
        "proposal_id": "proposal-1",
        "proposal_receipt_sha256": "a" * 64,
        "template_id": "basis_oi_deleveraging_v1",
        "template_sha256": stable_sha(t),
        "source_registry_sha256": "b" * 64,
        "required_sources": ["basis", "open_interest"],
        "outcome_source": "ohlcv",
        "mechanism_class": t["mechanism_class"],
        "event_anchor": t["event_anchor"],
        "direction_rule": t["direction_rule"],
        "context_rule": t["context_rule"],
        "horizon_rule": t["horizon_rule"],
        "temporal_durability_split": t["temporal_durability_split"],
        "negative_controls": t["negative_controls"],
        "numeric_signal_thresholds": [],
        "parameter_search": False,
        "executor_state": t["executor_state"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def contract_state() -> dict:
    return {
        "schema_version": "zel.production_ai_admission_materializer.v1",
        "state": "PASS_AI_ADMISSION_CONTRACTS_FROZEN",
        "contracts": [contract()],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def request(not_before_ms: int = 1000, request_id: str = "request-1") -> dict:
    c = contract()
    lineage = {
        "proposal_receipt_sha256": c["proposal_receipt_sha256"],
        "template_sha256": c["template_sha256"],
        "source_registry_sha256": c["source_registry_sha256"],
        "contract_receipt_sha256": c["receipt_sha256"],
        "economic_result_receipt_sha256": "c" * 64,
        "economic_batch_receipt_sha256": "d" * 64,
    }
    row = {
        "schema_version": "zel.production_family_paper_canary_request.v1",
        "state": "READY_INDEPENDENT_FAMILY_PAPER_CANARY",
        "action": "hold",
        "request_id": request_id,
        "family_id": c["family_id"],
        "contract_id": c["contract_id"],
        "template_id": c["template_id"],
        "proposal_id": c["proposal_id"],
        "required_sources": c["required_sources"],
        "outcome_source": "ohlcv",
        "mechanism_class": c["mechanism_class"],
        "event_anchor": c["event_anchor"],
        "direction_rule": c["direction_rule"],
        "context_rule": c["context_rule"],
        "horizon_rule": c["horizon_rule"],
        "negative_controls": c["negative_controls"],
        "execution_cost_bps": 12.30757224,
        "survivor_contract": SURVIVOR,
        "survivor_contract_sha256": stable_sha(SURVIVOR),
        "independence_contract": {
            "prospective_only": True,
            "admission_history_reuse_allowed": False,
            "not_before_ms": not_before_ms,
            "windows": ["W1", "W2", "W3"],
        },
        "lineage": lineage,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "created_at_ms": not_before_ms - 1,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def batch(req: dict) -> tuple[dict, dict]:
    row = {
        "schema_version": "zel.production_family_paper_canary_request.v1.batch",
        "state": "PASS_INDEPENDENT_FAMILY_PAPER_CANARY_REQUEST_READY",
        "requests": [req],
        "request_count": 1,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": req["created_at_ms"],
    }
    row["receipt_sha256"] = stable_sha(row)
    handoff = {
        "schema_version": "zel.production_ai_family_canary_handoff.v1",
        "state": "PASS_AI_FAMILY_CANARY_HANDOFF_READY",
        "request_receipt_sha256": row["receipt_sha256"],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    return row, handoff


def meta(cost_bps: float = 0.0) -> dict:
    c = contract()
    key = stable_sha({"contract_receipt_sha256": c["receipt_sha256"]})[:32]
    return {
        "canary_key": key,
        "family_id": c["family_id"],
        "strategy_id": c["template_id"],
        "alpha_id": f"{c['family_id']}__{key[:16]}",
        "contract_id": c["contract_id"],
        "contract_receipt_sha256": c["receipt_sha256"],
        "first_request_receipt_sha256": "e" * 64,
        "first_not_before_ms": 1000,
        "execution_cost_bps": cost_bps,
        "risk_request": {"leverage_x": 10, "position_pct": 5.0},
        "risk_policy_sha256": "f" * 64,
        "survivor_contract": SURVIVOR,
        "survivor_contract_sha256": stable_sha(SURVIVOR),
        "initial_lineage": {"template_sha256": c["template_sha256"]},
    }


def history_from_trade_bps(values: list[float]) -> list[dict]:
    price = 100.0
    rows: list[dict] = []
    for idx in range(len(values) + 1):
        row = {
            "schema_version": "zel.production_ai_admission_observation.v1",
            "contract_id": "contract-1",
            "family_id": "basis_oi_deleveraging",
            "template_id": "basis_oi_deleveraging_v1",
            "symbol": "BTC-USDT",
            "observed_at_ms": 1000 + idx * 3_600_000,
            "outcome_candle_ts_ms": 1000 + idx * 3_600_000,
            "outcome_close": price,
            "context_pass": idx < len(values),
            "signal_side": 1 if idx < len(values) else 0,
            "canary_key": meta()["canary_key"],
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        row["receipt_sha256"] = stable_sha(row)
        rows.append(row)
        if idx < len(values):
            price *= 1.0 + values[idx] / 10_000.0
    return rows


def test_three_frozen_60_trade_windows_can_pass_without_parameter_search():
    window = [20.0] * 40 + [-10.0] * 20
    result = evaluate_canary(meta(), history_from_trade_bps(window * 3))
    assert result is not None
    assert result["state"] == "PASS_FAMILY_PAPER_CANARY"
    assert result["economic_gate_pass"] is True
    assert result["durability_gate_pass"] is True
    assert result["integrity_pass"] is True
    assert result["metrics"]["trade_count"] == 180
    assert all(result["windows"][name]["trade_count"] == 60 for name in ("W1", "W2", "W3"))
    assert result["risk_request"] == {"leverage_x": 10, "position_pct": 5.0}
    assert result["parameter_search_performed"] is False


def test_durability_retention_below_frozen_60_percent_rejects():
    w1 = [20.0] * 40 + [-10.0] * 20
    w2 = [10.0] * 40 + [-5.0] * 20
    w3 = [20.0] * 40 + [-10.0] * 20
    result = evaluate_canary(meta(), history_from_trade_bps(w1 + w2 + w3))
    assert result is not None
    assert result["economic_gate_pass"] is True
    assert result["durability_gate_pass"] is False
    assert result["windows"]["W2"]["retention"] == pytest.approx(0.5)
    assert result["state"] == "REJECT_FAMILY_PAPER_CANARY"


def test_repeated_economic_request_for_same_frozen_contract_does_not_restart_canary_clock():
    first_req = request(not_before_ms=1000, request_id="request-1")
    first_batch, first_handoff = batch(first_req)
    state1, _, _, _ = tick(
        POLICY,
        request_batch=first_batch,
        handoff_state=first_handoff,
        contract_state=contract_state(),
        template_registry={"templates": {"basis_oi_deleveraging_v1": template()}},
        family_evidence_policy=FAMILY_POLICY,
        risk_policy=RISK_POLICY,
        l2_snapshot=None,
        carry_snapshot=None,
        existing_state=None,
        histories={},
        candles_by_symbol={},
        current_result=None,
        evidence=None,
        now_ms=2000,
    )
    assert state1["initialized_count"] == 1
    key = next(iter(state1["canaries"]))
    assert state1["canaries"][key]["first_not_before_ms"] == 1000
    assert state1["canaries"][key]["risk_request"] == {"leverage_x": 10, "position_pct": 5.0}

    second_req = request(not_before_ms=9000, request_id="request-2")
    second_batch, second_handoff = batch(second_req)
    state2, _, _, _ = tick(
        POLICY,
        request_batch=second_batch,
        handoff_state=second_handoff,
        contract_state=contract_state(),
        template_registry={"templates": {"basis_oi_deleveraging_v1": template()}},
        family_evidence_policy=FAMILY_POLICY,
        risk_policy=RISK_POLICY,
        l2_snapshot=None,
        carry_snapshot=None,
        existing_state=state1,
        histories={key: []},
        candles_by_symbol={},
        current_result=None,
        evidence=None,
        now_ms=10000,
    )
    assert state2["initialized_count"] == 0
    assert state2["canaries"][key]["first_not_before_ms"] == 1000
    assert state2["canaries"][key]["latest_request_not_before_ms"] == 9000
    assert state2["canaries"][key]["latest_request_id"] == "request-2"


def test_history_before_first_request_is_rejected_as_contamination():
    req = request(not_before_ms=5000)
    req_batch, handoff = batch(req)
    state, _, _, _ = tick(
        POLICY,
        request_batch=req_batch,
        handoff_state=handoff,
        contract_state=contract_state(),
        template_registry={"templates": {"basis_oi_deleveraging_v1": template()}},
        family_evidence_policy=FAMILY_POLICY,
        risk_policy=RISK_POLICY,
        l2_snapshot=None,
        carry_snapshot=None,
        existing_state=None,
        histories={},
        candles_by_symbol={},
        current_result=None,
        evidence=None,
        now_ms=6000,
    )
    key = next(iter(state["canaries"]))
    bad = history_from_trade_bps([10.0])
    for row in bad:
        row["canary_key"] = key
        row["observed_at_ms"] = 4000
        row["receipt_sha256"] = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    with pytest.raises(RuntimeError, match="PRE_REQUEST_CONTAMINATION"):
        tick(
            POLICY,
            request_batch=None,
            handoff_state=None,
            contract_state=contract_state(),
            template_registry={"templates": {"basis_oi_deleveraging_v1": template()}},
            family_evidence_policy=FAMILY_POLICY,
            risk_policy=RISK_POLICY,
            l2_snapshot=None,
            carry_snapshot=None,
            existing_state=copy.deepcopy(state),
            histories={key: bad},
            candles_by_symbol={},
            current_result=None,
            evidence=None,
            now_ms=7000,
        )
