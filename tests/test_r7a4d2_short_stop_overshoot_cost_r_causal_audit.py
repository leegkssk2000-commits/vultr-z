from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_COST_R_AUDIT"])
    spec = importlib.util.spec_from_file_location("cost_r_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_policy_stop_parity_and_exit_slippage_overshoot() -> None:
    module = load_module()
    entry = 100.0
    raw_r_pct = 1.0
    policy_stop = entry / (1.0 - 0.75 * 0.01)
    policy_tp = entry / (1.0 + 2.5 * 0.01)
    slip_rate = 0.0001
    exit_price = policy_stop * (1.0 + slip_rate)
    quantity = 1.0
    risk_capital_pct = quantity * raw_r_pct
    gross_pct = quantity * (entry / exit_price - 1.0) * 100.0
    trade = {
        "entry_price": entry,
        "exit_price": exit_price,
        "policy_stop": policy_stop,
        "policy_tp": policy_tp,
        "risk_capital_pct": risk_capital_pct,
        "raw_r_distance_pct": raw_r_pct,
        "gross_pnl_pct": gross_pct,
        "net_pnl_pct": gross_pct - 0.1,
        "cost_pct": 0.1,
        "exit_reason": "stop",
        "fill_rebase_applied": True,
    }
    cell = {
        "candidate_id": "c1",
        "arm": "FILL_REBASED_GEOMETRY",
        "cost_profile": "cost_profile_0",
        "perturbation": "perturbation_0",
        "trade": trade,
    }
    costs = {
        "cost_profile_0": {
            "fee_bps_per_side": 5.0,
            "slippage_bps_per_side": 1.0,
        }
    }
    result = module.audit_cell(cell, costs)
    assert result["policy_geometry_parity"] is True
    assert result["stop_overshoot_r"] > 0
    assert result["gap_overshoot_r"] == 0.0
    assert result["exit_slippage_overshoot_r"] > 0
    assert result["stop_overshoot_classification"] == "EXIT_SLIPPAGE_ONLY"


def test_open_gap_and_slippage_are_separated() -> None:
    module = load_module()
    entry = 100.0
    raw_r_pct = 1.0
    stop = entry / (1.0 - 0.75 * 0.01)
    tp = entry / (1.0 + 2.5 * 0.01)
    raw_gap_exit = stop * 1.002
    exit_price = raw_gap_exit * 1.0003
    gross_pct = (entry / exit_price - 1.0) * 100.0
    cell = {
        "candidate_id": "c2",
        "arm": "FILL_REBASED_GEOMETRY",
        "cost_profile": "cost_profile_1",
        "perturbation": "perturbation_1",
        "trade": {
            "entry_price": entry,
            "exit_price": exit_price,
            "policy_stop": stop,
            "policy_tp": tp,
            "risk_capital_pct": 1.0,
            "raw_r_distance_pct": raw_r_pct,
            "gross_pnl_pct": gross_pct,
            "net_pnl_pct": gross_pct - 0.15,
            "cost_pct": 0.15,
            "exit_reason": "stop",
        },
    }
    costs = {
        "cost_profile_1": {
            "fee_bps_per_side": 7.5,
            "slippage_bps_per_side": 3.0,
        }
    }
    result = module.audit_cell(cell, costs)
    assert result["gap_overshoot_r"] > 0
    assert result["exit_slippage_overshoot_r"] > 0
    assert result["stop_overshoot_classification"] == "OPEN_GAP_PLUS_EXIT_SLIPPAGE"


def test_cost_floor_expands_when_raw_r_is_narrow() -> None:
    module = load_module()
    trade = {
        "risk_capital_pct": 0.05,
        "raw_r_distance_pct": 0.05,
        "gross_pnl_pct": 0.1,
        "net_pnl_pct": -0.02,
        "cost_pct": 0.12,
        "entry_price": 100.0,
        "exit_price": 99.9,
        "policy_stop": 100.0375140678,
        "policy_tp": 99.875155,
        "exit_reason": "take_profit",
    }
    cell = {
        "candidate_id": "c3",
        "arm": "FILL_REBASED_GEOMETRY",
        "cost_profile": "cost_profile_2",
        "perturbation": "perturbation_0",
        "trade": trade,
    }
    costs = {
        "cost_profile_2": {
            "fee_bps_per_side": 10.0,
            "slippage_bps_per_side": 6.0,
        }
    }
    result = module.audit_cell(cell, costs)
    assert result["roundtrip_fee_floor_r"] == 4.0
    assert result["roundtrip_slippage_floor_r"] == 2.4
    assert result["contractual_friction_floor_r"] == 6.4


def test_candidate_resolution_selects_only_positive_rebase() -> None:
    module = load_module()
    candidate_results = []
    deltas = []
    audits = []
    specs = [
        ("good", "FILL_REBASED_GEOMETRY", 5.0, 0.8, 6.0, 0.9),
        ("bad1", "FILL_REBASED_GEOMETRY", -2.0, -0.2, -1.0, -0.1),
        ("bad2", "FILL_REBASED_GEOMETRY", -3.0, -0.4, -2.0, -0.3),
        ("control", "RAW_GEOMETRY_STABILITY_CONTROL", 0.0, 0.0, 1.0, 0.2),
    ]
    for candidate_id, arm, delta_r, delta_e, net_r, expectancy in specs:
        candidate_results.append({
            "candidate_id": candidate_id,
            "closed_trade_cell_count": 6,
            "invalid_geometry_count": 0,
            "metrics": {"net_r_sum": net_r, "expectancy_r": expectancy},
        })
        deltas.append({
            "candidate_id": candidate_id,
            "arm": arm,
            "net_r_sum_delta": delta_r,
            "expectancy_r_delta": delta_e,
        })
        for cost_id in ("cost_profile_0", "cost_profile_1", "cost_profile_2"):
            for perturbation in ("perturbation_0", "perturbation_1"):
                audits.append({
                    "candidate_id": candidate_id,
                    "cost_profile": cost_id,
                    "perturbation": perturbation,
                    "net_r": net_r / 6.0,
                    "raw_r_distance_pct": 0.2,
                    "contractual_friction_floor_r": 0.5,
                })
    result = module.candidate_decisions(candidate_results, deltas, audits)
    assert result["survivor_candidate_count"] == 1
    assert result["selected_survivor"]["candidate_id"] == "good"
    assert result["rebase_reject_candidate_ids"] == ["bad1", "bad2"]
    assert result["raw_control_candidate_ids"] == ["control"]
