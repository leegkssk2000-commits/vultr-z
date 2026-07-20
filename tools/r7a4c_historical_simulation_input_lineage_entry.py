#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).with_name("r7a4c_historical_simulation_input_lineage.py")


def _numeric_matrix(rows: list[Any], width: int = 6, sample_limit: int = 2000) -> np.ndarray:
    sample = rows[:sample_limit]
    if len(sample) < 20 or any(not isinstance(row, list) or len(row) != width for row in sample):
        raise ValueError("MARKET_ARRAY_ROWS_INVALID")
    try:
        matrix = np.asarray(sample, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("MARKET_ARRAY_ROWS_NON_NUMERIC") from exc
    if matrix.ndim != 2 or matrix.shape[1] != width or not np.isfinite(matrix).all():
        raise ValueError("MARKET_ARRAY_ROWS_NON_FINITE")
    return matrix


def _timestamp_index(matrix: np.ndarray) -> int:
    candidates: list[tuple[float, int]] = []
    for index in range(matrix.shape[1]):
        values = matrix[:, index]
        diffs = np.diff(values)
        if diffs.size == 0:
            continue
        increasing_ratio = float(np.mean(diffs > 0))
        positive_step = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 0.0
        magnitude = float(np.median(np.abs(values)))
        if increasing_ratio >= 0.98 and positive_step > 0 and magnitude >= 1e8:
            candidates.append((increasing_ratio, index))
    if len(candidates) != 1:
        raise ValueError(f"MARKET_TIMESTAMP_SCHEMA_AMBIGUOUS:{[index for _, index in candidates]}")
    return candidates[0][1]


def _mapping_score(matrix: np.ndarray, mapping: tuple[int, int, int, int, int]) -> tuple[float, float]:
    open_i, high_i, low_i, close_i, volume_i = mapping
    open_v = matrix[:, open_i]
    high_v = matrix[:, high_i]
    low_v = matrix[:, low_i]
    close_v = matrix[:, close_i]
    volume_v = matrix[:, volume_i]
    valid = (
        (open_v > 0)
        & (high_v > 0)
        & (low_v > 0)
        & (close_v > 0)
        & (volume_v >= 0)
        & (high_v >= np.maximum(open_v, close_v))
        & (low_v <= np.minimum(open_v, close_v))
        & (high_v >= low_v)
    )
    valid_ratio = float(np.mean(valid))
    scale = max(float(np.median(np.abs(close_v))), 1e-12)
    continuity = float(np.median(np.abs(open_v[1:] - close_v[:-1])) / scale)
    return valid_ratio, continuity


def infer_ohlcv_array_schema(rows: list[Any]) -> dict[str, int]:
    matrix = _numeric_matrix(rows)
    timestamp_i = _timestamp_index(matrix)
    remaining = [index for index in range(matrix.shape[1]) if index != timestamp_i]
    ranked: list[tuple[float, float, tuple[int, int, int, int, int]]] = []
    for mapping in itertools.permutations(remaining, 5):
        valid_ratio, continuity = _mapping_score(matrix, mapping)
        if valid_ratio >= 0.995 and math.isfinite(continuity):
            ranked.append((valid_ratio, -continuity, mapping))
    if not ranked:
        raise ValueError("MARKET_OHLCV_SCHEMA_NOT_RESOLVED")
    ranked.sort(reverse=True)
    best = ranked[0]
    if len(ranked) > 1:
        second = ranked[1]
        valid_margin = best[0] - second[0]
        continuity_margin = best[1] - second[1]
        if valid_margin < 1e-9 and continuity_margin < 1e-9:
            raise ValueError("MARKET_OHLCV_SCHEMA_AMBIGUOUS")
    open_i, high_i, low_i, close_i, volume_i = best[2]
    return {
        "timestamp": timestamp_i,
        "open": open_i,
        "high": high_i,
        "low": low_i,
        "close": close_i,
        "volume": volume_i,
    }


def decode_nested_market_json(path: Path) -> pd.DataFrame | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None
    rows = payload["rows"]
    if not rows:
        raise ValueError("MARKET_ARRAY_ROWS_EMPTY")
    first = rows[0]
    if isinstance(first, dict):
        frame = pd.DataFrame(rows)
    elif isinstance(first, list):
        schema = infer_ohlcv_array_schema(rows)
        frame = pd.DataFrame(
            {
                name: [row[index] for row in rows]
                for name, index in schema.items()
            }
        )
        frame.attrs["array_schema"] = schema
    else:
        raise ValueError("MARKET_ARRAY_ROW_TYPE_INVALID")
    symbol = payload.get("symbol")
    timeframe = payload.get("interval") or payload.get("timeframe")
    if symbol is not None and "symbol" not in frame.columns:
        frame["symbol"] = str(symbol)
    if timeframe is not None and "timeframe" not in frame.columns:
        frame["timeframe"] = str(timeframe)
    declared_count = payload.get("row_count")
    if declared_count is not None and int(declared_count) != len(frame):
        raise ValueError(f"MARKET_ROW_COUNT_MISMATCH:{declared_count}:{len(frame)}")
    return frame


def load_market_frame_compat(path: Path, fallback: Callable[[Path], pd.DataFrame]) -> pd.DataFrame:
    if path.suffix.lower() == ".json":
        decoded = decode_nested_market_json(path)
        if decoded is not None:
            return decoded
    return fallback(path)


def load_runner():
    spec = importlib.util.spec_from_file_location("r7a4c_lineage_runner", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("R7A4C_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original = module.load_market_frame
    module.load_market_frame = lambda path: load_market_frame_compat(path, original)
    return module


def main() -> int:
    return int(load_runner().main())


if __name__ == "__main__":
    raise SystemExit(main())
