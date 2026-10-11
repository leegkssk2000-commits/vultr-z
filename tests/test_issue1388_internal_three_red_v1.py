from __future__ import annotations

from pathlib import Path

import pandas as pd

from ops import issue1388_internal_three_red_v1 as model
from ops import issue1388_alpha_screen_v1 as common


ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000


def bars(count: int = 40) -> pd.DataFrame:
    values = []
    for i in range(count):
        open_ = 100.0
        close = 100.0
        values.append(
            {
                "open_ts_ms": i * HOUR,
                "close_ts_ms": (i + 1) * HOUR,
                "available_ts_ms": (i + 1) * HOUR,
                "segment_id": "A",
                "open": open_,
                "high": 101.0,
                "low": 99.0,
                "close": close,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(values)


def signal_at(data: pd.DataFrame, index: int = 4) -> None:
    for offset, close in zip((-2, -1, 0), (99.0, 98.0, 97.0)):
        row = index + offset
        data.loc[row, ["open", "high", "low", "close"]] = [close + 1.0, close + 1.5, close - 1.0, close]
    data.loc[index + 1, ["open", "high", "low", "close"]] = [97.5, 99.0, 97.0, 98.0]


def test_frozen_contract_and_density_receipt_are_bound() -> None:
    contract = model.validate_contract(ROOT)
    assert contract["strategy_id"] == model.CANDIDATE_ID
    assert contract["classification"] == "INTERNAL_BASELINE_DEV_ONLY"


def test_entry_is_next_open_and_stop_is_adverse_first() -> None:
    data = bars()
    signal_at(data)
    data.loc[5, "low"] = 95.0
    result = model.replay_symbol("BTC-USDT", data, 14.0, start_ms=0, end_ms=len(data) * HOUR)
    assert result["raw_signals"] == 1
    assert result["completed"] == 1
    trade = result["trades"][0]
    assert trade["entry_ts_ms"] == 5 * HOUR
    assert trade["signal_available_ts_ms"] == 5 * HOUR
    assert trade["exit_reason"] == "STOP_FIRST"
    assert trade["exit_price"] == 96.0
    assert trade["cost_bps"] == 16.0
    assert trade["funding_reserve_bps_embedded"] == 3.0


def test_timeout_is_exactly_24_hours_after_entry() -> None:
    data = bars()
    signal_at(data)
    data.loc[5:29, "low"] = 97.0
    result = model.replay_symbol("ETH-USDT", data, 14.0, start_ms=0, end_ms=len(data) * HOUR)
    trade = result["trades"][0]
    assert trade["exit_reason"] == "FIXED_24H_TIMEOUT"
    assert trade["exit_ts_ms"] - trade["entry_ts_ms"] == 24 * HOUR
    assert trade["holding_hours"] == 24.0


def test_adverse_gap_stop_has_priority_at_timeout_open() -> None:
    data = bars()
    signal_at(data)
    data.loc[5:28, "low"] = 97.0
    data.loc[29, ["open", "high", "low", "close"]] = [95.0, 96.0, 94.0, 95.0]
    result = model.replay_symbol("ETH-USDT", data, 14.0, start_ms=0, end_ms=len(data) * HOUR)
    trade = result["trades"][0]
    assert trade["exit_ts_ms"] - trade["entry_ts_ms"] == 24 * HOUR
    assert trade["exit_reason"] == "ADVERSE_GAP_STOP"
    assert trade["exit_price"] == 95.0


def test_signal_while_occupied_is_not_queued() -> None:
    data = bars(60)
    signal_at(data, 4)
    signal_at(data, 10)
    data.loc[5:29, "low"] = 97.0
    result = model.replay_symbol("SOL-USDT", data, 14.0, start_ms=0, end_ms=len(data) * HOUR)
    assert result["raw_signals"] == 2
    assert result["missed_occupied"] == 1
    assert result["completed"] == 1


def test_gap_and_late_availability_do_not_invent_fills() -> None:
    gap = bars()
    signal_at(gap)
    gap.loc[5:, "segment_id"] = "B"
    result = model.replay_symbol("XRP-USDT", gap, 14.0, start_ms=0, end_ms=len(gap) * HOUR)
    assert result["gap_quarantined"] == 1
    assert result["completed"] == 0

    late = bars()
    signal_at(late)
    late.loc[4, "available_ts_ms"] = 5 * HOUR + 1
    result = model.replay_symbol("XRP-USDT", late, 14.0, start_ms=0, end_ms=len(late) * HOUR)
    assert result["missing_fill_evidence"] == 1
    assert result["completed"] == 0


def test_common_runner_profile_is_bound_and_auditable(monkeypatch) -> None:
    data = bars()
    signal_at(data)
    data.loc[5, "low"] = 95.0
    market = {
        "frames": {symbol: data.copy() for symbol in common.SYMBOLS},
        "costs": {symbol: 14.0 for symbol in common.SYMBOLS},
    }
    monkeypatch.setattr(common, "START_MS", 0)
    monkeypatch.setattr(common, "END_MS", len(data) * HOUR)
    profile = common.profile_for(model.CANDIDATE_ID)
    assert profile["source_sha256"] == model.CONTRACT_SHA256
    result = common.screen(market, profile)
    assert result["candidate_id"] == model.CANDIDATE_ID
    assert result["cost_1x"]["T"] == len(common.SYMBOLS)
    assert result["cost_2x"]["CostExp_bps_T"] == 32.0
    assert result["classification"].startswith("INTERNAL_BASELINE_")
    saved = dict(result)
    supplied = saved.pop("result_sha256")
    assert supplied == common.digest(saved)
    common.audit_internal_three_red_result(saved, market)

