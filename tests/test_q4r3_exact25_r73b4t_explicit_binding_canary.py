from __future__ import annotations

import importlib.util
from pathlib import Path

CANARY_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4t_explicit_binding_canary.py"
ADAPTER_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4t_display_adapter.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = load("r73b4t_canary", CANARY_PATH)
adapter = load("r73b4t_adapter", ADAPTER_PATH)

SNAPSHOT = {
    "owner_id": "Q4R3_EXACT25_SHADOW_AGGREGATE_SNAPSHOT_WRITER",
    "epoch_id": "q4r3.exact25.shadow.pending",
    "sample_count": 0,
    "closed_count": 0,
    "active_count": 0,
    "wins": 0,
    "losses": 0,
    "breakeven": 0,
    "winrate_pct": None,
    "net_r": 0.0,
    "latest_trace_id": None,
    "runtime_active": False,
    "formal_ledger_bound": False,
}


def test_adapter_removes_legacy_metrics_and_rows() -> None:
    template = {
        "closed_count": 68,
        "pnl_r": 53.613052,
        "winrate_pct": 37.209,
        "latest_trace_id": "legacy.trace",
        "recent_ledger_trace": [{"pnl_r": 2.5}],
        "source": "q4r3_shadow_closed_ledger_latest.json",
        "nested": {"closed": 68, "total_r": 53.613052},
    }
    payload = adapter.build_payload(template, SNAPSHOT, "alimi")
    assert payload["closed_count"] == 0
    assert payload["pnl_r"] == 0.0
    assert payload["winrate_pct"] == 0.0
    assert payload["latest_trace_id"] is None
    assert payload["recent_ledger_trace"] == []
    assert payload["source"] == "shadow_aggregate_snapshot/latest.json"
    assert payload["nested"]["closed"] == 0
    assert payload["nested"]["total_r"] == 0.0


def test_caddy_route_is_inserted_before_generic_api() -> None:
    original = """alimi.z-os.vip {\n    encode gzip\n    handle_path /api/* {\n        root * /var/www/z-os-alimi/api\n    }\n}\n"""
    patched, count = canary.patch_caddy(original)
    assert count == 1
    assert patched.index(canary.ROUTE_BEGIN) < patched.index("handle_path /api/*")
    patched_again, count_again = canary.patch_caddy(patched)
    assert patched_again == patched
    assert count_again == 0


def test_telegram_all_legacy_literals_are_rewired() -> None:
    source = """A = 'telegram_pos_status_latest.json'\nB = \"/var/www/z-os-alimi/telegram_pos_status_latest.json\"\n"""
    patched, count = canary.patch_telegram_source(source)
    assert count == 2
    assert "telegram_pos_status_latest.json" not in patched
    assert patched.count(canary.NEW_TELEGRAM_SOURCE) == 2


def test_missing_telegram_literal_fails_closed() -> None:
    try:
        canary.patch_telegram_source("print('no legacy source')")
    except RuntimeError as exc:
        assert str(exc) == "TELEGRAM_STATUS_LITERAL_NOT_FOUND"
    else:
        raise AssertionError("expected fail-closed")
