from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_shadow_producer_lineage_audit.py"
SPEC = importlib.util.spec_from_file_location("q4r3_exact25_shadow_producer_lineage_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_timestamp_accepts_iso_and_milliseconds() -> None:
    iso = "2026-07-13T04:20:37+00:00"
    expected = datetime.fromisoformat(iso).timestamp()
    assert MODULE.parse_timestamp(iso) == expected
    assert MODULE.parse_timestamp(expected * 1000) == expected


def test_parse_timestamp_rejects_non_time_numbers() -> None:
    assert MODULE.parse_timestamp(25) is None
    assert MODULE.parse_timestamp("9538") is None
    assert MODULE.parse_timestamp(None) is None


def test_closed_marker_requires_real_close_evidence() -> None:
    assert MODULE.closed_marker({"status": "closed", "strategy": "alpha_combo"}) is True
    assert MODULE.closed_marker({"exit_ts": "2026-07-13T04:20:37Z", "strategy": "alpha_combo"}) is True
    assert MODULE.closed_marker({"status": "open", "strategy": "alpha_combo"}) is False


def test_inspect_runtime_json_uses_content_time_not_mtime(tmp_path: Path) -> None:
    path = tmp_path / "shadow_closed_latest.json"
    payload = {
        "status": "closed",
        "strategy_id": "alpha_combo",
        "event_id": "event-1",
        "exit_ts": "2026-07-13T04:20:37Z",
        "realized_pnl_usdt": 2.0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    now_epoch = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc).timestamp()
    result = MODULE.inspect_runtime_json(path, {"alpha_combo"}, now_epoch)
    assert result["classification"] == "FRESH_CLOSE_CANDIDATE"
    assert result["exact25_hits"] == ["alpha_combo"]
    assert result["event_count"] == 1


def test_audit_named_file_is_not_authoritative(tmp_path: Path) -> None:
    path = tmp_path / "q4r3_close_audit_latest.json"
    payload = {
        "status": "closed",
        "strategy_id": "alpha_combo",
        "event_id": "event-1",
        "exit_ts": "2026-07-13T04:20:37Z",
        "realized_R": 1.0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    now_epoch = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc).timestamp()
    result = MODULE.inspect_runtime_json(path, {"alpha_combo"}, now_epoch)
    assert result["classification"] == "AUDIT_OR_DERIVED"
