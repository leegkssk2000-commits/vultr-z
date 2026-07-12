from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_closed_pnl_contract_adapter.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_closed_pnl_contract_adapter_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_existing_realized_r_is_r_ready() -> None:
    row = {
        "strategy": "session_bias",
        "status": "closed",
        "closed_at": "2026-06-05T18:20:00Z",
        "symbol": "BTCUSDT",
        "realized_r": -0.5,
    }
    out = MODULE.classify_contract(row, "session_bias", "memory.json")
    assert out is not None
    assert out["contract_state"] == "R_READY_EXISTING"
    assert out["realized_R"] == -0.5


def test_usdt_is_converted_only_with_explicit_positive_risk() -> None:
    row = {
        "strategy_id": "session_bias",
        "status_closed": True,
        "closed_at": "2026-06-05T18:20:00Z",
        "symbol": "BTCUSDT",
        "realized_pnl_usdt": -12.0,
        "initial_risk_usdt": 8.0,
    }
    out = MODULE.classify_contract(row, "session_bias", "memory.json")
    assert out is not None
    assert out["contract_state"] == "R_READY_FROM_EXPLICIT_USDT_RISK"
    assert out["realized_R"] == -1.5
    assert out["conversion"] == "REALIZED_USDT_DIV_EXPLICIT_RISK_USDT"


def test_usdt_without_risk_is_not_converted() -> None:
    row = {
        "strategy": "ema_ribbon_scalp",
        "status_closed": True,
        "closed_at": "2026-06-05T18:20:00Z",
        "symbol": "BTCUSDT",
        "realized_pnl_usdt": 12.0,
        "rr": 1.35,
        "entry": 100.0,
        "sl": 99.0,
        "size_pct": 5,
    }
    out = MODULE.classify_contract(row, "ema_ribbon_scalp", "memory.json")
    assert out is not None
    assert out["contract_state"] == "CLOSED_PNL_USDT_NO_RISK_DENOMINATOR"
    assert out["realized_R"] is None


def test_summary_without_exit_timestamp_is_not_promoted() -> None:
    row = {
        "strategy": "vol_spike_fade",
        "status": "closed",
        "realized_pnl_usdt": -26.0,
        "risk_usdt": 10.0,
        "count": 4,
    }
    out = MODULE.classify_contract(row, "vol_spike_fade", "summary.json")
    assert out is not None
    assert out["contract_state"] == "CLOSED_ROW_NO_EXIT_TIMESTAMP"
    assert out["realized_R"] is None


def test_open_row_is_rejected_even_with_exit_like_fields() -> None:
    row = {
        "strategy": "scalp_snap",
        "status": "open",
        "closed_at": "2026-06-05T18:20:00Z",
        "realized_r": 0.5,
    }
    assert MODULE.classify_contract(row, "scalp_snap", "memory.json") is None


def test_boolean_closed_is_accepted() -> None:
    row = {
        "strategy": "fvg_revert",
        "status_closed": True,
        "closed_at": "2026-06-05T18:20:00Z",
        "realized_pnl_usdt": 5.0,
    }
    out = MODULE.classify_contract(row, "fvg_revert", "memory.json")
    assert out is not None
    assert out["closed_evidence"] == "BOOLEAN_CLOSED"


def test_iter_inherits_grouped_strategy_name() -> None:
    payload = {
        "trades_by_strategy": {
            "squeeze_break": [
                {
                    "status": "closed",
                    "closed_at": "2026-06-05T18:20:00Z",
                    "symbol": "BTCUSDT",
                    "realized_pnl_usdt": -4.0,
                }
            ]
        }
    }
    rows = list(MODULE.iter_contract_rows(payload, "memory.json", {"squeeze_break"}))
    assert len(rows) == 1
    assert rows[0]["strategy"] == "squeeze_break"


def test_row_identity_prefers_trade_id() -> None:
    row = {
        "strategy": "session_bias",
        "trade_id": "T1",
        "symbol": "BTCUSDT",
        "entry_ts": 1,
        "exit_ts": 2,
        "source_usdt_key": "realized_pnl_usdt",
        "realized_pnl_usdt": -2.0,
        "realized_R": None,
    }
    assert MODULE.row_identity(row) == ("session_bias", "T1")
