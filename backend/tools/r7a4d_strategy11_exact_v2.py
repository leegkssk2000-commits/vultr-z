from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
V1_PATH = ROOT / "backend/tools/r7a4d_strategy11_exact.py"
CACHE_ROOT = ROOT / "artifacts/strategy11_market_cache_v2"
ANCHOR_ENDS = (
    "2026-03-01T00:00:00Z",
    "2026-03-13T00:00:00Z",
    "2026-03-25T00:00:00Z",
    "2026-04-06T00:00:00Z",
    "2026-04-18T00:00:00Z",
    "2026-04-30T00:00:00Z",
    "2026-05-12T00:00:00Z",
    "2026-05-24T00:00:00Z",
    "2026-06-05T00:00:00Z",
    "2026-06-17T00:00:00Z",
)
WINDOW_ROLES = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
WINDOW_BARS = 900
INTERVAL_MS = 900_000


def _load_v1() -> Any:
    name = "r7a4d_strategy11_exact_v1_for_cache_v2"
    spec = importlib.util.spec_from_file_location(name, V1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("EXACT_V1_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _role_for_bounds(start_ms: int, end_ms: int, expected_rows: int) -> str:
    if expected_rows != WINDOW_BARS:
        raise ValueError(f"CACHE_EXPECTED_ROWS:{expected_rows}!={WINDOW_BARS}")
    for role, anchor in zip(WINDOW_ROLES, ANCHOR_ENDS):
        candidate_end = int(pd.Timestamp(anchor).timestamp() * 1000)
        candidate_end = (candidate_end // INTERVAL_MS) * INTERVAL_MS
        candidate_start = candidate_end - (WINDOW_BARS - 1) * INTERVAL_MS
        if start_ms == candidate_start and end_ms == candidate_end:
            return role
    raise ValueError(f"CACHE_WINDOW_NOT_FOUND:{start_ms}:{end_ms}")


def _cached_fetch(symbol: str, *, start_ms: int, end_ms: int, expected_rows: int):
    role = _role_for_bounds(start_ms, end_ms, expected_rows)
    path = CACHE_ROOT / f"{role}-{symbol}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"CACHE_FILE_MISSING:{path}")
    frame = pd.read_csv(path)
    if len(frame) != expected_rows:
        raise ValueError(f"CACHE_ROWS:{len(frame)}!={expected_rows}")
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    elif "timestamp_ms" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    else:
        raise ValueError("CACHE_TIMESTAMP_MISSING")
    if "ts" not in frame.columns and "timestamp_ms" in frame.columns:
        frame["ts"] = frame["timestamp_ms"]
    return frame, "SHARED_CACHE_V2", 0


def main() -> int:
    v1 = _load_v1()
    v1.ANCHOR_ENDS = ANCHOR_ENDS
    v1.WINDOW_ROLES = WINDOW_ROLES
    v1.WINDOW_BARS = WINDOW_BARS
    v1.base._fetch_exact = _cached_fetch
    return int(v1.main())


if __name__ == "__main__":
    raise SystemExit(main())
