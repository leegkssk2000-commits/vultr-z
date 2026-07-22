from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_ROWS_SCHEMA_DIAGNOSE"])
    spec = importlib.util.spec_from_file_location("rows_schema_diagnose", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binance_rows(count: int = 700) -> list[list[float]]:
    rows = []
    previous_close = 100.0
    for index in range(count):
        timestamp = 1_700_000_000_000 + index * 60_000
        open_v = previous_close
        close_v = open_v + (0.03 if index % 2 == 0 else -0.02)
        high_v = max(open_v, close_v) + 0.05
        low_v = min(open_v, close_v) - 0.05
        # Auxiliary zero-volume column must not be eligible as a positive OHLC price.
        volume = 0.0
        rows.append([timestamp, open_v, high_v, low_v, close_v, volume])
        previous_close = close_v
    return rows


def test_binance_matrix_layout_is_identified() -> None:
    module = load_module()
    result = module.diagnose_matrix_rows(binance_rows())
    assert result["layout_ready"] is True
    top = result["layout_candidates"][0]
    assert top["timestamp_index"] == 0
    assert top["open_index"] == 1
    assert top["high_index"] == 2
    assert top["low_index"] == 3
    assert top["close_index"] == 4
    assert top["continuity_profile"]["exact_link_ratio"] == 1.0


def test_open_close_swap_is_resolved_by_bar_continuity() -> None:
    module = load_module()
    altered_rows = [[row[0], row[4], row[2], row[3], row[1], row[5]] for row in binance_rows()]
    result = module.diagnose_matrix_rows(altered_rows)
    assert result["layout_ready"] is True
    top = result["layout_candidates"][0]
    assert top["open_index"] == 4
    assert top["close_index"] == 1
    assert top["continuity_profile"]["exact_link_ratio"] == 1.0


def test_dict_rows_are_not_guessed_as_matrix() -> None:
    module = load_module()
    result = module.diagnose_matrix_rows([{"t": 1, "o": 2}] * 700)
    assert result["layout_ready"] is False
    assert result["reason"] == "ROWS_NOT_MATRIX"


def test_non_monotonic_timestamp_prevents_layout_ready() -> None:
    module = load_module()
    rows = binance_rows()
    for index, row in enumerate(rows):
        row[0] = 1_700_000_000_000 + (index % 3) * 60_000
    result = module.diagnose_matrix_rows(rows)
    assert result["layout_ready"] is False


def test_shared_layout_passes_audit() -> None:
    module = load_module()
    inspected = []
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        result = module.diagnose_matrix_rows(binance_rows())
        inspected.append({"path": symbol, **result})
    frozen = {"state": "PASS"}
    selected = {
        "state": "PASS",
        "selected_segments": [{"source_path": symbol} for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")],
    }
    audit, blockers = module.build_audit(frozen, selected, inspected, [])
    assert blockers == []
    assert audit["shared_layout"] is True
    assert audit["next_stage"] == "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"


def test_layout_divergence_blocks() -> None:
    module = load_module()
    first = module.diagnose_matrix_rows(binance_rows())
    altered_rows = [[row[0], row[4], row[2], row[3], row[1], row[5]] for row in binance_rows()]
    second = module.diagnose_matrix_rows(altered_rows)
    inspected = [{"path": "A", **first}, {"path": "B", **second}]
    selected = {"state": "PASS", "selected_segments": [{"source_path": "A"}, {"source_path": "B"}]}
    _, blockers = module.build_audit({"state": "PASS"}, selected, inspected, [])
    assert any(item.startswith("REQUIRED_SOURCE_LAYOUT_DIVERGENCE") for item in blockers)
