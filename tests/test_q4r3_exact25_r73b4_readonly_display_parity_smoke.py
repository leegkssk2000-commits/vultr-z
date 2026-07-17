from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "tools/q4r3_exact25_r73b4_metric_helpers.py"
SPEC = importlib.util.spec_from_file_location("metrics", HELPER)
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def test_summary_ledger_metrics(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps({"summary": {"closed_count": 6, "winrate_pct": 66.6667,
                                             "total_r": 10.863052, "latest_trace_id": "p.6"}}) + "\n")
    result = metrics.ledger_metrics(path)
    assert result["closed_count"] == 6
    assert result["total_r"] == 10.863052
    assert result["latest_trace_id"] == "p.6"


def test_event_ledger_metrics(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    rows = [
        {"event_type": "position_closed", "position_id": "a", "net_r": 2.5},
        {"event_type": "position_closed", "position_id": "b", "net_r": -0.75},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    result = metrics.ledger_metrics(path)
    assert result["closed_count"] == 2
    assert result["winrate_pct"] == 50.0
    assert result["total_r"] == 1.75
    assert result["latest_trace_id"] == "b"


def test_html_metric_extraction() -> None:
    text = "<div>Closed 6</div><div>Winrate 66.67%</div><div>PNL +10.863052R</div><div>Trace p.6</div>"
    result = metrics.text_metrics(text)
    assert result == {"closed_count": 6, "winrate_pct": 66.67,
                      "total_r": 10.863052, "latest_trace_id": "p.6"}


def test_parity_accepts_trace_in_body() -> None:
    canonical = {"closed_count": 6, "winrate_pct": 66.6667, "total_r": 10.863052,
                 "latest_trace_id": "p.6"}
    observed = {"closed_count": 6, "winrate_pct": 66.67, "total_r": 10.863052}
    assert metrics.parity(canonical, observed, "latest p.6") == []


def test_parity_detects_stale_closed_count() -> None:
    canonical = {"closed_count": 6, "winrate_pct": 66.67, "total_r": 10.863052,
                 "latest_trace_id": "p.6"}
    observed = {"closed_count": 5, "winrate_pct": 66.67, "total_r": 10.863052,
                "latest_trace_id": "p.6"}
    assert "closed_count" in metrics.parity(canonical, observed, "p.6")


def test_empty_ledger_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    path.write_text("", encoding="utf-8")
    result = metrics.ledger_metrics(path)
    assert result["closed_count"] == 0
    assert result["latest_trace_id"] == ""
