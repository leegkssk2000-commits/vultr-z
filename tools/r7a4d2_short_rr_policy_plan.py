#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ABS_TOL = 1e-12
ANCHOR_LOSS_CAP_R = 0.75
ANCHOR_FULL_TP_R = 2.5


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def numeric_noise_only(sample: list[dict[str, Any]], tol: float = ABS_TOL) -> tuple[bool, float]:
    maximum = 0.0
    if len(sample) != 1:
        return False, maximum
    diffs = sample[0].get("diffs")
    if not isinstance(diffs, list) or not diffs:
        return False, maximum
    for row in diffs:
        if not isinstance(row, dict):
            return False, maximum
        prior = row.get("prior")
        current = row.get("current")
        if not isinstance(prior, (int, float)) or not isinstance(current, (int, float)):
            return False, maximum
        delta = abs(float(prior) - float(current))
        maximum = max(maximum, delta)
        if not math.isfinite(delta) or delta > tol:
            return False, maximum
    return True, maximum


def build_plan(evidence: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if str(evidence.get("state")) != "HOLD_LONG_REGRESSION_SINGLE_CASE":
        blockers.append("PRIOR_STATE_INVALID")
    if int(evidence.get("dual_result_count", -1)) != 600:
        blockers.append("DUAL_RESULT_COUNT_INVALID")
    if int(evidence.get("long_baseline_result_count", -1)) != 600:
        blockers.append("LONG_BASELINE_RESULT_COUNT_INVALID")
    if int(evidence.get("short_trade_detail_expected_count", -1)) != 120:
        blockers.append("SHORT_TRADE_EXPECTED_COUNT_INVALID")

    mismatch = evidence.get("long_regression_mismatch_sample")
    mismatch_rows = mismatch if isinstance(mismatch, list) else []
    noise_only, max_delta = numeric_noise_only(mismatch_rows)
    if not noise_only:
        blockers.append("LONG_MISMATCH_NOT_NUMERIC_NOISE")

    metrics = evidence.get("short_trade_metrics") if isinstance(evidence.get("short_trade_metrics"), dict) else {}
    if float(evidence.get("dual_minus_long_net_return_pct", 0.0)) >= 0:
        blockers.append("NEGATIVE_ROOT_CAUSE_INPUT_NOT_REPRODUCED")
    pf = metrics.get("profit_factor")
    if not isinstance(pf, (int, float)) or float(pf) >= 1.0:
        blockers.append("NEGATIVE_PROFIT_FACTOR_INPUT_NOT_REPRODUCED")

    payoff = ANCHOR_FULL_TP_R / ANCHOR_LOSS_CAP_R
    plan = {
        "schema": "r7a4d2_short_rr_policy_plan_v1",
        "official_stage": "R7.A4D2_SHORT_RR_POLICY_PLAN",
        "state": "PASS_SHORT_RR_POLICY_PLAN" if not blockers else "HOLD_SHORT_RR_POLICY_PLAN_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "anchor": {
            "source": "ZEL_ALIMI_SENIOR_BASELINE_2_5R_NEG_0_75R",
            "raw_r_definition": "filled_entry_to_strategy_structural_stop_distance",
            "policy_loss_cap_r": ANCHOR_LOSS_CAP_R,
            "policy_full_tp_r": ANCHOR_FULL_TP_R,
            "minimum_gross_payoff_ratio": round(payoff, 12),
        },
        "invariants": {
            "strategy_source_mutation_allowed": False,
            "raw_strategy_sl_tp_mutation_allowed": False,
            "raw_pnl_r_preserved": True,
            "policy_adjusted_pnl_r_required": True,
            "sidecar_short_admission_required": True,
            "legacy_hold_short_direct_execution_allowed": False,
            "missing_reduce_qty_action": "block",
            "entry_threshold_relaxation_allowed": False,
        },
        "initial_fail_closed_regime_policy": {
            "trend_down": "eligible_after_strategy_signal_validation",
            "range": "observer_until_strategy_role_binding",
            "trend_up": "blocked",
            "shock_recovery": "blocked",
        },
        "exit_profile_sequence": [
            {
                "id": "full_tp_anchor_v1",
                "primary": True,
                "loss_cap_r": ANCHOR_LOSS_CAP_R,
                "full_tp_r": ANCHOR_FULL_TP_R,
                "partial_reduce_allowed": False,
                "trailing_allowed": False,
                "mfe_runner_allowed": False,
            },
            {
                "id": "partial_trailing_mfe_observer_v1",
                "primary": False,
                "activation_gate": "full_tp_anchor_v1_positive_and_ssot_thresholds_resolved",
                "threshold_source": "SSOT_REQUIRED_NO_INVENTION",
            },
        ],
        "validation": {
            "counterfactual_scenario_count": 600,
            "full_short_trade_detail_required": True,
            "raw_result_immutability_required": True,
            "policy_adjusted_profit_factor_must_exceed": 1.0,
            "policy_adjusted_expectancy_r_must_exceed": 0.0,
            "invalid_geometry_count_required": 0,
            "orphan_add_count_required": 0,
            "missing_reduce_qty_count_required": 0,
            "trend_up_short_execution_count_required": 0,
            "shock_recovery_short_execution_count_required": 0,
        },
        "prior_numeric_noise": {
            "accepted": noise_only,
            "absolute_tolerance": ABS_TOL,
            "maximum_observed_delta": max_delta,
        },
        "next_stage": "R7.A4D2_SHORT_RR_SIDECAR_COUNTERFACTUAL_600" if not blockers else "R7.A4D2_SHORT_RR_POLICY_PLAN",
    }
    return plan, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    evidence_path = root / "runtime/r7a4d2_short_harness_mismatch_performance/diagnose_v1.json"
    evidence = load_json(evidence_path)
    plan, blockers = build_plan(evidence)
    output = root / "runtime/r7a4d2_short_rr_policy_plan/short_rr_policy_plan_v1.json"
    atomic_json(output, plan)

    print("STATE=" + str(plan["state"]))
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("POLICY_LOSS_CAP_R=" + str(ANCHOR_LOSS_CAP_R))
    print("POLICY_FULL_TP_R=" + str(ANCHOR_FULL_TP_R))
    print("MINIMUM_GROSS_PAYOFF_RATIO=" + str(plan["anchor"]["minimum_gross_payoff_ratio"]))
    print("RAW_PNL_R_PRESERVED=true")
    print("LEGACY_HOLD_SHORT_DIRECT_EXECUTION_ALLOWED=false")
    print("MISSING_REDUCE_QTY_ACTION=block")
    print("LONG_MISMATCH_NUMERIC_NOISE_ACCEPTED=" + str(plan["prior_numeric_noise"]["accepted"]).lower())
    print("PLAN_JSON=" + str(output))
    print("NEXT_STAGE=" + str(plan["next_stage"]))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
