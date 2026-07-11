from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_second_holdout_gap_repair.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_gap_repair", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _row(stamp: int) -> dict[str, float]:
    return {
        "ts": stamp,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
    }


def test_contiguous_missing_range_is_repaired_without_interpolation(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = MODULE.BASE.MINUTE_MS
    start = 1_000_000_000_000
    end = start + 19 * minute
    missing = {start + offset * minute for offset in (8, 9, 10, 11)}
    candles = {
        stamp: _row(stamp)
        for stamp in range(start, end + minute, minute)
        if stamp not in missing
    }

    calls: list[int] = []

    def fake_fetch(_symbol: str, anchor: int):
        calls.append(anchor)
        return [_row(stamp) for stamp in sorted(missing)]

    monkeypatch.setattr(MODULE.BASE, "_fetch_page", fake_fetch)
    report = MODULE._repair_gaps(
        "BTC-USDT",
        candles,
        start_ms=start,
        end_ms=end,
    )

    assert calls
    assert report["initial_missing"] == 4
    assert report["final_missing"] == 0
    assert MODULE._missing_timestamps(candles, start, end) == []
    assert len(candles) == 20


def test_checkpoint_roundtrip_preserves_only_matching_window(tmp_path: Path) -> None:
    minute = MODULE.BASE.MINUTE_MS
    start = 1_700_000_000_000
    end = start + 4 * minute
    checkpoint = tmp_path / "BTC.partial.json"
    candles = {stamp: _row(stamp) for stamp in range(start, end + minute, minute)}

    MODULE._write_checkpoint(
        checkpoint,
        symbol="BTCUSDT",
        start_ms=start,
        end_ms=end,
        rows_required=5,
        candles=candles,
        pages=7,
        stage="bulk",
    )
    loaded, pages = MODULE._load_checkpoint(
        checkpoint,
        start_ms=start,
        end_ms=end,
        rows_required=5,
    )
    assert pages == 7
    assert sorted(loaded) == sorted(candles)

    rejected, rejected_pages = MODULE._load_checkpoint(
        checkpoint,
        start_ms=start - minute,
        end_ms=end,
        rows_required=6,
    )
    assert rejected == {}
    assert rejected_pages == 0


def test_unresolved_gap_is_reported_not_synthesized(monkeypatch: pytest.MonkeyPatch) -> None:
    minute = MODULE.BASE.MINUTE_MS
    start = 1_500_000_000_000
    end = start + 5 * minute
    missing_stamp = start + 3 * minute
    candles = {
        stamp: _row(stamp)
        for stamp in range(start, end + minute, minute)
        if stamp != missing_stamp
    }

    monkeypatch.setattr(MODULE.BASE, "_fetch_page", lambda _symbol, _anchor: [])
    monkeypatch.setattr(MODULE, "REPAIR_ROUNDS", 1)
    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    report = MODULE._repair_gaps(
        "BTC-USDT",
        candles,
        start_ms=start,
        end_ms=end,
    )

    assert report["final_missing"] == 1
    assert report["missing_timestamps"] == [missing_stamp]
    assert missing_stamp not in candles
