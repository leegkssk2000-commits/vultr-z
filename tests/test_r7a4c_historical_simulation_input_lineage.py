from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools/r7a4c_historical_simulation_input_lineage.py"
spec = importlib.util.spec_from_file_location("r7a4c_lineage_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def complete_a4b_status() -> dict:
    return {
        "official_stage": "R7.A4B",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": 25,
        "strategy_import_count": 25,
        "strategy_pass_count": 25,
        "fixture_count": 4,
        "repeat_count": 2,
        "deterministic_pair_count": 100,
        "dry_run_call_count": 200,
        "successful_call_count": 200,
        "side_effect_attempt_count": 0,
        "canonical_input_parity_count": 28,
        "historical_market_data_used_count": 0,
        "execution_cost_model_applied_count": 0,
        "historical_replay_execution_count": 0,
        "active_entry_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": "R7.A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE",
        "dry_run_input_set_id": "dry-run-id",
    }


def market_contract() -> dict:
    return {
        "market_required_columns": ["open", "high", "low", "close"],
        "timestamp_aliases": ["timestamp", "ts"],
        "symbol_aliases": ["symbol"],
        "timeframe_aliases": ["timeframe"],
    }


def test_prior_gate_is_exact() -> None:
    status = complete_a4b_status()
    assert module.prior_gate(status, 25) is True
    status["successful_call_count"] = 199
    assert module.prior_gate(status, 25) is False


def test_market_frame_normalization() -> None:
    frame = pd.DataFrame(
        {
            "Timestamp": [3, 1, 2, 2],
            "Open": [103, 100, 101, 101],
            "High": [104, 101, 103, 103],
            "Low": [102, 99, 100, 100],
            "Close": [103.5, 100.5, 102, 102],
            "Symbol": ["BTCUSDT"] * 4,
            "Timeframe": ["5m"] * 4,
        }
    )
    normalized, metadata = module.normalize_market_frame(frame, market_contract())
    assert len(normalized) == 3
    assert normalized["__timestamp"].tolist() == [1, 2, 3]
    assert metadata["symbol"] == "BTCUSDT"
    assert metadata["timeframe"] == "5m"


def test_market_frame_normalization_accepts_mixed_case() -> None:
    frame = pd.DataFrame(
        {
            "Ts": [1, 2],
            "oPeN": [100, 101],
            "HIGH": [102, 103],
            "low": [99, 100],
            "Close": [101, 102],
        }
    )
    normalized, metadata = module.normalize_market_frame(frame, market_contract())
    assert normalized[["open", "high", "low", "close"]].shape == (2, 4)
    assert metadata["timestamp_column"] == "ts"


def test_market_frame_normalization_rejects_casefold_collision() -> None:
    frame = pd.DataFrame(
        [[1, 100, 101, 102, 99, 101]],
        columns=["timestamp", "Open", "open", "High", "Low", "Close"],
    )
    with pytest.raises(ValueError, match="MARKET_COLUMN_COLLISION:open"):
        module.normalize_market_frame(frame, market_contract())


def make_segment(index: int, ret: float, trend: float, drawdown: float, recovery: float) -> dict:
    return {
        "segment_id": f"segment-{index:03d}",
        "source_path": "data.csv",
        "source_sha256": "abc",
        "start_row": index * 320,
        "end_row_exclusive": (index + 1) * 320,
        "bars": 320,
        "start_timestamp": str(index * 320),
        "end_timestamp": str((index + 1) * 320 - 1),
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "metrics": {
            "return": ret,
            "volatility": 0.01,
            "trend_score": trend,
            "max_drawdown": drawdown,
            "recovery": recovery,
            "shock_score": abs(drawdown) + max(recovery, 0),
        },
    }


def test_regime_selection_produces_24_unique_segments() -> None:
    segments = []
    for index in range(8):
        segments.append(make_segment(index, 0.10 + index * 0.01, 2.0 + index, -0.02, 0.03))
    for index in range(8, 16):
        segments.append(make_segment(index, -0.10 - index * 0.005, -2.0 - index, -0.03, 0.01))
    for index in range(16, 24):
        segments.append(make_segment(index, 0.001 * (index - 20), 0.01 * (index - 20), -0.01, 0.01))
    for index in range(24, 32):
        segments.append(make_segment(index, 0.02, 0.2, -0.25 - index * 0.001, 0.30 + index * 0.001))
    regimes = ["trend_up", "range", "trend_down", "shock_recovery"]
    selected, coverage = module.select_regime_segments(segments, regimes, 6)
    assert len(selected) == 24
    assert len({row["segment_id"] for row in selected}) == 24
    assert coverage == {"shock_recovery": 6, "trend_up": 6, "trend_down": 6, "range": 6}


def test_execution_cost_axis_coverage() -> None:
    rows = [
        {"tokens": ["commission", "slippage"]},
        {"tokens": ["latency", "funding"]},
    ]
    assert module.axis_coverage(rows) == {
        "fee": True,
        "slippage": True,
        "latency": True,
        "funding": True,
    }


def test_scenario_math_is_3600() -> None:
    assert 25 * (4 * 6) * 3 * 2 == 3600
