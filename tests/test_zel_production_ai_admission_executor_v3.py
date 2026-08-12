from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_ai_admission_executor_v3 import (
    FUNDING_VOLUME_CONTEXT,
    FUNDING_VOLUME_TEMPLATE,
    build_funding_volume_observations,
    defer_early_rejection,
    load_rejection_evidence_floor,
)

OBSERVED_AT_MS = 1_800_000_000_000
CANDLE_TS_MS = OBSERVED_AT_MS - 7_200_000


def contract() -> dict:
    return {
        "contract_id": "c1",
        "family_id": "funding_volume_elasticity",
        "template_id": FUNDING_VOLUME_TEMPLATE,
    }


def carry(funding: float, observed_at_ms: int = OBSERVED_AT_MS) -> dict:
    return {
        "schema_version": "zel.production_carry_flow_data.v1",
        "state": "PASS_CARRY_POSITIONING_RAW_DATA",
        "observed_at_ms": observed_at_ms,
        "records": [
            {
                "symbol": "BTC-USDT",
                "feature": "premium_index",
                "raw": {"lastFundingRate": str(funding)},
                "source_payload_sha256": "a" * 64,
            }
        ],
        "receipt_sha256": "b" * 64,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def candles(open_price: float, close_price: float, volume: float) -> dict:
    return {
        "BTC-USDT": [
            {"ts": CANDLE_TS_MS, "op": open_price, "cl": close_price, "vol": volume}
        ]
    }


def previous(*, funding: float, volume: float) -> dict:
    return {
        "schema_version": "zel.production_ai_admission_observation.v1",
        "contract_id": "c1",
        "family_id": "funding_volume_elasticity",
        "template_id": FUNDING_VOLUME_TEMPLATE,
        "symbol": "BTC-USDT",
        "observed_at_ms": OBSERVED_AT_MS - 3_600_000,
        "outcome_candle_ts_ms": CANDLE_TS_MS - 3_600_000,
        "outcome_close": 100.0,
        "funding_rate": funding,
        "volume": volume,
        "context_pass": False,
        "signal_side": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def one(history, *, funding=0.001, op=100.0, cl=101.0, volume=120.0):
    rows = build_funding_volume_observations(
        contract(), carry(funding), candles(op, cl, volume), ["BTC-USDT"], history
    )
    assert len(rows) == 1
    return rows[0]


def test_first_prospective_observation_has_no_signal() -> None:
    row = one([])
    assert row["context_rule"] == FUNDING_VOLUME_CONTEXT
    assert row["context_pass"] is False
    assert row["signal_side"] == 0
    assert row["order_authority"] == "BLOCKED"
    assert row["live_trade_authority"] == "BLOCKED"


def test_unchanged_funding_and_expanding_volume_follows_bullish_candle() -> None:
    row = one([previous(funding=0.001, volume=100.0)], funding=0.001, op=100.0, cl=101.0, volume=120.0)
    assert row["funding_delta"] == 0.0
    assert row["volume_delta"] == 20.0
    assert row["context_pass"] is True
    assert row["signal_side"] == 1


def test_unchanged_funding_and_expanding_volume_follows_bearish_candle() -> None:
    row = one([previous(funding=0.001, volume=100.0)], funding=0.001, op=101.0, cl=100.0, volume=120.0)
    assert row["context_pass"] is True
    assert row["signal_side"] == -1


def test_funding_change_blocks_signal_without_threshold() -> None:
    row = one([previous(funding=0.001, volume=100.0)], funding=0.002, volume=120.0)
    assert row["funding_delta"] != 0.0
    assert row["context_pass"] is False
    assert row["signal_side"] == 0


def test_nonexpanding_volume_blocks_signal() -> None:
    row = one([previous(funding=0.001, volume=120.0)], funding=0.001, volume=120.0)
    assert row["volume_delta"] == 0.0
    assert row["context_pass"] is False
    assert row["signal_side"] == 0


def test_registered_template_is_exact_and_search_free() -> None:
    registry = json.loads(Path("config/zel_production_ai_admission_template_registry_v1.json").read_text())
    row = registry["templates"][FUNDING_VOLUME_TEMPLATE]
    assert row["required_sources_exact"] == ["funding", "ohlcv", "volume"]
    assert row["context_rule"] == FUNDING_VOLUME_CONTEXT
    assert row["numeric_signal_thresholds"] == []
    assert row["parameter_search"] is False
    assert registry["selection_authority"] is False
    assert registry["promotion_authority"] is False
    assert registry["execution_authority"] == "NONE"
    assert registry["order_authority"] == "BLOCKED"
    assert registry["live_trade_authority"] == "BLOCKED"


def test_rejection_floor_is_reused_from_frozen_edge_to_portfolio_contract() -> None:
    policy = json.loads(Path("config/zel_production_ai_admission_executor_v1.json").read_text())
    evidence = load_rejection_evidence_floor(policy)
    assert evidence["trade_floor"] == 60
    assert evidence["source"] == "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT"
    assert evidence["policy_path"] == "config/zel_production_family_paper_evidence_producer_v1.json"


def test_early_negative_edge_is_held_not_terminally_rejected() -> None:
    evidence = {
        "trade_floor": 60,
        "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
        "policy_path": "config/zel_production_family_paper_evidence_producer_v1.json",
    }
    raw = {
        "state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
        "next": "RETURN_TO_EDGE_ACQUISITION",
        "economic_candidate": False,
        "aggregate": {"trade_count": 2, "net_return_sum_bps": -1.0, "net_expectancy_bps": -0.5, "profit_factor": 0.0},
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    row = defer_early_rejection(raw, evidence)
    assert row["state"] == "HOLD_AI_ADMISSION_REJECTION_EVIDENCE_INSUFFICIENT"
    assert row["next"] == "CONTINUE_PROSPECTIVE_SOURCE_HISTORY"
    assert row["rejection_deferred"] is True
    assert row["rejection_evidence_trade_count"] == 2
    assert row["rejection_evidence_trade_floor"] == 60
    assert row["order_authority"] == "BLOCKED"
    assert row["live_trade_authority"] == "BLOCKED"


def test_rejection_is_allowed_only_after_frozen_trade_floor() -> None:
    evidence = {
        "trade_floor": 60,
        "source": "FROZEN_ZEL_EDGE_TO_PORTFOLIO_CONTRACT",
        "policy_path": "config/zel_production_family_paper_evidence_producer_v1.json",
    }
    raw = {
        "state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
        "next": "RETURN_TO_EDGE_ACQUISITION",
        "economic_candidate": False,
        "aggregate": {"trade_count": 60, "net_return_sum_bps": -10.0, "net_expectancy_bps": -0.1, "profit_factor": 0.8},
    }
    row = defer_early_rejection(raw, evidence)
    assert row["state"] == "REJECT_AI_ADMISSION_ECONOMIC_EDGE"
    assert row["next"] == "RETURN_TO_EDGE_ACQUISITION"
    assert row["rejection_deferred"] is False
    assert row["rejection_evidence_met"] is True
