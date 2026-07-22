from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SCHEMA_ADAPTER_BIND"])
    spec = importlib.util.spec_from_file_location("schema_adapter_bind", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(count: int = 900) -> list[list[float]]:
    output = []
    previous_close = 100.0
    start = 1_700_000_100_000
    for index in range(count):
        timestamp = start + index * 60_000
        open_v = previous_close
        close_v = open_v + (0.05 if index % 2 == 0 else -0.02)
        high_v = max(open_v, close_v) + 0.03
        low_v = min(open_v, close_v) - 0.03
        volume = 10_000.0 + index
        output.append([timestamp, open_v, high_v, low_v, close_v, volume])
        previous_close = close_v
    return output


def write_source(path: Path, symbol: str = "BTCUSDT", count: int = 900) -> str:
    module = load_module()
    payload = {"symbol": symbol, "interval": "1m", "row_count": count, "rows": rows(count)}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(module.sha256_file(path))


def pass_audit(paths: list[tuple[Path, str]]) -> dict:
    module = load_module()
    diagnostics = []
    for path, sha in paths:
        diagnostics.append({"path": path.name, "expected_sha256": sha, "actual_sha256": sha})
    return {
        "state": "PASS_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE",
        "blocker_count": 0,
        "required_source_count": len(paths),
        "layout_ready_source_count": len(paths),
        "unresolved_source_count": 0,
        "shared_layout": True,
        "layout_signatures": [module.EXPECTED_SIGNATURE],
        "source_diagnostics": diagnostics,
    }


def test_audited_loader_uses_fixed_layout_and_excludes_volume(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "BTCUSDT.json"
    sha = write_source(path)
    frame = module.load_audited_market_frame(path, sha)
    assert list(frame[["open", "high", "low", "close", "volume"]].iloc[0]) == [100.0, 100.08, 99.97, 100.05, 10000.0]
    assert len(frame) == 900


def test_resample_produces_complete_5m_and_15m_bars(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "BTCUSDT.json"
    sha = write_source(path)
    frame = module.load_audited_market_frame(path, sha)
    five = module.resample_complete_bars(frame, 5)
    fifteen = module.resample_complete_bars(frame, 15)
    assert len(five) == 180
    assert len(fifteen) == 60
    assert (five["high"] >= five[["open", "close"]].max(axis=1)).all()
    assert (fifteen["low"] <= fifteen[["open", "close"]].min(axis=1)).all()


def test_rows_audit_signature_mismatch_fail_closes() -> None:
    module = load_module()
    audit = {
        "state": "PASS_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE",
        "blocker_count": 0,
        "required_source_count": 5,
        "layout_ready_source_count": 5,
        "unresolved_source_count": 0,
        "shared_layout": True,
        "layout_signatures": [[6, 0, 1, 5, 3, 4]],
        "source_diagnostics": [{}] * 5,
    }
    try:
        module.validate_rows_audit(audit)
    except ValueError as exc:
        assert "LAYOUT_SIGNATURE_MISMATCH" in str(exc)
    else:
        raise AssertionError("signature mismatch must fail")


def test_sha_mismatch_fail_closes(tmp_path: Path) -> None:
    module = load_module()
    path = tmp_path / "BTCUSDT.json"
    write_source(path)
    try:
        module.load_audited_market_frame(path, "0" * 64)
    except ValueError as exc:
        assert str(exc) == "FROZEN_SHA_MISMATCH"
    else:
        raise AssertionError("sha mismatch must fail")
