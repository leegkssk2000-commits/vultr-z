#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

DECISION = Path("runtime/r7a4d2_economic_fail_mechanism_decision_gate/economic_fail_mechanism_decision_gate_v1.json")
MECHANISM = Path("runtime/r7a4d2_economic_fail_all_loss_mechanism_audit/economic_fail_all_loss_mechanism_audit_summary_v1.json")
BATCH = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_survivor_independent_oos_batch_summary_v1.json")
TRADES = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_oos_trade_rows_v1.jsonl")
CELLS = Path("runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution/remaining_oos_cell_rows_v1.jsonl")
OUTPUT_DIR = Path("runtime/r7a4d2_atr15_side_specialization_economic_child_audit")
SUMMARY_OUT = OUTPUT_DIR / "atr15_side_specialization_economic_child_audit_summary_v1.json"
CHILD_TRADES_OUT = OUTPUT_DIR / "atr15_short_child_trade_rows_v1.jsonl"
CHILD_CELLS_OUT = OUTPUT_DIR / "atr15_short_child_cell_rows_v1.jsonl"

EXPECTED_DECISION_STATE = "PASS_ECONOMIC_FAIL_MECHANISM_DECISION_GATE"
EXPECTED_MECHANISM_STATE = "PASS_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT"
EXPECTED_BATCH_STATE = "PASS_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH"
EXPECTED_LANE = "dual_atr_volatility_bot:15m"
EXPECTED_VARIANT = "atr15_persistence_5m_trigger"
EXPECTED_ACTION = "SIDE_SPECIALIZATION_CHILD_AUDIT"
EXPECTED_SIDE = "short"
EXPECTED_STRESS_CELLS = 6
EXPECTED_FOLDS = 6
MIN_EVENTS = 24
MIN_SYMBOLS = 3
MIN_POSITIVE_FOLDS = 4
SEVERE_MIN_PF = 1.20
BASE_COST = "cost_profile_0"
BASE_TIMING = "timing_0"
EPS = 1e-12
MATCH_TOLERANCE = 1e-6


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_number}")
            rows.append(value)
    return rows


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def close_enough(left: Any, right: Any, tolerance: float = MATCH_TOLERANCE) -> bool:
    return abs(finite(left, math.nan) - finite(right, math.nan)) <= tolerance


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(paths: Iterable[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count, digest.hexdigest()


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("fold", -1)),
            finite(row.get("entry_timestamp")),
            str(row.get("symbol") or ""),
            str(row.get("event_id") or ""),
            str(row.get("timing_id") or ""),
        ),
    )
    net_values = [finite(row.get("net_r")) for row in ordered]
    gross_values: list[float] = []
    drag_values: list[float] = []
    pnl_values = [finite(row.get("net_return_pct")) for row in ordered]
    identity_max_abs = 0.0
    fold_net: dict[int, float] = defaultdict(float)
    for row, net_r in zip(ordered, net_values):
        risk = finite(row.get("risk_pct"))
        gross_r = finite(row.get("gross_return_pct")) / risk if risk > EPS else 0.0
        drag_r = (
            finite(row.get("round_trip_cost_pct")) + finite(row.get("funding_cost_pct"))
        ) / risk if risk > EPS else 0.0
        gross_values.append(gross_r)
        drag_values.append(drag_r)
        identity_max_abs = max(identity_max_abs, abs((gross_r - drag_r) - net_r))
        fold_net[int(row.get("fold", -1))] += net_r
    wins = [value for value in net_values if value > 0]
    losses = [-value for value in net_values if value < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    event_ids = {str(row.get("event_id") or "") for row in rows if row.get("event_id")}
    symbols = {str(row.get("symbol") or "") for row in rows if row.get("symbol")}
    return {
        "trade_count": len(rows),
        "unique_event_count": len(event_ids),
        "symbol_count": len(symbols),
        "fold_count": len(fold_net),
        "positive_fold_count": sum(value > 0 for value in fold_net.values()),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(rows) * 100.0 if rows else 0.0,
        "gross_r_sum": sum(gross_values),
        "execution_drag_r_sum": sum(drag_values),
        "net_r_sum": sum(net_values),
        "net_pnl_sum_pct": sum(pnl_values),
        "expectancy_r": statistics.mean(net_values) if net_values else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > EPS else (math.inf if gross_win > 0 else 0.0),
        "max_drawdown_r": max_drawdown(net_values),
        "max_drawdown_pct": max_drawdown(pnl_values),
        "fold_net_r": {str(key): value for key, value in sorted(fold_net.items())},
        "symbol_histogram": dict(sorted(Counter(str(row.get("symbol") or "") for row in rows).items())),
        "regime_histogram": dict(sorted(Counter(str(row.get("regime") or "") for row in rows).items())),
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in rows).items())),
        "net_identity_max_abs_error": identity_max_abs,
    }


def profile_name(cost_profile_id: str) -> str:
    return {
        "cost_profile_0": "base",
        "cost_profile_1": "adverse",
        "cost_profile_2": "severe",
    }.get(cost_profile_id, cost_profile_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    required = [root / DECISION, root / MECHANISM, root / BATCH, root / TRADES, root / CELLS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_INPUT")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = snapshot(required)
    decision = load_json(root / DECISION)
    mechanism = load_json(root / MECHANISM)
    batch = load_json(root / BATCH)
    trades = load_jsonl(root / TRADES)
    cells = load_jsonl(root / CELLS)

    blockers: list[str] = []
    if decision.get("state") != EXPECTED_DECISION_STATE:
        blockers.append("DECISION_GATE_NOT_PASS")
    if mechanism.get("state") != EXPECTED_MECHANISM_STATE:
        blockers.append("MECHANISM_AUDIT_NOT_PASS")
    if batch.get("state") != EXPECTED_BATCH_STATE:
        blockers.append("BATCH_NOT_PASS")
    if int(decision.get("blocker_count") or 0) != 0 or int(mechanism.get("blocker_count") or 0) != 0:
        blockers.append("UPSTREAM_BLOCKER_NONZERO")
    if int(batch.get("mutation_path_count") or 0) != 0 or int(mechanism.get("mutation_path_count") or 0) != 0:
        blockers.append("UPSTREAM_INPUT_MUTATION_DETECTED")

    selected = decision.get("selected_candidate") if isinstance(decision.get("selected_candidate"), dict) else {}
    if str(selected.get("lane_id") or "") != EXPECTED_LANE:
        blockers.append("SELECTED_LANE_CHANGED")
    if str(selected.get("variant_id") or "") != EXPECTED_VARIANT:
        blockers.append("SELECTED_VARIANT_CHANGED")
    if str(selected.get("child_audit_type") or "") != EXPECTED_ACTION:
        blockers.append("SELECTED_ACTION_CHANGED")
    if str(selected.get("selected_side") or "") != EXPECTED_SIDE:
        blockers.append("SELECTED_SIDE_CHANGED")
    if not bool(selected.get("parent_immutable")):
        blockers.append("PARENT_IMMUTABLE_FALSE")
    if bool(decision.get("parallel_redesign_allowed")) or bool(decision.get("parameter_optimization_allowed")):
        blockers.append("FORBIDDEN_REDESIGN_AUTHORITY_TRUE")
    if bool(decision.get("stop_target_mutation_allowed")):
        blockers.append("STOP_TARGET_MUTATION_TRUE")

    candidate_rows = [
        row for row in trades
        if str(row.get("lane_id") or "") == EXPECTED_LANE
        and str(row.get("variant_id") or "") == EXPECTED_VARIANT
    ]
    child_rows = [row for row in candidate_rows if str(row.get("side") or "") == EXPECTED_SIDE]
    if not candidate_rows:
        blockers.append("ATR15_PARENT_TRADE_ROWS_ZERO")
    if not child_rows:
        blockers.append("ATR15_SHORT_CHILD_TRADE_ROWS_ZERO")
    if any(str(row.get("side") or "") != EXPECTED_SIDE for row in child_rows):
        blockers.append("CHILD_SIDE_CONTAMINATION")

    parent_cells = {
        (str(row.get("cost_profile_id") or ""), str(row.get("timing_id") or ""))
        for row in candidate_rows
    }
    if len(parent_cells) != EXPECTED_STRESS_CELLS:
        blockers.append(f"PARENT_STRESS_CELL_COUNT_INVALID:{len(parent_cells)}")
    source_cell_rows = [
        row for row in cells
        if str(row.get("lane_id") or "") == EXPECTED_LANE
        and str(row.get("variant_id") or "") == EXPECTED_VARIANT
    ]
    if len(source_cell_rows) != EXPECTED_STRESS_CELLS:
        blockers.append(f"PARENT_CELL_EVIDENCE_COUNT_INVALID:{len(source_cell_rows)}")

    parent_primary_rows = [
        row for row in candidate_rows
        if str(row.get("cost_profile_id") or "") == BASE_COST
        and str(row.get("timing_id") or "") == BASE_TIMING
    ]
    child_primary_rows = [
        row for row in child_rows
        if str(row.get("cost_profile_id") or "") == BASE_COST
        and str(row.get("timing_id") or "") == BASE_TIMING
    ]
    parent_primary = aggregate(parent_primary_rows)
    child_primary = aggregate(child_primary_rows)

    if parent_primary["unique_event_count"] != int(selected.get("parent_base_event_count") or -1):
        blockers.append("PARENT_PRIMARY_EVENT_COUNT_MISMATCH")
    if not close_enough(parent_primary["gross_r_sum"], selected.get("parent_gross_r_sum")):
        blockers.append("PARENT_PRIMARY_GROSS_R_MISMATCH")
    if not close_enough(parent_primary["execution_drag_r_sum"], selected.get("parent_execution_drag_r_sum")):
        blockers.append("PARENT_PRIMARY_DRAG_R_MISMATCH")
    if not close_enough(parent_primary["net_r_sum"], selected.get("parent_net_r_sum")):
        blockers.append("PARENT_PRIMARY_NET_R_MISMATCH")
    if not close_enough(parent_primary["profit_factor"], selected.get("parent_profit_factor")):
        blockers.append("PARENT_PRIMARY_PF_MISMATCH")

    if child_primary["unique_event_count"] != int(selected.get("selected_side_event_count") or -1):
        blockers.append("CHILD_PRIMARY_EVENT_COUNT_MISMATCH")
    if not close_enough(child_primary["gross_r_sum"], selected.get("selected_side_gross_r_sum")):
        blockers.append("CHILD_PRIMARY_GROSS_R_MISMATCH")
    if not close_enough(child_primary["execution_drag_r_sum"], selected.get("selected_side_execution_drag_r_sum")):
        blockers.append("CHILD_PRIMARY_DRAG_R_MISMATCH")
    if not close_enough(child_primary["net_r_sum"], selected.get("selected_side_net_r_sum")):
        blockers.append("CHILD_PRIMARY_NET_R_MISMATCH")
    if not close_enough(child_primary["profit_factor"], selected.get("selected_side_profit_factor")):
        blockers.append("CHILD_PRIMARY_PF_MISMATCH")
    if child_primary["net_identity_max_abs_error"] > MATCH_TOLERANCE:
        blockers.append("CHILD_PRIMARY_NET_IDENTITY_BROKEN")

    after = snapshot(required)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append(f"READ_ONLY_INPUT_MUTATION:{len(mutation_paths)}")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        print("STATE=HOLD_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    child_cell_rows: list[dict[str, Any]] = []
    for cost_profile_id, timing_id in sorted(parent_cells):
        rows = [
            row for row in child_rows
            if str(row.get("cost_profile_id") or "") == cost_profile_id
            and str(row.get("timing_id") or "") == timing_id
        ]
        metrics = aggregate(rows)
        child_cell_rows.append({
            "lane_id": EXPECTED_LANE,
            "parent_variant_id": EXPECTED_VARIANT,
            "child_variant_id": "atr15_persistence_5m_trigger_short_only",
            "selected_side": EXPECTED_SIDE,
            "cost_profile_id": cost_profile_id,
            "timing_id": timing_id,
            "profile": profile_name(cost_profile_id),
            **metrics,
        })

    profiles = {
        profile: aggregate([
            row for row in child_rows
            if profile_name(str(row.get("cost_profile_id") or "")) == profile
        ])
        for profile in ("base", "adverse", "severe")
    }
    severe_cells = [row for row in child_cell_rows if row.get("profile") == "severe"]
    worst_severe = min(severe_cells, key=lambda row: finite(row.get("net_r_sum"), math.inf)) if severe_cells else {}

    coverage_checks = {
        "primary_unique_events": child_primary["unique_event_count"] >= MIN_EVENTS,
        "primary_symbols": child_primary["symbol_count"] >= MIN_SYMBOLS,
        "primary_fold_coverage": child_primary["fold_count"] == EXPECTED_FOLDS,
        "all_stress_cells_present": len(child_cell_rows) == EXPECTED_STRESS_CELLS,
        "all_cells_have_events": all(int(row.get("unique_event_count") or 0) > 0 for row in child_cell_rows),
        "all_cells_identity_valid": all(finite(row.get("net_identity_max_abs_error")) <= MATCH_TOLERANCE for row in child_cell_rows),
    }
    primary_checks = {
        "net_positive": child_primary["net_r_sum"] > 0,
        "profit_factor_positive": child_primary["profit_factor"] > 1.0,
        "positive_folds": child_primary["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
    }
    profile_checks = {
        "base_net_positive": profiles["base"]["net_r_sum"] > 0,
        "base_pf_positive": profiles["base"]["profit_factor"] > 1.0,
        "base_positive_folds": profiles["base"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "adverse_net_positive": profiles["adverse"]["net_r_sum"] > 0,
        "adverse_pf_positive": profiles["adverse"]["profit_factor"] > 1.0,
        "adverse_positive_folds": profiles["adverse"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "severe_net_positive": profiles["severe"]["net_r_sum"] > 0,
        "severe_pf_gate": profiles["severe"]["profit_factor"] >= SEVERE_MIN_PF,
        "severe_positive_folds": profiles["severe"]["positive_fold_count"] >= MIN_POSITIVE_FOLDS,
        "worst_severe_net_positive": finite(worst_severe.get("net_r_sum"), -math.inf) > 0,
        "worst_severe_pf_positive": finite(worst_severe.get("profit_factor"), 0.0) > 1.0,
    }

    coverage_ready = all(coverage_checks.values())
    primary_pass = coverage_ready and all(primary_checks.values())
    robust_same_oos = primary_pass and all(profile_checks.values())
    conditional_same_oos = (
        primary_pass
        and all(profile_checks[key] for key in (
            "base_net_positive", "base_pf_positive", "base_positive_folds",
            "adverse_net_positive", "adverse_pf_positive", "adverse_positive_folds",
        ))
        and not robust_same_oos
    )

    if robust_same_oos:
        classification = "ROBUST_SAME_OOS_SIDE_CANDIDATE"
        next_stage = "R7.A4D2_ATR15_SHORT_CHILD_UNUSED_OOS_SOURCE_PLAN"
    elif conditional_same_oos:
        classification = "CONDITIONAL_SAME_OOS_SIDE_CANDIDATE"
        next_stage = "R7.A4D2_ATR15_SHORT_CHILD_UNUSED_OOS_SOURCE_PLAN"
    elif primary_pass:
        classification = "BASE_ONLY_FRAGILE_SIDE_PARTITION"
        next_stage = "R7.A4D2_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT"
    else:
        classification = "SIDE_PARTITION_NOT_ECONOMICALLY_REPRODUCED"
        next_stage = "R7.A4D2_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT"

    parent_profiles = {
        profile: aggregate([
            row for row in candidate_rows
            if profile_name(str(row.get("cost_profile_id") or "")) == profile
        ])
        for profile in ("base", "adverse", "severe")
    }
    deltas = {
        profile: {
            "net_r_delta": profiles[profile]["net_r_sum"] - parent_profiles[profile]["net_r_sum"],
            "profit_factor_delta": profiles[profile]["profit_factor"] - parent_profiles[profile]["profit_factor"],
            "max_drawdown_r_delta": profiles[profile]["max_drawdown_r"] - parent_profiles[profile]["max_drawdown_r"],
            "unique_event_delta": profiles[profile]["unique_event_count"] - parent_profiles[profile]["unique_event_count"],
        }
        for profile in ("base", "adverse", "severe")
    }

    output = root / OUTPUT_DIR
    trade_count, trade_sha = atomic_jsonl(output / CHILD_TRADES_OUT.name, child_rows)
    cell_count, cell_sha = atomic_jsonl(output / CHILD_CELLS_OUT.name, child_cell_rows)
    summary = {
        "schema": "r7a4d2_atr15_side_specialization_economic_child_audit_v1",
        "official_stage": "R7.A4D2_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT",
        "state": "PASS_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT",
        "target_commit": args.target_sha,
        "blocker_count": 0,
        "blockers": [],
        "parent_lane_id": EXPECTED_LANE,
        "parent_variant_id": EXPECTED_VARIANT,
        "child_variant_id": "atr15_persistence_5m_trigger_short_only",
        "selected_side": EXPECTED_SIDE,
        "selection_origin": "SAME_STRICT_FORWARD_OOS_BASE_PRIMARY_CELL_POST_HOC_SIDE_PARTITION",
        "classification": classification,
        "coverage_ready": coverage_ready,
        "coverage_checks": coverage_checks,
        "primary_base_cell": {"cost_profile_id": BASE_COST, "timing_id": BASE_TIMING},
        "parent_primary_metrics": parent_primary,
        "child_primary_metrics": child_primary,
        "primary_checks": primary_checks,
        "parent_profile_metrics": parent_profiles,
        "child_profile_metrics": profiles,
        "profile_checks": profile_checks,
        "worst_severe_cell_metrics": worst_severe,
        "profile_deltas_vs_parent": deltas,
        "robust_same_oos_side_candidate": robust_same_oos,
        "conditional_same_oos_side_candidate": conditional_same_oos,
        "same_oos_selection_bias": True,
        "independent_oos_pass": False,
        "promotion_allowed": False,
        "portfolio_weight_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "parent_immutable": True,
        "side_filter_only": True,
        "parameter_optimization_allowed": False,
        "threshold_relaxation_allowed": False,
        "stop_target_mutation_allowed": False,
        "exit_logic_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "input_mutation_count": 0,
        "child_trade_row_count": trade_count,
        "child_trade_sha256": trade_sha,
        "child_cell_row_count": cell_count,
        "child_cell_sha256": cell_sha,
        "next_stage": next_stage,
    }
    atomic_json(output / SUMMARY_OUT.name, summary)

    print("STATE=PASS_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT")
    print("BLOCKER_COUNT=0")
    print("CHILD_CLASSIFICATION=" + classification)
    print("SELECTED_SIDE=" + EXPECTED_SIDE)
    print("PRIMARY_EVENTS=" + str(child_primary["unique_event_count"]))
    print("PRIMARY_SYMBOLS=" + str(child_primary["symbol_count"]))
    print("PRIMARY_FOLDS=" + str(child_primary["fold_count"]))
    print("PRIMARY_POS_FOLDS=" + str(child_primary["positive_fold_count"]))
    print("PRIMARY_GROSS_R=" + f"{child_primary['gross_r_sum']:.12f}")
    print("PRIMARY_DRAG_R=" + f"{child_primary['execution_drag_r_sum']:.12f}")
    print("PRIMARY_NET_R=" + f"{child_primary['net_r_sum']:.12f}")
    print("PRIMARY_PF=" + f"{child_primary['profit_factor']:.12f}")
    for profile in ("base", "adverse", "severe"):
        metrics = profiles[profile]
        print(
            f"CHILD_PROFILE={profile}|EVENTS={metrics['unique_event_count']}|SYMBOLS={metrics['symbol_count']}|"
            f"FOLDS={metrics['fold_count']}|POS_FOLDS={metrics['positive_fold_count']}|"
            f"GROSS_R={metrics['gross_r_sum']:.6f}|DRAG_R={metrics['execution_drag_r_sum']:.6f}|"
            f"NET_R={metrics['net_r_sum']:.6f}|PF={metrics['profit_factor']:.6f}|DD_R={metrics['max_drawdown_r']:.6f}"
        )
    print("WORST_SEVERE_NET_R=" + f"{finite(worst_severe.get('net_r_sum')):.12f}")
    print("WORST_SEVERE_PF=" + f"{finite(worst_severe.get('profit_factor')):.12f}")
    print("ROBUST_SAME_OOS=" + str(robust_same_oos).lower())
    print("CONDITIONAL_SAME_OOS=" + str(conditional_same_oos).lower())
    print("SAME_OOS_SELECTION_BIAS=true")
    print("PROMOTION_ALLOWED=false")
    print("SUMMARY_JSON=" + str(output / SUMMARY_OUT.name))
    print("INPUT_MUTATION_COUNT=0")
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
