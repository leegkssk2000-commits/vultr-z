from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_close_source_authority_lock.py"
SPEC = importlib.util.spec_from_file_location("q4r3_exact25_close_source_authority_lock", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

START = datetime(2026, 7, 13, 4, 20, tzinfo=timezone.utc).timestamp()
NOW = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc).timestamp()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_pure_shadow_close_source_is_proven(tmp_path: Path) -> None:
    path = tmp_path / "shadow_close_latest.json"
    write_json(path, {
        "rows": [{
            "strategy_id": "alpha_combo",
            "event_id": "event-1",
            "status": "closed",
            "mode": "shadow",
            "closed_at": "2026-07-13T04:40:00Z",
            "realized_pnl_usdt": 2.5,
            "entry_price": 100.0,
            "stop_price": 99.0,
        }]
    })
    result = MODULE.inspect_candidate(path, {"alpha_combo"}, START, NOW)
    assert result["classification"] == "PROVEN_PURE_SHADOW_CLOSE_SOURCE"
    assert result["pure_shadow_authority"] is True
    assert result["qualifying_recent_exact25_close_count"] == 1


def test_paper_ledger_is_rejected_even_with_shadow_label(tmp_path: Path) -> None:
    path = tmp_path / "paper_order_ledger_state.json"
    write_json(path, {
        "rows": [{
            "strategy_id": "alpha_combo",
            "event_id": "event-1",
            "status": "closed",
            "mode": "shadow",
            "closed_at": "2026-07-13T04:40:00Z",
            "realized_pnl_usdt": 2.5,
        }]
    })
    result = MODULE.inspect_candidate(path, {"alpha_combo"}, START, NOW)
    assert result["classification"] == "PAPER_LEDGER_NOT_SHADOW_AUTHORITY"
    assert result["recent_paper_rows"] == 1
    assert result["pure_shadow_authority"] is False


def test_mixed_nonpaper_source_requires_filter_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "combined_close_latest.json"
    write_json(path, {
        "rows": [
            {
                "strategy_id": "alpha_combo",
                "event_id": "event-shadow",
                "status": "closed",
                "mode": "shadow",
                "closed_at": "2026-07-13T04:40:00Z",
                "realized_pnl_usdt": 2.5,
            },
            {
                "strategy_id": "alpha_combo",
                "event_id": "event-paper",
                "status": "closed",
                "mode": "paper",
                "closed_at": "2026-07-13T04:41:00Z",
                "realized_pnl_usdt": 1.0,
            },
        ]
    })
    result = MODULE.inspect_candidate(path, {"alpha_combo"}, START, NOW)
    assert result["classification"] == "MIXED_SOURCE_FILTERED_SIDECAR_REQUIRED"
    assert result["recent_shadow_rows"] == 1
    assert result["recent_paper_rows"] == 1


def test_audit_unit_is_never_counted_as_producer() -> None:
    units = [
        {
            "unit": "q4r3-exact25-shadow-producer-lineage-audit-hotfix.service",
            "ActiveState": "active",
            "SubState": "running",
            "FragmentPath": "/etc/systemd/system/q4r3-exact25-shadow-producer-lineage-audit-hotfix.service",
            "ExecStart": "python exact25 audit.py",
        },
        {
            "unit": "q4r3-exact25-shadow-engine.service",
            "ActiveState": "active",
            "SubState": "running",
            "FragmentPath": "/etc/systemd/system/q4r3-exact25-shadow-engine.service",
            "ExecStart": "python exact25 engine.py",
        },
    ]
    result = MODULE.eligible_producer_units(units, set())
    assert result == ["q4r3-exact25-shadow-engine.service"]


def test_old_close_is_not_forward_qualifying(tmp_path: Path) -> None:
    path = tmp_path / "shadow_close_latest.json"
    write_json(path, {
        "strategy_id": "alpha_combo",
        "event_id": "old-event",
        "status": "closed",
        "mode": "shadow",
        "closed_at": "2026-07-12T04:00:00Z",
        "realized_pnl_usdt": 2.5,
    })
    result = MODULE.inspect_candidate(path, {"alpha_combo"}, START, NOW)
    assert result["classification"] == "NO_RECENT_EXACT25_CLOSE_ROWS"
    assert result["qualifying_recent_exact25_close_count"] == 0
