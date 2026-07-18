from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "tools/q4r3_exact25_r73b4v_zero_epoch_start_preflight.py"
SPEC = importlib.util.spec_from_file_location("r73b4v", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_number_parses_rendered_units() -> None:
    assert module.number("0R") == 0.0
    assert module.number("0%") == 0.0
    assert module.number("+2.5R") == 2.5


def test_semantic_metrics_accepts_nested_surface_payload() -> None:
    payload = {
        "summary": {
            "closed_count": "0",
            "recent_rows": "0",
            "last12_r": "0",
            "winrate_pct": "0",
            "ev_r": "0",
            "pnl_r": "0",
            "last_close": "none",
            "epoch": "q4r3.exact25.shadow.pending",
        },
        "authority": {"runtime_active": False, "formal_ledger_bound": False},
    }
    metrics = module.semantic_metrics(payload)
    assert metrics == {
        "closed": "0",
        "recent_rows": "0",
        "last12": "0",
        "winrate": "0",
        "ev": "0",
        "pnl": "0",
        "last_close": "none",
        "epoch": "q4r3.exact25.shadow.pending",
        "runtime_active": False,
        "formal_ledger_bound": False,
    }


def test_zero_metric_blockers_rejects_any_nonzero_residue() -> None:
    metrics = {
        "closed": 0,
        "recent_rows": 43,
        "last12": 7.25,
        "winrate": 37.209,
        "ev": 0.459302,
        "pnl": 0,
        "last_close": "BTCUSDT stale",
    }
    blockers = module.zero_metric_blockers("TELEGRAM", metrics, require_last_close=True)
    assert "TELEGRAM_RECENT_ROWS_NOT_ZERO:43" in blockers
    assert "TELEGRAM_LAST12_NOT_ZERO:7.25" in blockers
    assert any(item.startswith("TELEGRAM_LAST_CLOSE_NOT_NONE") for item in blockers)


def test_clean_zero_metrics_pass() -> None:
    metrics = {
        "closed": "0",
        "recent_rows": "0",
        "last12": "0R",
        "winrate": "0%",
        "ev": "0R",
        "pnl": "0R",
        "last_close": "none",
    }
    assert module.zero_metric_blockers("TELEGRAM", metrics, require_last_close=True) == []


def test_command_count_preserves_required_commands() -> None:
    source = "'/pos' '/pnl' '/view'"
    assert module.command_count(source, ["/pos", "/pnl", "/view"]) == 3


def test_none_value_variants() -> None:
    assert module.none_value(None)
    assert module.none_value("none")
    assert module.none_value({})
    assert not module.none_value("BTCUSDT close")
