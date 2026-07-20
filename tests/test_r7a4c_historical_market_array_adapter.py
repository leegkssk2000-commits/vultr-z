from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools/r7a4c_historical_simulation_input_lineage_entry.py"
spec = importlib.util.spec_from_file_location("r7a4c_array_adapter_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def build_rows(count: int = 400) -> list[list[float]]:
    rows: list[list[float]] = []
    previous_close = 100.0
    for index in range(count):
        timestamp = 1_700_000_000_000 + index * 60_000
        open_ = previous_close
        close = open_ + ((index % 9) - 4) * 0.03
        high = max(open_, close) + 0.25 + (index % 3) * 0.01
        low = min(open_, close) - 0.22 - (index % 2) * 0.01
        volume = 1000.0 + index * 1.5
        rows.append([timestamp, open_, high, low, close, volume])
        previous_close = close
    return rows


def test_infer_standard_six_column_ohlcv_schema() -> None:
    schema = module.infer_ohlcv_array_schema(build_rows())
    assert schema == {
        "timestamp": 0,
        "open": 1,
        "high": 2,
        "low": 3,
        "close": 4,
        "volume": 5,
    }


def test_price_cluster_prevents_volume_high_confusion() -> None:
    shuffled = []
    for timestamp, open_, high, low, close, volume in build_rows():
        shuffled.append([timestamp, open_, volume, low, close, high])
    schema = module.infer_ohlcv_array_schema(shuffled)
    assert schema == {
        "timestamp": 0,
        "open": 1,
        "high": 5,
        "low": 3,
        "close": 4,
        "volume": 2,
    }


def test_decode_root_rows_with_metadata(tmp_path: Path) -> None:
    path = tmp_path / "market.json"
    rows = build_rows()
    path.write_text(
        json.dumps(
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "row_count": len(rows),
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    frame = module.decode_nested_market_json(path)
    assert frame is not None
    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    assert len(frame) == len(rows)
    assert frame["symbol"].iloc[0] == "BTCUSDT"
    assert frame["timeframe"].iloc[0] == "1m"
    assert frame.attrs["array_schema"]["timestamp"] == 0


def test_decode_rejects_declared_row_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "market.json"
    rows = build_rows()
    path.write_text(json.dumps({"row_count": len(rows) + 1, "rows": rows}), encoding="utf-8")
    with pytest.raises(ValueError, match="MARKET_ROW_COUNT_MISMATCH"):
        module.decode_nested_market_json(path)


def test_schema_inference_is_fail_closed_for_ambiguous_rows() -> None:
    rows = []
    for index in range(100):
        timestamp = 1_700_000_000_000 + index * 60_000
        rows.append([timestamp, 100.0, 100.0, 100.0, 100.0, 100.0])
    with pytest.raises(ValueError, match="MARKET_OHLCV_SCHEMA_AMBIGUOUS"):
        module.infer_ohlcv_array_schema(rows)
