from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_ai_admission_executor_v1 import (
    L2_CONTEXT_RULE,
    OBS_SCHEMA,
    build_observations,
    evaluate_contract,
    executor_tick,
)
from backend.production.zel_production_improvement_controller_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_ai_admission_executor_v1.json").read_text())
TEMPLATES = json.loads((ROOT / "config/zel_production_ai_admission_template_registry_v1.json").read_text())
COST = json.loads((ROOT / "config/zel_production_carry_positioning_v1.json").read_text())
BASE_TS = 1_780_000_000_000


def contract() -> dict:
    t = TEMPLATES["templates"]["l2_inventory_pressure_v1"]
    row = {
        "schema_version": "zel.production_ai_admission_contract.v1",
        "contract_id": "c" * 32,
        "family_id": "l2_basis_inventory_pressure",
        "proposal_id": "p1",
        "proposal_receipt_sha256": "a" * 64,
        "template_id": "l2_inventory_pressure_v1",
        "template_sha256": stable_sha(t),
        "source_registry_sha256": "b" * 64,
        "required_sources": ["basis", "l2_order_book"],
        "outcome_source": "ohlcv",
        "mechanism_class": "STATE_IMBALANCE_CONTINUATION",
        "event_anchor": "NATIVE_ORDER_BOOK_UPDATE",
        "direction_rule": "FOLLOW_PRIMARY_IMBALANCE_SIGN",
        "context_rule": L2_CONTEXT_RULE,
        "horizon_rule": "NEXT_CANONICAL_OUTCOME_OBSERVATION",
        "temporal_durability_split": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_EVENT",
        "negative_controls": ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"],
        "numeric_signal_thresholds": [],
        "parameter_search": False,
        "executor_state": "WAIT_VERIFIED_NORMALIZED_SOURCE_HISTORY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def observation(ts: int, close: float, sign: int = 1, basis_sign: int = 1) -> dict:
    row = {
        "schema_version": OBS_SCHEMA,
        "contract_id": "c" * 32,
        "family_id": "l2_basis_inventory_pressure",
        "template_id": "l2_inventory_pressure_v1",
        "symbol": "BTC-USDT",
        "observed_at_ms": ts + 3_600_000,
        "outcome_candle_ts_ms": ts,
        "outcome_close": close,
        "primary_imbalance_sign": sign,
        "imbalance_returned_book": 0.1 * sign,
        "basis_bps": 2.0 * basis_sign,
        "basis_sign": basis_sign,
        "context_rule": L2_CONTEXT_RULE,
        "context_pass": sign != 0 and sign == basis_sign,
        "l2_source_payload_sha256": "1" * 64,
        "basis_source_payload_sha256": "2" * 64,
        "l2_receipt_sha256": "3" * 64,
        "carry_receipt_sha256": "4" * 64,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def l2_snapshot() -> dict:
    return {
        "schema_version": "zel.production_l2_order_book_data.v1",
        "state": "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT",
        "observed_at_ms": BASE_TS + 7_200_000,
        "records": [
            {"symbol": "BTC-USDT", "imbalance_returned_book": 0.25, "primary_imbalance_sign": 1, "source_payload_sha256": "1" * 64},
            {"symbol": "ETH-USDT", "imbalance_returned_book": -0.25, "primary_imbalance_sign": -1, "source_payload_sha256": "5" * 64},
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "receipt_sha256": "3" * 64,
    }


def carry_snapshot() -> dict:
    return {
        "schema_version": "zel.production_carry_flow_data.v1",
        "state": "PASS_CARRY_POSITIONING_RAW_DATA",
        "records": [
            {"feature": "premium_index", "symbol": "BTC-USDT", "derived_observation": {"basis_bps": 3.0}, "source_payload_sha256": "2" * 64},
            {"feature": "premium_index", "symbol": "ETH-USDT", "derived_observation": {"basis_bps": 3.0}, "source_payload_sha256": "6" * 64},
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "receipt_sha256": "4" * 64,
    }


def test_build_observations_uses_basis_sign_without_numeric_thresholds() -> None:
    candles = {
        "BTC-USDT": [{"ts": BASE_TS, "cl": 100.0}],
        "ETH-USDT": [{"ts": BASE_TS, "cl": 200.0}],
    }
    rows = build_observations(contract(), l2_snapshot(), carry_snapshot(), candles, POLICY["symbols"])
    assert len(rows) == 2
    btc = next(x for x in rows if x["symbol"] == "BTC-USDT")
    eth = next(x for x in rows if x["symbol"] == "ETH-USDT")
    assert btc["context_pass"] is True
    assert eth["context_pass"] is False
    assert btc["context_rule"] == L2_CONTEXT_RULE
    assert btc["selection_authority"] is False
    assert btc["execution_authority"] == "NONE"


def test_evaluate_contract_passes_only_candidate_not_survivor() -> None:
    closes = [100.0, 105.0, 109.0, 112.0, 114.0]
    rows = [observation(BASE_TS + i * 3_600_000, close) for i, close in enumerate(closes)]
    result = evaluate_contract(contract(), rows, 12.30757224)
    assert result["state"] == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE"
    assert result["economic_candidate"] is True
    assert result["next"] == "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY"
    assert result["negative_controls"]["pass"] is True
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"


def test_evaluate_contract_rejects_negative_edge() -> None:
    closes = [100.0, 98.0, 96.0, 94.0, 92.0]
    rows = [observation(BASE_TS + i * 3_600_000, close) for i, close in enumerate(closes)]
    result = evaluate_contract(contract(), rows, 12.30757224)
    assert result["state"] == "REJECT_AI_ADMISSION_ECONOMIC_EDGE"
    assert result["economic_candidate"] is False
    assert result["next"] == "RETURN_TO_EDGE_ACQUISITION"


def test_evaluate_contract_holds_on_insufficient_history() -> None:
    result = evaluate_contract(contract(), [observation(BASE_TS, 100.0), observation(BASE_TS + 3_600_000, 101.0)], 12.30757224)
    assert result["state"] == "HOLD_AI_ADMISSION_HISTORY_INSUFFICIENT"
    assert result["economic_candidate"] is False


def test_executor_keeps_unbound_template_local_and_l2_history_active() -> None:
    l2 = contract()
    liquidation = dict(l2)
    liquidation.update({
        "contract_id": "d" * 32,
        "family_id": "liquidation_family",
        "template_id": "liquidation_cascade_reversion_v1",
        "required_sources": ["basis", "liquidation", "open_interest"],
        "event_anchor": "NONZERO_SIGNED_LIQUIDATION_EVENT",
        "direction_rule": "FADE_PRIMARY_EVENT_SIGN",
        "context_rule": None,
        "template_sha256": stable_sha(TEMPLATES["templates"]["liquidation_cascade_reversion_v1"]),
    })
    state = {
        "schema_version": "zel.production_ai_admission_materializer.v1",
        "contracts": [l2, liquidation],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    result, _ = executor_tick(
        POLICY,
        contract_state=state,
        template_registry=TEMPLATES,
        l2_snapshot=l2_snapshot(),
        carry_snapshot=carry_snapshot(),
        cost_authority=COST,
        candles_by_symbol={
            "BTC-USDT": [{"ts": BASE_TS, "cl": 100.0}],
            "ETH-USDT": [{"ts": BASE_TS, "cl": 200.0}],
        },
        history=[],
    )
    assert result["state"] == "HOLD_AI_ADMISSION_HISTORY_ACCUMULATING"
    states = {str(x.get("state")) for x in result["results"]}
    assert "HOLD_AI_ADMISSION_EXECUTOR_TEMPLATE_NOT_YET_SOURCE_BOUND" in states
    assert "HOLD_AI_ADMISSION_HISTORY_INSUFFICIENT" in states
    assert result["execution_authority"] == "NONE"
