from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path


PATH = Path(os.environ["R7A4D2_SHORT_PERF_DIAG"])
SPEC = importlib.util.spec_from_file_location("short_perf_diag", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_long_projection_removes_short_fields_and_trade_side() -> None:
    value = {
        "net_return_pct": 1.0,
        "short_closed_trade_count": 2,
        "trade_sample": [{"side": "long", "net_pnl_pct": 1.0}],
    }
    assert MODULE.long_projection(value) == {
        "net_return_pct": 1.0,
        "trade_sample": [{"net_pnl_pct": 1.0}],
    }


def test_field_diff_reports_nested_path() -> None:
    diffs = MODULE.field_diff({"a": {"b": 1}}, {"a": {"b": 2}})
    assert diffs == [{"path": "$.a.b", "prior": 1, "current": 2}]


def test_trade_metrics_profit_factor_and_expectancy() -> None:
    trades = [
        {"net_pnl_pct": 2.0, "gross_pnl_pct": 2.2, "cost_pct": 0.2, "pnl_r": 2.0, "mfe_pct": 3.0, "mae_pct": -0.5, "exit_reason": "take_profit"},
        {"net_pnl_pct": -1.0, "gross_pnl_pct": -0.8, "cost_pct": 0.2, "pnl_r": -1.0, "mfe_pct": 0.2, "mae_pct": -1.4, "exit_reason": "stop"},
    ]
    result = MODULE.trade_metrics(trades)
    assert result["trade_count"] == 2
    assert result["win_rate_pct"] == 50.0
    assert result["profit_factor"] == 2.0
    assert result["expectancy_r"] == 0.5
    assert result["payoff_ratio"] == 2.0


def test_trade_metrics_infinity_when_no_loss() -> None:
    result = MODULE.trade_metrics([
        {"net_pnl_pct": 1.0, "gross_pnl_pct": 1.1, "cost_pct": 0.1, "pnl_r": 1.0, "mfe_pct": 1.2, "mae_pct": -0.1, "exit_reason": "take_profit"}
    ])
    assert result["profit_factor"] == "Infinity"
    assert result["payoff_ratio"] == "Infinity"
    assert math.isclose(result["expectancy_net_pct_per_trade"], 1.0)
