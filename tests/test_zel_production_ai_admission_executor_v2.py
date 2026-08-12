from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_ai_admission_executor_v2 import (
    BASIS_OI_CONTEXT,
    BASIS_OI_TEMPLATE,
    FUNDING_L2_CONTEXT,
    FUNDING_L2_TEMPLATE,
    build_basis_oi_observations,
    build_funding_l2_observations,
    evaluate_contract,
    validate_contract,
)
from backend.production.zel_production_improvement_controller_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = json.loads((ROOT / "config/zel_production_ai_admission_template_registry_v1.json").read_text())
BASE_TS = 1_780_000_000_000


def contract(template_id: str, family_id: str, sources: list[str]) -> dict:
    t = TEMPLATES["templates"][template_id]
    row = {
        "schema_version": "zel.production_ai_admission_contract.v1",
        "contract_id": ("b" if template_id == BASIS_OI_TEMPLATE else "f") * 32,
        "family_id": family_id,
        "proposal_id": "proposal-fixture",
        "proposal_receipt_sha256": "a" * 64,
        "template_id": template_id,
        "template_sha256": stable_sha(t),
        "source_registry_sha256": "c" * 64,
        "required_sources": sources,
        "outcome_source": t["outcome_source"],
        "mechanism_class": t["mechanism_class"],
        "event_anchor": t["event_anchor"],
        "direction_rule": t["direction_rule"],
        "context_rule": t.get("context_rule"),
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


def carry(*, observed: int, basis: float, oi: float, funding: float = 0.001) -> dict:
    records = []
    for symbol, n in (("BTC-USDT", "1"), ("ETH-USDT", "2")):
        records.extend(
            [
                {
                    "feature": "premium_index",
                    "symbol": symbol,
                    "raw": {"lastFundingRate": funding},
                    "derived_observation": {"basis_bps": basis},
                    "source_payload_sha256": n * 64,
                },
                {
                    "feature": "open_interest",
                    "symbol": symbol,
                    "raw": {"openInterest": oi},
                    "source_payload_sha256": ("3" if symbol == "BTC-USDT" else "4") * 64,
                },
            ]
        )
    return {
        "schema_version": "zel.production_carry_flow_data.v1",
        "state": "PASS_CARRY_POSITIONING_RAW_DATA",
        "observed_at_ms": observed,
        "records": records,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "receipt_sha256": "5" * 64,
    }


def l2(*, observed: int, sign: int = 1) -> dict:
    return {
        "schema_version": "zel.production_l2_order_book_data.v1",
        "state": "PASS_L2_ORDER_BOOK_NATIVE_SNAPSHOT",
        "observed_at_ms": observed,
        "records": [
            {
                "symbol": "BTC-USDT",
                "imbalance_returned_book": 0.2 * sign,
                "primary_imbalance_sign": sign,
                "source_payload_sha256": "6" * 64,
            },
            {
                "symbol": "ETH-USDT",
                "imbalance_returned_book": 0.1 * sign,
                "primary_imbalance_sign": sign,
                "source_payload_sha256": "7" * 64,
            },
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "receipt_sha256": "8" * 64,
    }


def candles(ts: int) -> dict:
    return {
        "BTC-USDT": [{"ts": ts, "cl": 100.0}],
        "ETH-USDT": [{"ts": ts, "cl": 200.0}],
    }


def test_new_contracts_are_frozen_and_threshold_free() -> None:
    b = validate_contract(
        contract(BASIS_OI_TEMPLATE, "basis_volatility_unwind", ["basis", "open_interest"]),
        TEMPLATES,
    )
    f = validate_contract(
        contract(FUNDING_L2_TEMPLATE, "l2_liquidity_asymmetry_shock", ["funding", "l2_order_book"]),
        TEMPLATES,
    )
    assert b["context_rule"] == BASIS_OI_CONTEXT
    assert f["context_rule"] == FUNDING_L2_CONTEXT
    assert b["numeric_signal_thresholds"] == [] and b["parameter_search"] is False
    assert f["numeric_signal_thresholds"] == [] and f["parameter_search"] is False


def test_basis_oi_uses_only_observed_change_and_fades_basis_when_oi_expands() -> None:
    c = contract(BASIS_OI_TEMPLATE, "basis_volatility_unwind", ["basis", "open_interest"])
    first_obs = BASE_TS + 7_200_000
    first = build_basis_oi_observations(c, carry(observed=first_obs, basis=2.0, oi=100.0), candles(BASE_TS + 3_600_000), ["BTC-USDT", "ETH-USDT"], [])
    assert len(first) == 2
    assert all(x["context_pass"] is False and x["signal_side"] == 0 for x in first)
    second_obs = BASE_TS + 10_800_000
    second = build_basis_oi_observations(c, carry(observed=second_obs, basis=5.0, oi=120.0), candles(BASE_TS + 7_200_000), ["BTC-USDT", "ETH-USDT"], first)
    assert len(second) == 2
    assert all(x["context_pass"] is True for x in second)
    assert all(x["basis_delta_bps"] == 3.0 and x["open_interest_delta"] == 20.0 for x in second)
    assert all(x["signal_side"] == -1 for x in second)


def test_funding_l2_requires_sign_consensus_then_fades_crowding_sign() -> None:
    c = contract(FUNDING_L2_TEMPLATE, "l2_liquidity_asymmetry_shock", ["funding", "l2_order_book"])
    observed = BASE_TS + 7_200_000
    rows = build_funding_l2_observations(c, l2(observed=observed, sign=1), carry(observed=observed, basis=1.0, oi=100.0, funding=0.001), candles(BASE_TS + 3_600_000), ["BTC-USDT", "ETH-USDT"])
    assert len(rows) == 2
    assert all(x["context_pass"] is True for x in rows)
    assert all(x["funding_sign"] == 1 and x["primary_imbalance_sign"] == 1 for x in rows)
    assert all(x["signal_side"] == -1 for x in rows)


def test_generic_v2_evaluation_can_only_create_economic_candidate() -> None:
    c = contract(FUNDING_L2_TEMPLATE, "l2_liquidity_asymmetry_shock", ["funding", "l2_order_book"])
    closes = [100.0, 90.0, 85.0, 80.0, 75.0]
    rows = []
    for i, close in enumerate(closes):
        row = {
            "schema_version": "zel.production_ai_admission_observation.v1",
            "contract_id": c["contract_id"],
            "family_id": c["family_id"],
            "template_id": FUNDING_L2_TEMPLATE,
            "symbol": "BTC-USDT",
            "observed_at_ms": BASE_TS + (i + 2) * 3_600_000,
            "outcome_candle_ts_ms": BASE_TS + i * 3_600_000,
            "outcome_close": close,
            "context_pass": True,
            "signal_side": -1,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        row["receipt_sha256"] = stable_sha(row)
        rows.append(row)
    result = evaluate_contract(c, rows, 12.30757224)
    assert result["state"] == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE"
    assert result["economic_candidate"] is True
    assert result["next"] == "BUILD_INDEPENDENT_FAMILY_PAPER_CANARY"
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
