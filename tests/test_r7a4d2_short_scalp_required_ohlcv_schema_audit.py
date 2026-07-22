from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_REQUIRED_OHLCV_SCHEMA_AUDIT"])
    spec = importlib.util.spec_from_file_location("required_ohlcv_schema_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def records(count: int = 640):
    return [
        {
            "open_time": 1_700_000_000_000 + index * 60_000,
            "o": 100 + index * 0.01,
            "h": 101 + index * 0.01,
            "l": 99 + index * 0.01,
            "c": 100.5 + index * 0.01,
            "v": 10 + index,
        }
        for index in range(count)
    ]


def best(module, value):
    candidates = module.collect_candidates(value)
    assert candidates
    candidates.sort(key=lambda row: (-int(row.get("score", 0)), str(row.get("container_path") or "")))
    return candidates[0]


def test_nested_record_list_detects_alias_mapping() -> None:
    module = load_module()
    candidate = best(module, {"symbol": "BTCUSDT", "interval": "1m", "data": records()})
    quality = module.sample_quality(candidate)
    assert candidate["adapter_class"] == "RECORD_LIST"
    assert candidate["container_path"] == "$.data"
    assert candidate["row_count"] == 640
    assert set(module.REQUIRED_FIELDS).issubset(candidate["mapping"])
    assert quality["numeric_ohlc_ratio"] == 1.0
    assert quality["timestamp_present_ratio"] == 1.0
    assert quality["ohlc_geometry_valid_ratio"] == 1.0


def test_columns_matrix_detects_indices() -> None:
    module = load_module()
    rows = [[row["open_time"], row["o"], row["h"], row["l"], row["c"], row["v"]] for row in records()]
    candidate = best(module, {"columns": ["open_time", "o", "h", "l", "c", "v"], "values": rows})
    quality = module.sample_quality(candidate)
    assert candidate["adapter_class"] == "COLUMN_MATRIX"
    assert candidate["index_mapping"]["close"] == 4
    assert quality["numeric_ohlc_ratio"] == 1.0
    assert quality["timestamp_present_ratio"] == 1.0


def test_columnar_arrays_detects_and_samples() -> None:
    module = load_module()
    source = records()
    value = {
        "timestamp": [row["open_time"] for row in source],
        "open": [row["o"] for row in source],
        "high": [row["h"] for row in source],
        "low": [row["l"] for row in source],
        "close": [row["c"] for row in source],
        "volume": [row["v"] for row in source],
    }
    candidate = best(module, value)
    quality = module.sample_quality(candidate)
    assert candidate["adapter_class"] == "COLUMNAR_ARRAYS"
    assert candidate["row_count"] == 640
    assert quality["numeric_ohlc_ratio"] == 1.0
    assert quality["timestamp_present_ratio"] == 1.0


def test_timestamp_keyed_row_map_detects_timestamp_from_key() -> None:
    module = load_module()
    value = {
        str(row["open_time"]): {"open": row["o"], "high": row["h"], "low": row["l"], "close": row["c"]}
        for row in records()
    }
    candidate = best(module, {"rows": value})
    quality = module.sample_quality(candidate)
    assert candidate["adapter_class"] == "TIMESTAMP_KEYED_ROW_MAP"
    assert candidate["mapping"]["timestamp"] == "__row_key__"
    assert quality["timestamp_present_ratio"] == 1.0
    assert quality["numeric_ohlc_ratio"] == 1.0


def test_build_audit_passes_when_all_required_sources_are_ready() -> None:
    module = load_module()
    required_paths = [f"data/S{i}.json" for i in range(5)]
    frozen = {"state": "PASS"}
    selected = {
        "state": "PASS",
        "selected_segments": [{"source_path": path} for path in required_paths],
    }
    inspected = [
        {
            "path": path,
            "adapter_ready": True,
            "schema_signature": "same-signature",
            "adapter_class": "RECORD_LIST",
        }
        for path in required_paths
    ]
    audit, blockers = module.build_audit(frozen, selected, inspected, [])
    assert blockers == []
    assert audit["state"] == "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT"
    assert audit["adapter_ready_source_count"] == 5
    assert audit["single_shared_schema"] is True
    assert audit["next_stage"] == "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"


def test_unresolved_required_source_fail_closes() -> None:
    module = load_module()
    selected = {
        "state": "PASS",
        "selected_segments": [{"source_path": "data/BTC.json"}],
    }
    audit, blockers = module.build_audit(
        {"state": "PASS"},
        selected,
        [{"path": "data/BTC.json", "adapter_ready": False}],
        [],
    )
    assert any(item.startswith("REQUIRED_SCHEMA_UNRESOLVED") for item in blockers)
    assert audit["state"] == "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT_INPUT"
