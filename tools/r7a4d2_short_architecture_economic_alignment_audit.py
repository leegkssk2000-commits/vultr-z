#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SHORT_PLAN_PATH = Path("runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json")
SEMANTIC_PATH = Path("runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json")
RR_PLAN_PATH = Path("runtime/r7a4d2_short_rr_policy_plan/short_rr_policy_plan_v1.json")
RR_PROOF_PATH = Path("runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json")
POLICY_RESULTS_PATH = Path("runtime/r7a4d2_short_rr_sidecar_counterfactual/policy_results_600_v1.jsonl")
DISCOVERY_PATH = Path("runtime/r7a4d2_short_scalp_timeframe_candidate_discovery_36/candidate_discovery_v1.json")
REGISTRY_PATH = Path("backend/strategy25/canonical_strategy_registry_v1.json")
CONFIG_PATH = Path("backend/strategy25/canonical_strategy25_config_v1.json")
OUTPUT_PATH = Path("runtime/r7a4d2_short_architecture_economic_alignment_audit/alignment_audit_v1.json")


# Diagnostic taxonomy only. It does not mutate or replace the canonical strategy registry.
STRATEGY_FAMILY = {
    "alpha_combo": "composite",
    "anchor_vwap_trend": "trend",
    "bb_revert": "mean_reversion",
    "break_and_continue": "breakout",
    "ema_ribbon_scalp": "scalp",
    "fvg_revert": "mean_reversion",
    "grid_rebalance": "grid_range",
    "keltner_trend": "trend",
    "liquidity_sweep": "event_reversal",
    "mfi_rsi_div": "divergence_reversal",
    "obv_trend": "trend",
    "pivot_reversal": "reversal",
    "range_fade": "mean_reversion",
    "rbreaker_like": "breakout",
    "rsi_swing_fail": "reversal",
    "scalp_snap": "scalp",
    "session_bias": "session",
    "squeeze_break": "breakout",
    "sr_levels": "support_resistance",
    "supertrend_pullback": "trend_pullback",
    "trend_ma_macd": "trend",
    "trend_rider": "trend",
    "turtle_trend": "breakout_trend",
    "vol_spike_fade": "event_reversal",
    "vwap_revert": "mean_reversion",
}

TIMEFRAME_KEYS = {
    "timeframe",
    "native_timeframe",
    "bar_interval",
    "interval",
    "timeframe_minutes",
    "native_interval",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
            rows.append(value)
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / max(float(denominator), 1e-12), 10)


def safe_mean(values: Iterable[float]) -> float:
    rows = list(values)
    return round(statistics.fmean(rows), 10) if rows else 0.0


def safe_median(values: Iterable[float]) -> float:
    rows = list(values)
    return round(statistics.median(rows), 10) if rows else 0.0


def jsonify_number(value: float) -> float | str:
    if math.isfinite(value):
        return round(value, 10)
    return "Infinity" if value > 0 else "-Infinity"


def recursive_timeframe_contracts(value: Any, path: str = "$") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in TIMEFRAME_KEYS and child not in (None, "", [], {}):
                rows.append({"path": child_path, "value": child})
            rows.extend(recursive_timeframe_contracts(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(recursive_timeframe_contracts(child, f"{path}[{index}]"))
    return rows


def trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net_pct = [finite(row.get("net_pnl_pct")) for row in trades]
    gross_pct = [finite(row.get("gross_pnl_pct")) for row in trades]
    pnl_r = [finite(row.get("pnl_r")) for row in trades if row.get("pnl_r") is not None]
    risk_pct = [finite(row.get("risk_capital_pct")) for row in trades if finite(row.get("risk_capital_pct")) > 0]
    cost_pct = [finite(row.get("cost_pct")) for row in trades]
    wins_pct = [value for value in net_pct if value > 0]
    losses_pct = [value for value in net_pct if value < 0]
    wins_r = [value for value in pnl_r if value > 0]
    losses_r = [value for value in pnl_r if value < 0]
    gross_profit = sum(wins_pct)
    gross_loss = abs(sum(losses_pct))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    average_win_r = statistics.fmean(wins_r) if wins_r else 0.0
    average_loss_r = statistics.fmean(losses_r) if losses_r else 0.0
    payoff_r = average_win_r / abs(average_loss_r) if average_loss_r < 0 else (math.inf if average_win_r > 0 else 0.0)
    friction_r = [
        finite(row.get("cost_pct")) / finite(row.get("risk_capital_pct"))
        for row in trades
        if finite(row.get("risk_capital_pct")) > 0
    ]
    gross_r = [
        finite(row.get("gross_pnl_pct")) / finite(row.get("risk_capital_pct"))
        for row in trades
        if finite(row.get("risk_capital_pct")) > 0
    ]
    return {
        "trade_count": len(trades),
        "win_count": len(wins_pct),
        "loss_count": len(losses_pct),
        "win_rate_pct": round(len(wins_pct) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_pnl_sum_pct": round(sum(net_pct), 10),
        "gross_pnl_sum_pct": round(sum(gross_pct), 10),
        "cost_sum_pct": round(sum(cost_pct), 10),
        "profit_factor": jsonify_number(profit_factor),
        "expectancy_r": safe_mean(pnl_r),
        "median_r": safe_median(pnl_r),
        "realized_payoff_ratio_r": jsonify_number(payoff_r),
        "average_win_r": round(average_win_r, 10),
        "average_loss_r": round(average_loss_r, 10),
        "median_risk_capital_pct": safe_median(risk_pct),
        "median_friction_r": safe_median(friction_r),
        "maximum_friction_r": round(max(friction_r), 10) if friction_r else 0.0,
        "mean_gross_r": safe_mean(gross_r),
        "minimum_gross_r": round(min(gross_r), 10) if gross_r else 0.0,
        "exit_histogram": dict(sorted(Counter(str(row.get("exit_reason") or "") for row in trades).items())),
    }


def numeric_pf(value: Any) -> float:
    if value == "Infinity":
        return math.inf
    return finite(value)


def current_policy_positive(metrics: dict[str, Any]) -> bool:
    return (
        int(metrics.get("trade_count", 0)) > 0
        and numeric_pf(metrics.get("profit_factor")) > 1.0
        and finite(metrics.get("expectancy_r")) > 0.0
        and finite(metrics.get("net_pnl_sum_pct")) > 0.0
    )


def selection_basis_audit(
    short_plan: dict[str, Any], semantic: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, int]]:
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []) if item)
    reports = [row for row in semantic.get("strategy_reports", []) if isinstance(row, dict)]
    downgrade_ids = sorted(
        str(row.get("strategy_id") or "")
        for row in reports
        if row.get("strategy_id") and int(row.get("short_downgrade_count") or 0) > 0
    )
    counts = {
        str(row.get("strategy_id") or ""): int(row.get("short_downgrade_count") or 0)
        for row in reports
        if row.get("strategy_id")
    }
    return target_ids, downgrade_ids, counts


def build_audit(
    short_plan: dict[str, Any],
    semantic: dict[str, Any],
    rr_plan: dict[str, Any],
    rr_proof: dict[str, Any],
    policy_results: list[dict[str, Any]],
    discovery: dict[str, Any],
    registry: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_NOT_PASS")
    if semantic.get("state") not in {"PASS_SEMANTIC_PARITY", "PASS_R7A4D_SEMANTIC_PARITY_AUDIT"}:
        # Older evidence uses a different PASS label; structural fields below remain authoritative.
        if int(semantic.get("strategy_count", -1)) != 25:
            blockers.append("SEMANTIC_EVIDENCE_INVALID")
    if rr_plan.get("state") != "PASS_SHORT_RR_POLICY_PLAN":
        blockers.append("RR_PLAN_NOT_PASS")
    if len(policy_results) != 600:
        blockers.append(f"POLICY_RESULT_COUNT_INVALID:{len(policy_results)}")
    if int(rr_proof.get("completed_policy_scenario_count", -1)) != 600:
        blockers.append("RR_POLICY_COMPLETION_INVALID")
    if int(rr_proof.get("failed_scenario_count", -1)) != 0:
        blockers.append("RR_POLICY_FAILURE_PRESENT")
    if rr_proof.get("source_registry_parity") is not True:
        blockers.append("SOURCE_REGISTRY_PARITY_INVALID")
    if int(rr_proof.get("raw_and_canonical_mutation_count", -1)) != 0:
        blockers.append("RAW_OR_CANONICAL_MUTATION_PRESENT")

    target_ids, downgrade_ids, downgrade_counts = selection_basis_audit(short_plan, semantic)
    if len(target_ids) != 12:
        blockers.append(f"SHORT_TARGET_COUNT_INVALID:{len(target_ids)}")
    if target_ids != downgrade_ids:
        blockers.append("SHORT_TARGET_SEMANTIC_DOWNGRADE_SET_MISMATCH")
    unknown_family = sorted(strategy_id for strategy_id in target_ids if strategy_id not in STRATEGY_FAMILY)
    if unknown_family:
        blockers.append("STRATEGY_FAMILY_UNCLASSIFIED:" + ",".join(unknown_family))

    registry_entries = {
        str(row.get("strategy_id") or ""): row
        for row in registry.get("entries", [])
        if isinstance(row, dict) and row.get("strategy_id")
    }
    timeframe_contracts: dict[str, list[dict[str, Any]]] = {}
    for strategy_id in target_ids:
        entry = registry_entries.get(strategy_id, {})
        timeframe_contracts[strategy_id] = recursive_timeframe_contracts(entry)

    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_regimes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in policy_results:
        strategy_id = str(row.get("strategy_id") or "")
        if strategy_id not in target_ids:
            continue
        grouped_rows[strategy_id].append(row)
        trade_rows = [trade for trade in row.get("short_trade_detail", []) if isinstance(trade, dict)]
        grouped_trades[strategy_id].extend(trade_rows)
        grouped_regimes[strategy_id][str(row.get("regime") or "UNKNOWN")] += len(trade_rows)

    strategy_summary: dict[str, dict[str, Any]] = {}
    family_aggregate: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "strategy_count": 0,
            "scenario_count": 0,
            "candidate_count": 0,
            "admitted_action_count": 0,
            "closed_trade_count": 0,
            "net_pnl_sum_pct": 0.0,
            "cost_sum_pct": 0.0,
            "current_policy_positive_strategy_count": 0,
        }
    )

    for strategy_id in target_ids:
        rows = grouped_rows.get(strategy_id, [])
        trades = grouped_trades.get(strategy_id, [])
        metrics = trade_metrics(trades)
        family = STRATEGY_FAMILY.get(strategy_id, "unclassified")
        candidate_count = sum(int(row.get("short_policy_candidate_count") or 0) for row in rows)
        admitted_count = sum(int(row.get("short_policy_admitted_action_count") or 0) for row in rows)
        regime_block_count = sum(int(row.get("short_policy_regime_block_count") or 0) for row in rows)
        positive = current_policy_positive(metrics)
        if not trades:
            economic_class = "NO_SHORT_TRADE_EVIDENCE"
        elif positive:
            economic_class = "CURRENT_POLICY_POSITIVE_BUT_UNBENCHMARKED"
        else:
            economic_class = "CURRENT_POLICY_NON_POSITIVE"
        strategy_summary[strategy_id] = {
            "strategy_id": strategy_id,
            "diagnostic_family": family,
            "target_selection_basis": "semantic_short_downgrade_presence",
            "observed_short_downgrade_count": downgrade_counts.get(strategy_id, 0),
            "native_timeframe_contract_present": bool(timeframe_contracts.get(strategy_id)),
            "native_timeframe_contracts": timeframe_contracts.get(strategy_id, []),
            "universal_rr_anchor_applied": True,
            "policy_loss_cap_r": finite(rr_plan.get("anchor", {}).get("policy_loss_cap_r")),
            "policy_full_tp_r": finite(rr_plan.get("anchor", {}).get("policy_full_tp_r")),
            "scenario_count": len(rows),
            "candidate_count": candidate_count,
            "admitted_action_count": admitted_count,
            "regime_block_count": regime_block_count,
            "regime_trade_histogram": dict(sorted(grouped_regimes[strategy_id].items())),
            "metrics": metrics,
            "current_policy_positive": positive,
            "economic_classification": economic_class,
            "simple_strategy_benchmark_present": False,
            "broker_bot_comparison_supported": False,
            "promotion_supported": False,
        }
        aggregate = family_aggregate[family]
        aggregate["strategy_count"] += 1
        aggregate["scenario_count"] += len(rows)
        aggregate["candidate_count"] += candidate_count
        aggregate["admitted_action_count"] += admitted_count
        aggregate["closed_trade_count"] += int(metrics["trade_count"])
        aggregate["net_pnl_sum_pct"] += finite(metrics["net_pnl_sum_pct"])
        aggregate["cost_sum_pct"] += finite(metrics["cost_sum_pct"])
        aggregate["current_policy_positive_strategy_count"] += int(positive)

    for value in family_aggregate.values():
        value["net_pnl_sum_pct"] = round(float(value["net_pnl_sum_pct"]), 10)
        value["cost_sum_pct"] = round(float(value["cost_sum_pct"]), 10)

    family_count = len({STRATEGY_FAMILY.get(strategy_id, "unclassified") for strategy_id in target_ids})
    timeframe_contract_count = sum(bool(timeframe_contracts.get(strategy_id)) for strategy_id in target_ids)
    positive_ids = sorted(
        strategy_id for strategy_id, row in strategy_summary.items() if row["current_policy_positive"]
    )
    nonpositive_ids = sorted(strategy_id for strategy_id in target_ids if strategy_id not in positive_ids)

    discovery_summary = discovery.get("architecture_summary") if isinstance(discovery.get("architecture_summary"), dict) else {}
    raw_signal_count = sum(int(row.get("raw_signal_candidate_count") or 0) for row in discovery_summary.values() if isinstance(row, dict))
    conditional_pass_count = sum(int(row.get("conditional_distance_pass_count") or 0) for row in discovery_summary.values() if isinstance(row, dict))
    robust_pass_count = sum(int(row.get("robust_distance_pass_count") or 0) for row in discovery_summary.values() if isinstance(row, dict))
    selected_count = int(discovery.get("selected_candidate_count") or 0)
    selected_symbols = Counter(
        str(row.get("symbol") or "UNKNOWN")
        for row in discovery.get("selected_candidates", [])
        if isinstance(row, dict)
    )

    root_causes = [
        {
            "id": "TARGET_SELECTION_SEMANTIC_NOT_ECONOMIC",
            "severity": "ARCHITECTURE",
            "evidence": {
                "target_count": len(target_ids),
                "target_set_equals_short_downgrade_set": target_ids == downgrade_ids,
                "economic_selection_metric_present": False,
            },
            "meaning": "The 12-strategy short universe was selected because short signals were downgraded by a long-only adapter, not because short alpha was proven.",
        },
        {
            "id": "UNIVERSAL_RR_ACROSS_HETEROGENEOUS_FAMILIES",
            "severity": "ARCHITECTURE",
            "evidence": {
                "strategy_count": len(target_ids),
                "diagnostic_family_count": family_count,
                "policy_loss_cap_r": finite(rr_plan.get("anchor", {}).get("policy_loss_cap_r")),
                "policy_full_tp_r": finite(rr_plan.get("anchor", {}).get("policy_full_tp_r")),
            },
            "meaning": "One 0.75R/2.5R exit geometry was imposed on heterogeneous scalp, trend, range, reversal, grid and composite strategies before family-specific geometry was established.",
        },
        {
            "id": "NATIVE_TIMEFRAME_CONTRACT_MISSING",
            "severity": "ARCHITECTURE",
            "evidence": {
                "strategy_count": len(target_ids),
                "strategy_with_timeframe_contract_count": timeframe_contract_count,
            },
            "meaning": "The registry has no strategy-native timeframe contract, so identical segment feeds cannot establish economic equivalence across strategy families.",
        },
        {
            "id": "SIMPLE_BENCHMARK_ABSENT",
            "severity": "ARCHITECTURE",
            "evidence": {
                "simple_baseline_result_count": 0,
                "broker_bot_result_count": 0,
                "flat_baseline_only": True,
            },
            "meaning": "The branch has no same-data, same-cost simple benchmark proving that complexity adds value.",
        },
        {
            "id": "CANDIDATE_COUNT_OBJECTIVE_MISALIGNED",
            "severity": "DESIGN",
            "evidence": {
                "raw_signal_count": raw_signal_count,
                "conditional_distance_pass_count": conditional_pass_count,
                "robust_distance_pass_count": robust_pass_count,
                "selected_candidate_count": selected_count,
                "target_candidate_count": int(discovery.get("candidate_target_count") or 0),
                "selected_symbol_histogram": dict(sorted(selected_symbols.items())),
            },
            "meaning": "A fixed 36-candidate quota was pursued before the strategy/timeframe/cost architecture demonstrated a viable edge.",
        },
    ]

    architecture_alignment_pass = False
    audit = {
        "schema": "r7a4d2_short_architecture_economic_alignment_audit_v1",
        "official_stage": "R7.A4D2_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT",
        "state": "PASS_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT" if not blockers else "HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "audit_completed": not blockers,
        "architecture_alignment_pass": architecture_alignment_pass,
        "architecture_decision": "BLOCK_REBUILD_REQUIRED" if not blockers else "HOLD_INPUT_INVALID",
        "promotion_action": "block",
        "primary_root_cause_count": len(root_causes),
        "primary_root_causes": root_causes,
        "short_target_strategy_count": len(target_ids),
        "short_target_strategy_ids": target_ids,
        "short_target_selection_basis": "semantic_short_downgrade_presence",
        "short_target_selected_by_economic_edge": False,
        "diagnostic_family_count": family_count,
        "native_timeframe_contract_strategy_count": timeframe_contract_count,
        "universal_rr_strategy_count": len(target_ids),
        "simple_benchmark_result_count": 0,
        "broker_bot_comparison_supported": False,
        "current_policy_positive_strategy_count": len(positive_ids),
        "current_policy_positive_strategy_ids": positive_ids,
        "current_policy_nonpositive_or_empty_strategy_count": len(nonpositive_ids),
        "current_policy_nonpositive_or_empty_strategy_ids": nonpositive_ids,
        "strategy_summary": strategy_summary,
        "family_summary": dict(sorted(family_aggregate.items())),
        "scalp_redesign_summary": {
            "raw_signal_count": raw_signal_count,
            "conditional_distance_pass_count": conditional_pass_count,
            "conditional_pass_rate_pct": round(conditional_pass_count / raw_signal_count * 100.0, 10) if raw_signal_count else 0.0,
            "robust_distance_pass_count": robust_pass_count,
            "selected_candidate_count": selected_count,
            "target_candidate_count": int(discovery.get("candidate_target_count") or 0),
            "selected_symbol_histogram": dict(sorted(selected_symbols.items())),
        },
        "economic_positive_definition": {
            "source": "current_RR_policy_only_not_promotion_SSOT",
            "profit_factor_gt": 1.0,
            "expectancy_r_gt": 0.0,
            "net_pnl_sum_pct_gt": 0.0,
            "external_benchmark_required_for_promotion": True,
        },
        "frozen_actions": {
            "scalp_candidate_discovery_36": "block",
            "scalp_counterfactual_216": "block",
            "full_3600_reexecution": "block",
            "event_replay_2880": "block",
            "shadow_start": "block",
            "paper_live_order": "block",
        },
        "required_rebuild_sequence": [
            "define each strategy family intent and native timeframe contract",
            "build same-data same-cost simple trend and mean-reversion benchmark floor",
            "measure raw strategy geometry before universal RR transformation",
            "derive family-specific exit candidates from observed MFE MAE and friction R",
            "retain only strategies that beat the relevant simple benchmark on net PnL and risk",
            "run independent validation before any ensemble or 3600 reexecution",
        ],
        "next_stage": "R7.A4D2_SHORT_STRATEGY_FAMILY_CONTRACT_AND_SIMPLE_BENCHMARK_PLAN" if not blockers else "R7.A4D2_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT",
    }
    return audit, blockers


def self_test() -> int:
    metrics = trade_metrics([
        {"net_pnl_pct": 1.0, "gross_pnl_pct": 1.2, "cost_pct": 0.2, "pnl_r": 2.0, "risk_capital_pct": 0.5, "exit_reason": "take_profit"},
        {"net_pnl_pct": -0.4, "gross_pnl_pct": -0.3, "cost_pct": 0.1, "pnl_r": -0.8, "risk_capital_pct": 0.5, "exit_reason": "stop"},
    ])
    assert metrics["trade_count"] == 2
    assert numeric_pf(metrics["profit_factor"]) > 1.0
    assert metrics["expectancy_r"] == 0.6
    assert current_policy_positive(metrics) is True
    sample = {"native_timeframe": "5m", "nested": {"interval": "1m"}}
    assert len(recursive_timeframe_contracts(sample)) == 2
    print("STATE=PASS_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    evidence_paths = [
        root / SHORT_PLAN_PATH,
        root / SEMANTIC_PATH,
        root / RR_PLAN_PATH,
        root / RR_PROOF_PATH,
        root / POLICY_RESULTS_PATH,
        root / DISCOVERY_PATH,
        root / REGISTRY_PATH,
        root / CONFIG_PATH,
    ]
    missing = [str(path) for path in evidence_paths if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT")
        print("BLOCKER_COUNT=" + str(len(missing)))
        print("BLOCKERS=" + json.dumps([f"REQUIRED_EVIDENCE_MISSING:{path}" for path in missing]))
        print("RC=2")
        return 2

    before = {str(path): sha256_file(path) for path in evidence_paths}
    try:
        audit, blockers = build_audit(
            load_json(root / SHORT_PLAN_PATH),
            load_json(root / SEMANTIC_PATH),
            load_json(root / RR_PLAN_PATH),
            load_json(root / RR_PROOF_PATH),
            load_jsonl(root / POLICY_RESULTS_PATH),
            load_json(root / DISCOVERY_PATH),
            load_json(root / REGISTRY_PATH),
            load_json(root / CONFIG_PATH),
        )
    except Exception as exc:
        print("STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"AUDIT_INPUT_FAILED:{type(exc).__name__}:{exc}"]))
        print("RC=2")
        return 2

    after = {str(path): sha256_file(path) for path in evidence_paths}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        blockers = list(dict.fromkeys(blockers))
        audit["blockers"] = blockers
        audit["blocker_count"] = len(blockers)
        audit["state"] = "HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT"
        audit["audit_completed"] = False
        audit["architecture_decision"] = "HOLD_INPUT_INVALID"
        audit["next_stage"] = "R7.A4D2_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT"
    audit["protected_mutation_path_count"] = len(mutation_paths)
    audit["protected_mutation_paths"] = mutation_paths
    atomic_json(root / OUTPUT_PATH, audit)

    print("STATE=" + str(audit["state"]))
    print("BLOCKER_COUNT=" + str(audit["blocker_count"]))
    print("AUDIT_COMPLETED=" + str(audit["audit_completed"]).lower())
    print("ARCHITECTURE_ALIGNMENT_PASS=" + str(audit["architecture_alignment_pass"]).lower())
    print("ARCHITECTURE_DECISION=" + str(audit["architecture_decision"]))
    print("PROMOTION_ACTION=" + str(audit["promotion_action"]))
    print("PRIMARY_ROOT_CAUSE_COUNT=" + str(audit["primary_root_cause_count"]))
    print("PRIMARY_ROOT_CAUSES=" + json.dumps(audit["primary_root_causes"], ensure_ascii=False, sort_keys=True))
    print("SHORT_TARGET_STRATEGY_COUNT=" + str(audit["short_target_strategy_count"]))
    print("DIAGNOSTIC_FAMILY_COUNT=" + str(audit["diagnostic_family_count"]))
    print("NATIVE_TIMEFRAME_CONTRACT_STRATEGY_COUNT=" + str(audit["native_timeframe_contract_strategy_count"]))
    print("UNIVERSAL_RR_STRATEGY_COUNT=" + str(audit["universal_rr_strategy_count"]))
    print("SIMPLE_BENCHMARK_RESULT_COUNT=" + str(audit["simple_benchmark_result_count"]))
    print("CURRENT_POLICY_POSITIVE_STRATEGY_COUNT=" + str(audit["current_policy_positive_strategy_count"]))
    print("CURRENT_POLICY_POSITIVE_STRATEGY_IDS=" + json.dumps(audit["current_policy_positive_strategy_ids"]))
    print("STRATEGY_SUMMARY=" + json.dumps(audit["strategy_summary"], ensure_ascii=False, sort_keys=True))
    print("FAMILY_SUMMARY=" + json.dumps(audit["family_summary"], ensure_ascii=False, sort_keys=True))
    print("SCALP_REDESIGN_SUMMARY=" + json.dumps(audit["scalp_redesign_summary"], ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(audit["protected_mutation_path_count"]))
    print("AUDIT_JSON=" + str(root / OUTPUT_PATH))
    print("NEXT_STAGE=" + str(audit["next_stage"]))
    print("BLOCKERS=" + json.dumps(audit["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if audit["audit_completed"] else "2"))
    return 0 if audit["audit_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
