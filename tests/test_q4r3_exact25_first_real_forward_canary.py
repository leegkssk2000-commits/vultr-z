from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_exact25_first_real_forward_canary.py"
    spec = importlib.util.spec_from_file_location("q4r3_first_real_canary_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_extract_closed_events_ignores_open_then_accepts_closed(tmp_path: Path) -> None:
    path = tmp_path / "surface.json"
    path.write_text(json.dumps({"current": {"event_id": "e1", "strategy": "alpha_combo", "symbol": "BTCUSDT", "open": True}}), encoding="utf-8")
    assert MODULE.extract_closed_events(path) == {}
    path.write_text(json.dumps({"current": {"event_id": "e1", "strategy": "alpha_combo", "symbol": "BTCUSDT", "closed": True, "exit_ts": "2026-07-13T04:00:00Z"}}), encoding="utf-8")
    assert "e1" in MODULE.extract_closed_events(path)


def test_atomic_jsonl_append_rejects_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    row = {"event_id": "e1", "strategy_id": "alpha_combo"}
    assert MODULE.atomic_jsonl_append(path, row) is True
    assert MODULE.atomic_jsonl_append(path, row) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_normalize_row_calculates_exact_r() -> None:
    owners = {"alpha_combo": "a" * 64}
    event = {
        "event_id": "e1",
        "strategy": "alpha_combo",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_ts": "2026-07-13T04:00:00Z",
        "exit_ts": "2026-07-13T04:10:00Z",
        "entry": 100.0,
        "sl": 99.0,
        "qty": 2.0,
        "closed": True,
    }
    row = {"strategy": "alpha_combo", "symbol": "BTCUSDT", "realized_pnl_usdt": 3.0, "pnl_r": 1.5, "entry": 100.0, "sl": 99.0}
    normalized = MODULE.normalize_row(row, event, owners)
    assert normalized["initial_risk_usdt"] == 2.0
    assert normalized["realized_R"] == 1.5
    assert normalized["time_exposure_min"] == 10.0


def test_normalize_row_blocks_formula_mismatch() -> None:
    owners = {"alpha_combo": "a" * 64}
    event = {
        "event_id": "e1",
        "strategy": "alpha_combo",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_ts": "2026-07-13T04:00:00Z",
        "exit_ts": "2026-07-13T04:10:00Z",
        "entry": 100.0,
        "sl": 99.0,
        "qty": 2.0,
        "closed": True,
    }
    row = {"strategy": "alpha_combo", "symbol": "BTCUSDT", "realized_pnl_usdt": 3.0, "pnl_r": 1.4, "entry": 100.0, "sl": 99.0}
    try:
        MODULE.normalize_row(row, event, owners)
    except RuntimeError as exc:
        assert "REALIZED_R_FORMULA_MISMATCH" in str(exc)
    else:
        raise AssertionError("formula mismatch must fail closed")


def test_match_new_row_prefers_event_id() -> None:
    event = {"event_id": "e2", "strategy": "alpha_combo", "symbol": "BTCUSDT", "closed": True}
    rows = [
        {"event_id": "e1", "strategy": "alpha_combo", "symbol": "BTCUSDT", "pnl_r": 1},
        {"event_id": "e2", "strategy": "alpha_combo", "symbol": "BTCUSDT", "pnl_r": 2},
    ]
    assert MODULE.match_new_row(rows, event)["event_id"] == "e2"
