from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_ADMISSION_CLOSURE"])
    spec = importlib.util.spec_from_file_location("admission_closure", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trade(net: float, pnl_r: float, exit_reason: str = "take_profit") -> dict:
    return {
        "net_pnl_pct": net,
        "gross_pnl_pct": net + 0.01,
        "cost_pct": 0.01,
        "pnl_r": pnl_r,
        "risk_capital_pct": 0.1,
        "mfe_pct": 0.3,
        "mae_pct": -0.1,
        "exit_reason": exit_reason,
    }


def test_positive_pair_becomes_candidate() -> None:
    module = load_module()
    metrics = module.group_metrics([{}, {}], [trade(0.2, 2.0), trade(0.1, 1.0)])
    assert metrics["allowlist_candidate"] is True
    assert metrics["classification"] == "POSITIVE_MULTI_TRADE_CANDIDATE"


def test_negative_pair_is_not_candidate() -> None:
    module = load_module()
    metrics = module.group_metrics([{}, {}], [trade(-0.1, -0.75, "stop"), trade(0.02, 0.2)])
    assert metrics["allowlist_candidate"] is False
    assert metrics["classification"] == "NEGATIVE_OBSERVER_RESULT"


def test_no_trade_routes_to_execution_closure() -> None:
    module = load_module()
    rows = [{"strategy_id": "alpha_combo", "regime": "trend_up", "metrics": module.group_metrics([{}], [])}]
    classes, next_stage = module.classify_next(rows, 0)
    assert "OBSERVER_CLOSED_TRADE_ZERO" in classes
    assert next_stage == "R7.A4D2_SHORT_OBSERVER_EXECUTION_CLOSURE"


def test_positive_non_grid_routes_to_allowlist_plan() -> None:
    module = load_module()
    rows = [
        {
            "strategy_id": "alpha_combo",
            "regime": "trend_up",
            "metrics": module.group_metrics([{}], [trade(0.2, 2.0)]),
        },
        {
            "strategy_id": "grid_rebalance",
            "regime": "shock_recovery",
            "metrics": module.group_metrics([{}], [trade(1.0, 2.5)]),
        },
    ]
    classes, next_stage = module.classify_next(rows, 2)
    assert "POSITIVE_STRATEGY_REGIME_ALLOWLIST_CANDIDATES_FOUND" in classes
    assert "GRID_REBALANCE_QUARANTINED" in classes
    assert next_stage == "R7.A4D2_SHORT_ADMISSION_ALLOWLIST_PLAN"
