from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load("r73b4u_adapter", ROOT / "tools/q4r3_exact25_r73b4u_strict_display_adapter.py")
canary = load("r73b4u_canary", ROOT / "tools/q4r3_exact25_r73b4u_zero_epoch_display_parity.py")

SNAPSHOT = {
    "owner_id": "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER",
    "snapshot_sha256": "a" * 64,
    "epoch_id": "q4r3.exact25.shadow.pending",
    "sample_count": 0,
    "closed_count": 0,
    "runtime_active": False,
    "formal_ledger_bound": False,
}


def dirty_template() -> dict:
    return {
        "closed_count": 68,
        "rows": 43,
        "recent_rows": 43,
        "last12": 7.25,
        "wr": 37.209,
        "ev": 0.459302,
        "pnl_r": 53.613052,
        "last_close": "BTCUSDT breakout long SL_TOUCH_CLOSED -0.75R",
        "ledger_source": "q4r3_shadow_closed_ledger_latest.json",
        "recent": [
            {"symbol": "BTCUSDT", "strategy": "breakout", "side": "long", "reason": "SL_TOUCH_CLOSED", "pnl_r": -0.75}
        ],
        "summary": {"closed": 68, "rows": 43, "total_r": 53.613052},
    }


def test_strict_adapter_removes_all_visible_residue() -> None:
    payload = adapter.build_payload(dirty_template(), SNAPSHOT, "alimi")
    assert payload["closed_count"] == 0
    assert payload["rows"] == 0
    assert payload["recent_rows"] == 0
    assert payload["last12"] == 0.0
    assert payload["wr"] == 0.0
    assert payload["ev"] == 0.0
    assert payload["last_close"] == "none"
    assert payload["recent"] == []
    assert payload["summary"]["closed"] == 0
    assert payload["summary"]["rows"] == 0
    assert payload["summary"]["total_r"] == 0.0
    assert canary.residuals(payload) == []


def test_residual_scanner_catches_trade_rows_and_old_source() -> None:
    found = canary.residuals(dirty_template())
    assert any(item.startswith("STALE_TRADE_ROWS") for item in found)
    assert any(item.startswith("STALE_SOURCE") for item in found)
    assert any(item.startswith("NONZERO_METRIC") for item in found)
    assert any(item.startswith("STALE_LAST_EVENT") for item in found)


def test_output_permission_is_0644(tmp_path: Path) -> None:
    target = tmp_path / "display.json"
    adapter.atomic_json(target, {"closed_count": 0})
    assert target.stat().st_mode & 0o777 == 0o644


def test_market_candle_array_is_not_mistaken_for_trade_rows() -> None:
    payload = {"candles": [[1, 2, 3, 4], [2, 3, 4, 5]], "closed_count": 0, "display_source": adapter.CANONICAL_SOURCE}
    assert canary.residuals(payload) == []
