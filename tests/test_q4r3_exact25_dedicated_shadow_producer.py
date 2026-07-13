from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pandas as pd

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_dedicated_shadow_producer.py"
SPEC = importlib.util.spec_from_file_location("q4r3_exact25_dedicated_shadow_producer", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_frame() -> pd.DataFrame:
    rows = 240
    timestamps = pd.date_range("2026-07-13T00:00:00Z", periods=rows, freq="min")
    close = [100.0 + index * 0.01 for index in range(rows)]
    return pd.DataFrame({
        "timestamp_ms": [int(ts.timestamp() * 1000) for ts in timestamps],
        "timestamp": timestamps,
        "open": [value - 0.02 for value in close],
        "high": [value + 0.10 for value in close],
        "low": [value - 0.10 for value in close],
        "close": close,
        "volume": [1000.0] * rows,
    })


def test_feature_snapshot_is_observer_only() -> None:
    features = MODULE.feature_snapshot(sample_frame())
    assert features["observer_only"] is True
    assert features["htf_bias"] in {"long", "short", "neutral"}
    assert features["premium_discount_side"] in {"premium", "discount"}
    assert isinstance(features["ltf_reversal_confirm"], bool)


def test_valid_long_entry_and_position_risk() -> None:
    frame = sample_frame()
    result = {
        "action": "enter",
        "side": "long",
        "entry": 102.39,
        "sl": 101.39,
        "tp": 104.39,
        "size": 0.5,
        "why": "test",
        "skill": "none",
        "confidence": 0.7,
    }
    position = MODULE.make_position(
        "alpha_combo",
        "a" * 64,
        "BTCUSDT",
        "1m",
        result,
        frame,
        1.0,
        0.0005,
        1.0,
    )
    assert position is not None
    assert position["side"] == "long"
    assert abs(position["initial_risk_usdt"] - 1.0) < 1e-12
    assert abs(position["qty"] - 1.0) < 1e-12
    assert position["paper_enabled"] is False
    assert position["live_enabled"] is False
    assert position["order_enabled"] is False


def test_same_bar_stop_is_conservative() -> None:
    position = {
        "side": "long",
        "stop_price": 99.0,
        "take_profit_price": 102.0,
        "entry_epoch": 1_783_900_000.0,
    }
    result = MODULE.bar_exit(
        position,
        {"high": 103.0, "low": 98.0, "close": 101.0},
        1_783_900_060.0,
        120.0,
    )
    assert result == (99.0, "same_bar_stop_first")


def test_close_row_has_exact_r_formula() -> None:
    position = {
        "position_id": "exact25.shadow.test",
        "strategy_id": "alpha_combo",
        "owner_sha256": "b" * 64,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_ts": "2026-07-13T04:00:00+00:00",
        "entry_epoch": 1_783_913_600.0,
        "entry_price": 100.0,
        "stop_price": 99.0,
        "take_profit_price": 102.0,
        "qty": 1.0,
        "initial_risk_usdt": 1.0,
        "gross_realized_partial": 0.0,
        "fee_accum": 0.0,
        "slippage_accum": 0.0,
        "add_count": 0,
        "partial_count": 0,
        "max_favorable_usdt": 2.0,
        "max_adverse_usdt": -0.5,
        "entry_features": {"observer_only": True},
    }
    row = MODULE.close_position(
        position,
        102.0,
        "2026-07-13T04:30:00+00:00",
        "take_profit",
        {"htf_bias": "long", "observer_only": True},
        0.0,
        0.0,
    )
    assert row["realized_pnl_usdt"] == 2.0
    assert row["realized_R"] == row["realized_pnl_usdt"] / row["initial_risk_usdt"]
    assert row["MFE_R"] == 2.0
    assert row["MAE_R"] == -0.5
    assert row["mode"] == "shadow"
    assert row["paper_enabled"] is False
    assert row["live_enabled"] is False
    assert row["order_enabled"] is False


def test_close_surface_is_deduplicated(tmp_path: Path) -> None:
    path = tmp_path / "close_latest.json"
    row = {"event_id": "e1", "strategy_id": "alpha_combo", "status": "CLOSED"}
    MODULE.publish_close_surface(path, row)
    MODULE.publish_close_surface(path, row)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 1
    assert len(payload["rows"]) == 1


def test_source_contains_no_private_or_order_calls() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {
        "create_order", "create_market_order", "create_limit_order", "cancel_order",
        "cancel_all_orders", "set_leverage", "set_margin_mode", "fetch_balance",
        "fetch_positions", "fetch_open_orders", "private_get", "private_post",
    }
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden:
                found.add(node.func.attr)
    assert found == set()


def test_symbol_parser_defaults_to_core_four() -> None:
    assert MODULE.parse_symbols("") == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
