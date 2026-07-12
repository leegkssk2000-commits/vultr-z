from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_25_strategy_realized_ledger_bind_fixed.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_25_strategy_realized_ledger_bind_fixed_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_normalize_name_is_stable() -> None:
    assert MODULE.normalize_name(" VWAP-Revert ") == "vwap_revert"
    assert MODULE.normalize_name("support__resistance") == "support_resistance"


def test_extract_exact_universe_and_aliases() -> None:
    payload = {
        "strategy_registry": [
            {"strategy_id": f"strategy_{index:02d}", "aliases": [f"S-{index:02d}"]}
            for index in range(25)
        ]
    }
    candidates = list(MODULE.extract_universe_candidates(payload, "memory.json"))
    exact = [candidate for candidate in candidates if len(candidate["names"]) == 25]
    assert exact
    aliases = exact[0]["aliases"]
    assert aliases["s_00"] == "strategy_00"
    assert "s_00" not in exact[0]["names"]


def test_alternate_strategy_fields_are_aliases_not_universe_members() -> None:
    names, aliases = MODULE.object_strategy_names(
        {
            "strategy_id": "support_resistance",
            "strategy_name": "Support Resistance",
            "aliases": ["SR-Reclaim"],
        }
    )
    assert names == ["support_resistance"]
    assert aliases["sr_reclaim"] == "support_resistance"


def test_closed_realized_row_is_accepted() -> None:
    payload = {
        "trades": [
            {
                "strategy": "trend-rider",
                "symbol": "BTCUSDT",
                "side": "long",
                "status": "closed",
                "entry_ts": 1_700_000_000_000,
                "exit_ts": 1_700_000_060_000,
                "realized_r": 0.75,
            }
        ]
    }
    rows = list(MODULE.iter_realized_rows(payload, "memory.json"))
    assert len(rows) == 1
    assert rows[0]["observed_strategy"] == "trend_rider"
    assert rows[0]["realized_R"] == 0.75


def test_open_row_is_rejected_even_with_pnl() -> None:
    payload = {
        "strategy": "trend_rider",
        "status": "open",
        "entry_ts": 1_700_000_000_000,
        "pnl_r": 0.5,
    }
    assert list(MODULE.iter_realized_rows(payload, "memory.json")) == []


def test_grouped_strategy_name_is_inherited() -> None:
    payload = {
        "trades_by_strategy": {
            "liquidity_sweep": [
                {"closed_at": "2026-01-01T00:00:00Z", "realized_r": -0.5, "status": "closed"}
            ]
        }
    }
    rows = list(MODULE.iter_realized_rows(payload, "memory.json"))
    assert len(rows) == 1
    assert rows[0]["observed_strategy"] == "liquidity_sweep"


def test_canonicalize_alias_and_punctuation() -> None:
    expected = ["support_resistance", "vwap_revert"]
    alias_map = {"sr_reclaim": "support_resistance"}
    assert MODULE.canonicalize_strategy("SR-Reclaim", alias_map, expected) == ("support_resistance", "alias_map")
    assert MODULE.canonicalize_strategy("VWAPRevert", alias_map, expected) == ("vwap_revert", "punctuation_normalized")


def test_record_identity_prefers_trade_id() -> None:
    row = {
        "canonical_strategy": "a",
        "trade_id": "T1",
        "symbol": "BTCUSDT",
        "entry_ts": 1,
        "exit_ts": 2,
        "realized_R": 0.5,
    }
    assert MODULE.record_identity(row) == ("a", "T1")


def test_row_closed_requires_closed_evidence() -> None:
    assert MODULE.row_closed({"status": "closed"}, None, None) is True
    assert MODULE.row_closed({"status": "open"}, 123, "tp") is False
    assert MODULE.row_closed({}, 123, None) is True
    assert MODULE.row_closed({}, None, None) is False
