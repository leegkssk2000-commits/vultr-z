from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4_metric_helpers_v2.py"
SPEC = importlib.util.spec_from_file_location("metrics_v2", MODULE_PATH)
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def test_json_style_metric_keys() -> None:
    text = '{"closed_count":6,"winrate_pct":66.6667,"total_r":10.863052,"latest_trace_id":"p.6"}'
    assert metrics.text_metrics(text) == {
        "closed_count": 6,
        "winrate_pct": 66.6667,
        "total_r": 10.863052,
        "latest_trace_id": "p.6",
    }


def test_embedded_json_style_metric_keys() -> None:
    text = '<script>window.state={"state_closed":6,"wr_pct":66.67,"pnl_r":10.863052,"position_id":"p.6"}</script>'
    result = metrics.text_metrics(text)
    assert result["closed_count"] == 6
    assert result["winrate_pct"] == 66.67
    assert result["total_r"] == 10.863052
    assert result["latest_trace_id"] == "p.6"
