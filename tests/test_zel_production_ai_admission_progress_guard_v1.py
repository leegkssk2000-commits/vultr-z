from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_ai_admission_progress_guard_v1 import progress_guard_tick

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_ai_admission_executor_v1.json").read_text())
BASE_TS = 1_780_000_000_000
CID = "f" * 32


def contract_state() -> dict:
    return {
        "contracts": [
            {
                "contract_id": CID,
                "template_id": "funding_volume_elasticity_v1",
            }
        ]
    }


def carry_snapshot() -> dict:
    return {"observed_at_ms": BASE_TS + 7_200_000}


def candles() -> dict:
    return {
        "BTC-USDT": [{"ts": BASE_TS, "op": 100.0, "cl": 101.0, "vol": 10.0}],
        "ETH-USDT": [{"ts": BASE_TS, "op": 200.0, "cl": 199.0, "vol": 20.0}],
    }


def row(symbol: str) -> dict:
    return {
        "contract_id": CID,
        "symbol": symbol,
        "outcome_candle_ts_ms": BASE_TS,
    }


def summary(appended: int) -> dict:
    return {"executor_version": "V3", "observation_history_appended": appended}


def test_progress_guard_accepts_valid_same_candle_dedup() -> None:
    out = progress_guard_tick(
        POLICY,
        contract_state=contract_state(),
        carry_snapshot=carry_snapshot(),
        history=[row("BTC-USDT"), row("ETH-USDT")],
        executor_summary=summary(0),
        candles_by_symbol=candles(),
    )
    assert out["state"] == "HOLD_PROSPECTIVE_DUPLICATE_CANDLE"
    assert out["dedup_valid"] is True
    assert out["integrity_ok"] is True
    assert out["missing_key_count"] == 0


def test_progress_guard_accepts_real_history_advance() -> None:
    out = progress_guard_tick(
        POLICY,
        contract_state=contract_state(),
        carry_snapshot=carry_snapshot(),
        history=[row("BTC-USDT"), row("ETH-USDT")],
        executor_summary=summary(2),
        candles_by_symbol=candles(),
    )
    assert out["state"] == "PASS_PROSPECTIVE_HISTORY_ADVANCED"
    assert out["integrity_ok"] is True
    assert out["observation_history_appended"] == 2


def test_progress_guard_blocks_missing_expected_closed_candle_key() -> None:
    out = progress_guard_tick(
        POLICY,
        contract_state=contract_state(),
        carry_snapshot=carry_snapshot(),
        history=[row("BTC-USDT")],
        executor_summary=summary(0),
        candles_by_symbol=candles(),
    )
    assert out["state"] == "HOLD_PROSPECTIVE_APPEND_MISSING"
    assert out["integrity_ok"] is False
    assert out["missing_key_count"] == 1


def test_progress_guard_blocks_duplicate_history_primary_key() -> None:
    out = progress_guard_tick(
        POLICY,
        contract_state=contract_state(),
        carry_snapshot=carry_snapshot(),
        history=[row("BTC-USDT"), row("BTC-USDT")],
        executor_summary=summary(0),
        candles_by_symbol=candles(),
    )
    assert out["state"] == "HOLD_PROSPECTIVE_HISTORY_DUPLICATE_KEY"
    assert out["integrity_ok"] is False
    assert out["duplicate_key_count"] == 1


def test_progress_guard_holds_cleanly_without_target_contract() -> None:
    out = progress_guard_tick(
        POLICY,
        contract_state={"contracts": []},
        carry_snapshot=carry_snapshot(),
        history=[],
        executor_summary=summary(0),
        candles_by_symbol=candles(),
    )
    assert out["state"] == "HOLD_PROSPECTIVE_NO_TARGET_CONTRACT"
    assert out["integrity_ok"] is True
