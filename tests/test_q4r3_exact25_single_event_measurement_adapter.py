from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.q4r3_exact25_single_event_measurement_adapter import (
    append_exactly_once,
    count_valid_rows,
    manifest_owner_map,
    select_event,
    validate_event,
)


def manifest(owner: str = "a" * 64) -> dict:
    return {
        "strategies": [
            {
                "strategy_id": f"strategy_{index:02d}",
                "owner_sha256": owner if index == 0 else f"{index:064x}",
            }
            for index in range(25)
        ]
    }


def close_row(owner: str = "a" * 64) -> dict:
    return {
        "schema": "q4r3_exact25_dedicated_shadow_close_v1",
        "event_id": "exact25.shadow.test:close",
        "position_id": "exact25.shadow.test",
        "event_type": "CLOSED",
        "status": "CLOSED",
        "state": "CLOSED",
        "closed": True,
        "mode": "shadow",
        "shadow": True,
        "source": "q4r3_exact25_dedicated_shadow_producer",
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "strategy_id": "strategy_00",
        "owner_sha256": owner,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_ts": "2026-07-13T14:00:00+00:00",
        "exit_ts": "2026-07-13T14:05:00+00:00",
        "captured_at": "2026-07-13T14:05:01+00:00",
        "entry_price": 100.0,
        "stop_price": 99.0,
        "take_profit_price": 102.0,
        "exit_price": 102.0,
        "qty": 1.0,
        "initial_risk_usdt": 1.0,
        "realized_pnl_usdt": 1.8,
        "realized_R": 1.8,
        "fee": 0.1,
        "slippage": 0.1,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def test_select_latest_and_validate_owner_formula() -> None:
    owners = manifest_owner_map(manifest())
    older = close_row()
    older["event_id"] = "older:close"
    older["captured_at"] = "2026-07-13T14:04:01+00:00"
    latest = close_row()
    selected = select_event({"rows": [older, latest]}, None)
    assert selected["event_id"] == latest["event_id"]
    normalized = validate_event(selected, owners, min_event_epoch=1_700_000_000.0)
    assert normalized["formula_verified"] is True
    assert normalized["owner_lineage_verified"] is True


def test_exact_one_append_then_duplicate_rejected(tmp_path: Path) -> None:
    owners = manifest_owner_map(manifest())
    row = validate_event(close_row(), owners, min_event_epoch=None)
    ledger = tmp_path / "ledger.jsonl"
    assert append_exactly_once(ledger, row) is True
    assert count_valid_rows(ledger) == 1
    assert append_exactly_once(ledger, row) is False
    assert count_valid_rows(ledger) == 1


def test_formula_mismatch_is_blocked() -> None:
    owners = manifest_owner_map(manifest())
    row = close_row()
    row["realized_R"] = 9.0
    with pytest.raises(RuntimeError, match="REALIZED_R_FORMULA_MISMATCH"):
        validate_event(row, owners, min_event_epoch=None)


def test_owner_mismatch_is_blocked() -> None:
    owners = manifest_owner_map(manifest())
    row = close_row(owner="b" * 64)
    with pytest.raises(RuntimeError, match="OWNER_SHA_MISMATCH"):
        validate_event(row, owners, min_event_epoch=None)


def test_unsafe_execution_flag_is_blocked() -> None:
    owners = manifest_owner_map(manifest())
    row = close_row()
    row["paper_enabled"] = True
    with pytest.raises(RuntimeError, match="UNSAFE_EVENT_FLAG"):
        validate_event(row, owners, min_event_epoch=None)
