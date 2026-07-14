from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_preentry_method_context_capture.py"
SPEC = importlib.util.spec_from_file_location("preentry_capture", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_context_join_is_strictly_preentry_and_fresh() -> None:
    rows = [
        {"symbol": "BTCUSDT", "bar_epoch": 100.0, "value": "old"},
        {"symbol": "BTCUSDT", "bar_epoch": 119.0, "value": "fresh"},
        {"symbol": "BTCUSDT", "bar_epoch": 121.0, "value": "future"},
    ]
    selected, age = MODULE.context_before_entry(rows, "BTCUSDT", 120.0)
    assert selected is not None
    assert selected["value"] == "fresh"
    assert age == 1.0

    selected, age = MODULE.context_before_entry(rows[:1], "BTCUSDT", 400.0)
    assert selected is None
    assert age == 300.0


def test_append_rows_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "capture.jsonl"
    row = {"position_id": "p1", "value": 1}
    assert MODULE.append_rows(ledger, [row]) == 1
    assert MODULE.append_rows(ledger, [row]) == 0
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_build_capture_is_method_neutral_and_cost_traced() -> None:
    position = {
        "position_id": "p1",
        "strategy_id": "alpha_combo",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_epoch": 1_800_000_000.0,
        "entry_price": 100.0,
        "stop_price": 99.0,
        "take_profit_price": 102.0,
        "qty": 0.01,
        "entry_features": {"session_window": "newyork", "htf_bias": "long"},
    }
    context = {
        "symbol": "BTCUSDT",
        "bar_epoch": 1_799_999_990.0,
        "atr_pct": 1.5,
        "realized_volatility_pct": 2.0,
        "funding_8h_pct": 0.01,
        "spread_bps": 1.2,
        "trend_direction": "long",
        "trend_strength": 1.5,
    }
    execution = {
        "fee_bps_round_trip": 10.0,
        "slippage_bps_round_trip": 2.0,
        "interpretation": {"fee": "test", "slippage": "test"},
    }
    activation = {"activation_at": "2026-07-14T00:00:00+00:00"}
    row = MODULE.build_capture(position, context, 10.0, execution, activation)
    assert row["method"] is None
    assert row["method_subtype"] is None
    assert row["method_neutral"] is True
    assert row["historical_backfill"] is False
    assert row["expected_gross_edge_bps"] == 200.0
    assert row["expected_stop_distance_bps"] == 100.0
    assert row["planned_target_r"] == 2.0
    assert row["fee_bps_round_trip"] == 10.0
    assert row["slippage_bps"] == 2.0
    assert row["regime"] == "trend_long"


def test_extract_positions_deduplicates_by_position_id() -> None:
    payload = {
        "positions": {
            "a": {"position_id": "p1", "symbol": "BTCUSDT", "entry_epoch": 1_800_000_000.0},
            "b": {"position_id": "p1", "symbol": "BTCUSDT", "entry_epoch": 1_800_000_000.0},
        }
    }
    positions = MODULE.extract_positions(payload)
    assert len(positions) == 1
    assert positions[0]["position_id"] == "p1"
