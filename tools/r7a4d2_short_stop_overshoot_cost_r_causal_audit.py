#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


EXPECTED_CELL_COUNT = 24
EXPECTED_CANDIDATE_COUNT = 4
NOMINAL_LOSS_CAP_R = 0.75
NOMINAL_FULL_TP_R = 2.5
TOL = 1e-7


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def ratio_or_label(numerator: float, denominator: float) -> float | str:
    if denominator > 0:
        return rounded(numerator / denominator)
    return "Infinity" if numerator > 0 else 0.0


def trade_basis(trade: dict[str, Any]) -> dict[str, float]:
    risk_capital_pct = abs(finite(trade.get("risk_capital_pct")))
    raw_r_distance_pct = abs(finite(trade.get("raw_r_distance_pct")))
    if risk_capital_pct <= 0 or raw_r_distance_pct <= 0:
        raise ValueError("TRADE_R_BASIS_INVALID")
    quantity = risk_capital_pct / raw_r_distance_pct
    gross_r = finite(trade.get("gross_pnl_pct")) / risk_capital_pct
    net_r = finite(trade.get("net_pnl_pct")) / risk_capital_pct
    recorded_cost_r = abs(finite(trade.get("cost_pct"))) / risk_capital_pct
    return {
        "risk_capital_pct": risk_capital_pct,
        "raw_r_distance_pct": raw_r_distance_pct,
        "quantity": quantity,
        "gross_r": gross_r,
        "net_r": net_r,
        "recorded_cost_r": recorded_cost_r,
    }


def theoretical_short_gross_r(entry: float, exit_price: float, quantity: float, risk_capital_pct: float) -> float:
    if entry <= 0 or exit_price <= 0 or risk_capital_pct <= 0:
        raise ValueError("THEORETICAL_SHORT_R_INPUT_INVALID")
    gross_pct = quantity * (entry / exit_price - 1.0) * 100.0
    return gross_pct / risk_capital_pct


def audit_cell(cell: dict[str, Any], cost_profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    trade = cell.get("trade") if isinstance(cell.get("trade"), dict) else None
    if trade is None:
        raise ValueError("CELL_TRADE_MISSING")
    basis = trade_basis(trade)
    cost_id = str(cell.get("cost_profile") or "")
    perturbation = str(cell.get("perturbation") or "")
    cost = cost_profiles.get(cost_id)
    if cost is None:
        raise ValueError(f"COST_PROFILE_MISSING:{cost_id}")

    fee_bps = finite(cost.get("fee_bps_per_side"))
    slip_bps = finite(cost.get("slippage_bps_per_side"))
    raw_distance_pct = basis["raw_r_distance_pct"]
    roundtrip_fee_floor_r = (2.0 * fee_bps / 100.0) / raw_distance_pct
    roundtrip_slippage_floor_r = (2.0 * slip_bps / 100.0) / raw_distance_pct
    contractual_friction_floor_r = roundtrip_fee_floor_r + roundtrip_slippage_floor_r

    entry = finite(trade.get("entry_price"))
    exit_price = finite(trade.get("exit_price"))
    policy_stop = finite(trade.get("policy_stop"))
    policy_tp = finite(trade.get("policy_tp"))
    exit_reason = str(trade.get("exit_reason") or "")
    slip_rate = slip_bps / 10000.0

    policy_stop_gross_r = 0.0
    policy_tp_gross_r = 0.0
    policy_geometry_parity = False
    if entry > 0 and policy_stop > 0 and policy_tp > 0:
        policy_stop_gross_r = theoretical_short_gross_r(
            entry, policy_stop, basis["quantity"], basis["risk_capital_pct"]
        )
        policy_tp_gross_r = theoretical_short_gross_r(
            entry, policy_tp, basis["quantity"], basis["risk_capital_pct"]
        )
        policy_geometry_parity = (
            abs(policy_stop_gross_r + NOMINAL_LOSS_CAP_R) <= 1e-6
            and abs(policy_tp_gross_r - NOMINAL_FULL_TP_R) <= 1e-6
        )

    stop_overshoot_r = 0.0
    gap_overshoot_r = 0.0
    exit_slippage_overshoot_r = 0.0
    stop_classification = "NOT_STOP_EXIT"
    raw_exit_before_slippage = 0.0
    no_slip_gross_r = basis["gross_r"]
    if exit_reason in {"stop", "stop_collision"}:
        raw_exit_before_slippage = exit_price / (1.0 + slip_rate) if slip_rate > -1.0 else exit_price
        no_slip_gross_r = theoretical_short_gross_r(
            entry, raw_exit_before_slippage, basis["quantity"], basis["risk_capital_pct"]
        )
        stop_overshoot_r = max(abs(basis["gross_r"]) - NOMINAL_LOSS_CAP_R, 0.0)
        gap_overshoot_r = max(abs(no_slip_gross_r) - NOMINAL_LOSS_CAP_R, 0.0)
        exit_slippage_overshoot_r = max(abs(basis["gross_r"]) - abs(no_slip_gross_r), 0.0)
        if gap_overshoot_r > TOL and exit_slippage_overshoot_r > TOL:
            stop_classification = "OPEN_GAP_PLUS_EXIT_SLIPPAGE"
        elif gap_overshoot_r > TOL:
            stop_classification = "OPEN_GAP_OVERSHOOT"
        elif exit_slippage_overshoot_r > TOL:
            stop_classification = "EXIT_SLIPPAGE_ONLY"
        else:
            stop_classification = "WITHIN_POLICY_TOLERANCE"

    return {
        "candidate_id": str(cell.get("candidate_id") or ""),
        "arm": str(cell.get("arm") or ""),
        "cost_profile": cost_id,
        "perturbation": perturbation,
        "exit_reason": exit_reason,
        "entry_price": rounded(entry),
        "exit_price": rounded(exit_price),
        "policy_stop": rounded(policy_stop),
        "policy_tp": rounded(policy_tp),
        "raw_exit_before_slippage": rounded(raw_exit_before_slippage),
        "risk_capital_pct": rounded(basis["risk_capital_pct"]),
        "raw_r_distance_pct": rounded(raw_distance_pct),
        "quantity": rounded(basis["quantity"]),
        "gross_r": rounded(basis["gross_r"]),
        "net_r": rounded(basis["net_r"]),
        "recorded_fee_funding_cost_r": rounded(basis["recorded_cost_r"]),
        "roundtrip_fee_floor_r": rounded(roundtrip_fee_floor_r),
        "roundtrip_slippage_floor_r": rounded(roundtrip_slippage_floor_r),
        "contractual_friction_floor_r": rounded(contractual_friction_floor_r),
        "policy_stop_gross_r": rounded(policy_stop_gross_r),
        "policy_tp_gross_r": rounded(policy_tp_gross_r),
        "policy_geometry_parity": policy_geometry_parity,
        "stop_overshoot_r": rounded(stop_overshoot_r),
        "gap_overshoot_r": rounded(gap_overshoot_r),
        "exit_slippage_overshoot_r": rounded(exit_slippage_overshoot_r),
        "no_slip_gross_r": rounded(no_slip_gross_r),
        "stop_overshoot_classification": stop_classification,
        "fill_rebase_applied": bool(trade.get("fill_rebase_applied")),
    }


def summarize_axis(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    result: dict[str, dict[str, float]] = {}
    for axis, members in sorted(grouped.items()):
        result[axis] = {
            "cell_count": float(len(members)),
            "gross_r_sum": rounded(sum(finite(row.get("gross_r")) for row in members)),
            "net_r_sum": rounded(sum(finite(row.get("net_r")) for row in members)),
            "recorded_cost_r_sum": rounded(sum(finite(row.get("recorded_fee_funding_cost_r")) for row in members)),
            "contractual_friction_floor_r_sum": rounded(sum(finite(row.get("contractual_friction_floor_r")) for row in members)),
        }
    return result


def candidate_decisions(
    candidate_results: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    cell_audits: list[dict[str, Any]],
) -> dict[str, Any]:
    result_by_id = {str(row.get("candidate_id") or ""): row for row in candidate_results}
    audit_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cell_audits:
        audit_by_id[str(row.get("candidate_id") or "")].append(row)
    decisions: list[dict[str, Any]] = []
    for delta in deltas:
        candidate_id = str(delta.get("candidate_id") or "")
        result = result_by_id.get(candidate_id, {})
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        arm = str(delta.get("arm") or "")
        net_delta = finite(delta.get("net_r_sum_delta"))
        expectancy_delta = finite(delta.get("expectancy_r_delta"))
        current_net = finite(metrics.get("net_r_sum"))
        current_expectancy = finite(metrics.get("expectancy_r"))
        closed = int(result.get("closed_trade_cell_count") or 0)
        invalid = int(result.get("invalid_geometry_count") or 0)
        members = audit_by_id.get(candidate_id, [])
        worst_cost_axis = min(
            (
                sum(finite(row.get("net_r")) for row in members if row.get("cost_profile") == cost_id)
                for cost_id in sorted({str(row.get("cost_profile") or "") for row in members})
            ),
            default=0.0,
        )
        if (
            arm == "FILL_REBASED_GEOMETRY"
            and net_delta > 0
            and expectancy_delta > 0
            and current_net > 0
            and current_expectancy > 0
            and closed == 6
            and invalid == 0
        ):
            classification = "SINGLE_SURVIVOR_RETEST_CANDIDATE"
        elif arm == "FILL_REBASED_GEOMETRY":
            classification = "REBASE_REJECT"
        else:
            classification = "RAW_GEOMETRY_CONTROL_ONLY"
        decisions.append({
            "candidate_id": candidate_id,
            "arm": arm,
            "classification": classification,
            "closed_trade_cell_count": closed,
            "invalid_geometry_count": invalid,
            "net_r_sum": rounded(current_net),
            "expectancy_r": rounded(current_expectancy),
            "net_r_sum_delta": rounded(net_delta),
            "expectancy_r_delta": rounded(expectancy_delta),
            "worst_cost_axis_net_r_sum": rounded(worst_cost_axis),
            "median_raw_r_distance_pct": rounded(statistics.median([finite(row.get("raw_r_distance_pct")) for row in members])) if members else 0.0,
            "median_contractual_friction_floor_r": rounded(statistics.median([finite(row.get("contractual_friction_floor_r")) for row in members])) if members else 0.0,
        })
    survivors = sorted(
        [row for row in decisions if row["classification"] == "SINGLE_SURVIVOR_RETEST_CANDIDATE"],
        key=lambda row: (-finite(row["net_r_sum_delta"]), -finite(row["net_r_sum"]), row["candidate_id"]),
    )
    selected = survivors[0] if survivors else None
    return {
        "candidate_decisions": decisions,
        "survivor_candidate_count": len(survivors),
        "selected_survivor": selected,
        "rebase_reject_candidate_ids": sorted(
            row["candidate_id"] for row in decisions if row["classification"] == "REBASE_REJECT"
        ),
        "raw_control_candidate_ids": sorted(
            row["candidate_id"] for row in decisions if row["classification"] == "RAW_GEOMETRY_CONTROL_ONLY"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract_path = Path(args.contract).resolve()
    proof_path = root / "runtime/r7a4d2_short_scalp_counterfactual24_baseline_expansion36/counterfactual_expansion_proof_v1.json"
    proof = load_json(proof_path)
    contract = load_json(contract_path)
    before = {str(proof_path): sha256_file(proof_path), str(contract_path): sha256_file(contract_path)}

    blockers: list[str] = []
    if proof.get("state") != "PASS_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36":
        blockers.append("COUNTERFACTUAL_EXPANSION_NOT_PASS")
    if int(proof.get("blocker_count", -1)) != 0:
        blockers.append("COUNTERFACTUAL_EXPANSION_BLOCKED")
    if proof.get("source_registry_parity") is not True:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")
    if int(proof.get("mutation_path_count", -1)) != 0 or int(proof.get("side_effect_attempt_count", -1)) != 0:
        blockers.append("INPUT_INTEGRITY_FAILED")
    if int(proof.get("failure_count", -1)) != 0:
        blockers.append("COUNTERFACTUAL_FAILURE_PRESENT")
    scalp = proof.get("scalp_counterfactual") if isinstance(proof.get("scalp_counterfactual"), dict) else {}
    cells = [row for row in scalp.get("cells", []) if isinstance(row, dict)]
    candidate_results = [row for row in scalp.get("candidate_results", []) if isinstance(row, dict)]
    deltas = [row for row in scalp.get("counterfactual_deltas", []) if isinstance(row, dict)]
    if len(cells) != EXPECTED_CELL_COUNT or int(scalp.get("completed_cell_count", -1)) != EXPECTED_CELL_COUNT:
        blockers.append(f"SCALP_CELL_COUNT_INVALID:{len(cells)}")
    if int(scalp.get("closed_trade_cell_count", -1)) != EXPECTED_CELL_COUNT:
        blockers.append("SCALP_CLOSED_TRADE_COUNT_INVALID")
    if int(scalp.get("invalid_geometry_count", -1)) != 0:
        blockers.append("SCALP_INVALID_GEOMETRY_PRESENT")
    if len(candidate_results) != EXPECTED_CANDIDATE_COUNT or len(deltas) != EXPECTED_CANDIDATE_COUNT:
        blockers.append("SCALP_CANDIDATE_SHAPE_INVALID")
    cost_profiles = {
        str(row.get("id") or ""): row for row in contract.get("cost_profiles", []) if isinstance(row, dict)
    }
    perturbations = {
        str(row.get("id") or ""): row for row in contract.get("perturbations", []) if isinstance(row, dict)
    }
    if sorted(cost_profiles) != ["cost_profile_0", "cost_profile_1", "cost_profile_2"]:
        blockers.append("COST_PROFILE_CONTRACT_INVALID")
    if sorted(perturbations) != ["perturbation_0", "perturbation_1"]:
        blockers.append("PERTURBATION_CONTRACT_INVALID")

    audits: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not blockers:
        for index, cell in enumerate(cells):
            try:
                audits.append(audit_cell(cell, cost_profiles))
            except Exception as exc:
                failures.append({"cell_index": index, "candidate_id": cell.get("candidate_id"), "error": f"{type(exc).__name__}:{exc}"})
    if failures:
        blockers.append(f"CELL_CAUSAL_AUDIT_FAILED:{len(failures)}")

    raw_distances = [finite(row.get("raw_r_distance_pct")) for row in audits]
    recorded_cost_rs = [finite(row.get("recorded_fee_funding_cost_r")) for row in audits]
    friction_floor_rs = [finite(row.get("contractual_friction_floor_r")) for row in audits]
    stop_rows = [row for row in audits if row.get("exit_reason") in {"stop", "stop_collision"}]
    stop_overshoot_rows = [row for row in stop_rows if finite(row.get("stop_overshoot_r")) > TOL]
    geometry_parity_failures = [row for row in audits if row.get("policy_geometry_parity") is not True]
    if geometry_parity_failures:
        blockers.append(f"POLICY_GEOMETRY_PARITY_FAILED:{len(geometry_parity_failures)}")

    gross_wins = [finite(row.get("gross_r")) for row in audits if finite(row.get("gross_r")) > 0]
    gross_losses = [abs(finite(row.get("gross_r"))) for row in audits if finite(row.get("gross_r")) < 0]
    net_wins = [finite(row.get("net_r")) for row in audits if finite(row.get("net_r")) > 0]
    net_losses = [abs(finite(row.get("net_r"))) for row in audits if finite(row.get("net_r")) < 0]
    gross_payoff = ratio_or_label(statistics.fmean(gross_wins) if gross_wins else 0.0, statistics.fmean(gross_losses) if gross_losses else 0.0)
    net_payoff = ratio_or_label(statistics.fmean(net_wins) if net_wins else 0.0, statistics.fmean(net_losses) if net_losses else 0.0)

    axis_by_cost = summarize_axis(audits, "cost_profile")
    axis_by_perturbation = summarize_axis(audits, "perturbation")
    perturbation_decay_r = rounded(
        finite(axis_by_perturbation.get("perturbation_1", {}).get("net_r_sum"))
        - finite(axis_by_perturbation.get("perturbation_0", {}).get("net_r_sum"))
    )
    severe_minus_base_r = rounded(
        finite(axis_by_cost.get("cost_profile_2", {}).get("net_r_sum"))
        - finite(axis_by_cost.get("cost_profile_0", {}).get("net_r_sum"))
    )
    decisions = candidate_decisions(candidate_results, deltas, audits) if audits else {
        "candidate_decisions": [], "survivor_candidate_count": 0, "selected_survivor": None,
        "rebase_reject_candidate_ids": [], "raw_control_candidate_ids": [],
    }

    causes: list[str] = []
    median_friction = statistics.median(friction_floor_rs) if friction_floor_rs else 0.0
    gross_payoff_value = finite(gross_payoff)
    net_payoff_value = finite(net_payoff)
    if median_friction >= 0.5 or (gross_payoff_value > 0 and net_payoff_value < gross_payoff_value * 0.6):
        causes.append("COST_TO_RAW_R_COMPRESSION")
    if stop_overshoot_rows:
        causes.append("STOP_EXIT_GAP_OR_SLIPPAGE_OVERSHOOT")
    if perturbation_decay_r < 0:
        causes.append("ENTRY_TIMING_DECAY")
    if decisions.get("survivor_candidate_count", 0) < 3 and decisions.get("rebase_reject_candidate_ids"):
        causes.append("FILL_REBASE_EFFECT_HETEROGENEITY")
    if not causes:
        causes.append("CAUSE_NOT_RESOLVED")

    if decisions.get("survivor_candidate_count") != 1:
        blockers.append(f"SINGLE_SURVIVOR_COUNT_INVALID:{decisions.get('survivor_candidate_count', 0)}")
    blockers = list(dict.fromkeys(blockers))
    after = {str(proof_path): sha256_file(proof_path), str(contract_path): sha256_file(contract_path)}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")

    state = "PASS_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT" if not blockers else "HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT"
    next_stage = (
        "R7.A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN"
        if not blockers
        else "R7.A4D2_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT"
    )
    evidence = {
        "schema": "r7a4d2_short_stop_overshoot_cost_r_causal_audit_v1",
        "official_stage": "R7.A4D2_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "nominal_loss_cap_r": NOMINAL_LOSS_CAP_R,
        "nominal_full_tp_r": NOMINAL_FULL_TP_R,
        "nominal_payoff_ratio": rounded(NOMINAL_FULL_TP_R / NOMINAL_LOSS_CAP_R),
        "observed_gross_payoff_ratio": gross_payoff,
        "observed_net_payoff_ratio": net_payoff,
        "primary_cause": causes[0],
        "cause_chain": causes,
        "cell_count": len(audits),
        "median_raw_r_distance_pct": rounded(statistics.median(raw_distances)) if raw_distances else 0.0,
        "minimum_raw_r_distance_pct": rounded(min(raw_distances)) if raw_distances else 0.0,
        "maximum_raw_r_distance_pct": rounded(max(raw_distances)) if raw_distances else 0.0,
        "median_recorded_fee_funding_cost_r": rounded(statistics.median(recorded_cost_rs)) if recorded_cost_rs else 0.0,
        "p90_recorded_fee_funding_cost_r": rounded(percentile(recorded_cost_rs, 0.9)),
        "median_contractual_friction_floor_r": rounded(median_friction),
        "p90_contractual_friction_floor_r": rounded(percentile(friction_floor_rs, 0.9)),
        "friction_floor_ge_0_5r_count": sum(1 for value in friction_floor_rs if value >= 0.5),
        "friction_floor_ge_1_0r_count": sum(1 for value in friction_floor_rs if value >= 1.0),
        "stop_trade_count": len(stop_rows),
        "stop_overshoot_count": len(stop_overshoot_rows),
        "stop_overshoot_classification_histogram": dict(sorted(Counter(str(row.get("stop_overshoot_classification")) for row in stop_rows).items())),
        "stop_overshoot_r_sum": rounded(sum(finite(row.get("stop_overshoot_r")) for row in stop_rows)),
        "gap_overshoot_r_sum": rounded(sum(finite(row.get("gap_overshoot_r")) for row in stop_rows)),
        "exit_slippage_overshoot_r_sum": rounded(sum(finite(row.get("exit_slippage_overshoot_r")) for row in stop_rows)),
        "policy_geometry_parity_failure_count": len(geometry_parity_failures),
        "cost_profile_axis": axis_by_cost,
        "perturbation_axis": axis_by_perturbation,
        "perturbation_1_minus_0_net_r": perturbation_decay_r,
        "severe_minus_base_net_r": severe_minus_base_r,
        "candidate_resolution": decisions,
        "cell_audits": audits,
        "failure_count": len(failures),
        "failures": failures,
        "protected_mutation_path_count": len(mutation_paths),
        "protected_mutation_paths": mutation_paths,
        "strategy_mutation_allowed": False,
        "entry_threshold_relaxation_allowed": False,
        "production_admission_expansion_allowed": False,
        "shadow_start_allowed": False,
        "baseline_market_coverage_expansion_still_required": True,
        "next_stage": next_stage,
    }
    output = root / "runtime/r7a4d2_short_stop_overshoot_cost_r_causal_audit/causal_audit_v1.json"
    atomic_json(output, evidence)

    selected = decisions.get("selected_survivor") or {}
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("PRIMARY_CAUSE=" + str(evidence["primary_cause"]))
    print("CAUSE_CHAIN=" + json.dumps(causes, ensure_ascii=False))
    print("OBSERVED_GROSS_PAYOFF_RATIO=" + str(gross_payoff))
    print("OBSERVED_NET_PAYOFF_RATIO=" + str(net_payoff))
    print("MEDIAN_RAW_R_DISTANCE_PCT=" + str(evidence["median_raw_r_distance_pct"]))
    print("MEDIAN_RECORDED_FEE_FUNDING_COST_R=" + str(evidence["median_recorded_fee_funding_cost_r"]))
    print("MEDIAN_CONTRACTUAL_FRICTION_FLOOR_R=" + str(evidence["median_contractual_friction_floor_r"]))
    print("FRICTION_FLOOR_GE_1R_COUNT=" + str(evidence["friction_floor_ge_1_0r_count"]))
    print("STOP_TRADE_COUNT=" + str(len(stop_rows)))
    print("STOP_OVERSHOOT_COUNT=" + str(len(stop_overshoot_rows)))
    print("STOP_OVERSHOOT_HISTOGRAM=" + json.dumps(evidence["stop_overshoot_classification_histogram"], sort_keys=True))
    print("PERTURBATION_1_MINUS_0_NET_R=" + str(perturbation_decay_r))
    print("SEVERE_MINUS_BASE_NET_R=" + str(severe_minus_base_r))
    print("SINGLE_SURVIVOR_CANDIDATE_ID=" + str(selected.get("candidate_id") or ""))
    print("SINGLE_SURVIVOR_NET_R_DELTA=" + str(selected.get("net_r_sum_delta") or 0.0))
    print("REBASE_REJECT_CANDIDATE_IDS=" + json.dumps(decisions.get("rebase_reject_candidate_ids", [])))
    print("RAW_CONTROL_CANDIDATE_IDS=" + json.dumps(decisions.get("raw_control_candidate_ids", [])))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("EVIDENCE_JSON=" + str(output))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
