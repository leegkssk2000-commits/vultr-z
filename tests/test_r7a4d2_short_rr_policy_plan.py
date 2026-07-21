#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_SHORT_RR_PLAN"])
    spec = importlib.util.spec_from_file_location("short_rr_plan", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(delta: float = 2e-16, diff_value: object | None = None):
    current = -1.0 + delta if diff_value is None else diff_value
    return {
        "state": "HOLD_LONG_REGRESSION_SINGLE_CASE",
        "dual_result_count": 600,
        "long_baseline_result_count": 600,
        "short_trade_detail_expected_count": 120,
        "dual_minus_long_net_return_pct": -7.35,
        "short_trade_metrics": {"profit_factor": 0.09},
        "long_regression_mismatch_sample": [
            {"diffs": [{"path": "$.net_return_pct", "prior": -1.0, "current": current}]}
        ],
    }


def test_anchor_payoff_is_2_5_over_0_75():
    module = load_module()
    plan, blockers = module.build_plan(evidence())
    assert blockers == []
    assert plan["anchor"]["minimum_gross_payoff_ratio"] == round(2.5 / 0.75, 12)
    assert plan["invariants"]["raw_pnl_r_preserved"] is True


def test_tiny_float_mismatch_is_noise():
    module = load_module()
    plan, blockers = module.build_plan(evidence())
    assert blockers == []
    assert plan["prior_numeric_noise"]["accepted"] is True


def test_nonnumeric_mismatch_is_blocked():
    module = load_module()
    _, blockers = module.build_plan(evidence(diff_value="changed"))
    assert "LONG_MISMATCH_NOT_NUMERIC_NOISE" in blockers


def test_missing_reduce_qty_fails_closed():
    module = load_module()
    plan, blockers = module.build_plan(evidence())
    assert blockers == []
    assert plan["invariants"]["missing_reduce_qty_action"] == "block"
    assert plan["invariants"]["legacy_hold_short_direct_execution_allowed"] is False
