#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PREVIOUS_SUMMARY = Path("runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_baseline_and_data_coverage_v1.json")
PREVIOUS_TRADES = Path("runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_trade_results_v1.jsonl")
PREVIOUS_CELLS = Path("runtime/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit/benchmark_cell_results_v1.jsonl")
MACRO_PLAN = Path("runtime/r7a4d2_short_macro_alpha_reset_plan/macro_alpha_reset_plan_v1.json")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
OUTPUT_DIR = Path("runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan")

EXPECTED_OLD_LANES = 10
EXPECTED_OLD_CELLS = 60
EXPECTED_SEGMENTS = 24
EXPECTED_V2_BOTS = 6
EXPECTED_V2_TIMEFRAMES = 2
EXPECTED_V2_LANES = 12
EXPECTED_V2_STRESS_PER_LANE = 6
EXPECTED_V2_CELLS = 72
TIMEFRAME_MINUTES = {"5m": 5, "15m": 15}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
            rows.append(value)
    return rows


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default


def safe_median(values: list[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.median(clean) if clean else None


def percentile(values: list[float], q: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * q
    lower = int(math.floor(position)); upper = int(math.ceil(position))
    if lower == upper:
        return clean[lower]
    weight = position - lower
    return clean[lower] * (1.0 - weight) + clean[upper] * weight


def cost_profiles(contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    perturbations = [row for row in contract.get("perturbations", []) if isinstance(row, dict)]
    for profile in contract.get("cost_profiles", []):
        if not isinstance(profile, dict):
            continue
        fee = finite(profile.get("fee_bps_per_side")); slip = finite(profile.get("slippage_bps_per_side"))
        round_trip_pct = 2.0 * (fee + slip) / 100.0
        timing_rows = []
        for perturbation in perturbations:
            total_bars = int(profile.get("latency_bars") or 0) + int(perturbation.get("additional_entry_delay_bars") or 0)
            timing_rows.append({
                "perturbation_id": perturbation.get("id"),
                "entry_delay_bars": total_bars,
                "exit_delay_bars": int(profile.get("latency_bars") or 0) + int(perturbation.get("additional_exit_delay_bars") or 0),
                "entry_delay_minutes_5m": total_bars * 5,
                "entry_delay_minutes_15m": total_bars * 15,
            })
        rows.append({
            "id": profile.get("id"), "label": profile.get("label"),
            "fee_bps_per_side": fee, "slippage_bps_per_side": slip,
            "round_trip_cost_pct": round_trip_pct,
            "latency_bars": int(profile.get("latency_bars") or 0),
            "timing_rows": timing_rows,
        })
    return rows


def trade_audit_rows(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    augmented: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        entry = finite(row.get("entry_price"), math.nan)
        target = finite(row.get("target_price"), math.nan)
        risk = finite(row.get("risk_pct"), math.nan)
        cost = finite(row.get("round_trip_cost_pct"), math.nan)
        target_move = abs(entry - target) / entry * 100.0 if entry > 0 and target > 0 else math.nan
        cost_to_risk = cost / risk if risk > 0 else math.inf
        target_to_cost = target_move / cost if cost > 0 else math.inf
        item = {
            "lane_id": str(row.get("lane_id") or ""),
            "benchmark_id": str(row.get("benchmark_id") or ""),
            "timeframe": str(row.get("timeframe") or ""),
            "cost_profile_id": str(row.get("cost_profile_id") or ""),
            "perturbation_id": str(row.get("perturbation_id") or ""),
            "risk_pct": risk,
            "round_trip_cost_pct": cost,
            "target_move_pct": target_move,
            "cost_to_risk_ratio": cost_to_risk,
            "target_to_cost_ratio": target_to_cost,
            "take_profit_net_loss": str(row.get("exit_reason") or "") == "take_profit" and finite(row.get("net_return_pct")) <= 0.0,
            "net_return_pct": finite(row.get("net_return_pct")),
        }
        augmented.append(item)
        grouped[item["lane_id"]].append(item)

    lane_rows: list[dict[str, Any]] = []
    for lane_id, rows in sorted(grouped.items()):
        ratios = [finite(row["cost_to_risk_ratio"], math.inf) for row in rows]
        target_ratios = [finite(row["target_to_cost_ratio"], math.inf) for row in rows]
        lane_rows.append({
            "lane_id": lane_id,
            "benchmark_id": rows[0]["benchmark_id"],
            "timeframe": rows[0]["timeframe"],
            "trade_instance_count_across_stress": len(rows),
            "median_cost_to_risk_ratio": safe_median(ratios),
            "p75_cost_to_risk_ratio": percentile(ratios, 0.75),
            "median_target_to_cost_ratio": safe_median(target_ratios),
            "target_below_3x_cost_count": sum(1 for value in target_ratios if value < 3.0),
            "target_below_3x_cost_pct": 100.0 * sum(1 for value in target_ratios if value < 3.0) / len(target_ratios),
            "cost_exceeds_risk_count": sum(1 for value in ratios if value >= 1.0),
            "cost_exceeds_risk_pct": 100.0 * sum(1 for value in ratios if value >= 1.0) / len(ratios),
            "take_profit_net_loss_count": sum(1 for row in rows if row["take_profit_net_loss"]),
        })
    return augmented, lane_rows


def corrected_execution_model(contract: dict[str, Any]) -> dict[str, Any]:
    profiles = []
    for profile in contract.get("cost_profiles", []):
        if not isinstance(profile, dict):
            continue
        profiles.append({
            "id": str(profile.get("id")),
            "label": str(profile.get("label")),
            "fee_bps_per_side": finite(profile.get("fee_bps_per_side")),
            "slippage_bps_per_side": finite(profile.get("slippage_bps_per_side")),
            "funding_bps_per_8h": finite(profile.get("funding_bps_per_8h")),
            "latency_bars": 0,
            "round_trip_cost_pct": 2.0 * (finite(profile.get("fee_bps_per_side")) + finite(profile.get("slippage_bps_per_side"))) / 100.0,
            "role": "PRIMARY_BASELINE" if str(profile.get("id")) == "cost_profile_0" else (
                "REQUIRED_ADVERSE_GATE" if str(profile.get("id")) == "cost_profile_1" else "TAIL_ROBUSTNESS_ONLY"),
        })
    return {
        "model_id": "exchange_execution_economics_v2_non_live",
        "source_cost_values_preserved": True,
        "bar_latency_removed": True,
        "reason": "bar delay is not exchange latency; next-bar fill already discretizes signal-to-order timing",
        "profiles": profiles,
        "timing_perturbations": [
            {"id": "timing_0", "label": "canonical_next_bar_fill", "additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0, "additional_slippage_bps_per_side": 0.0},
            {"id": "timing_1", "label": "adverse_fill_price_stress", "additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0, "additional_slippage_bps_per_side": 5.0, "assumption_scope": "NON_LIVE_CALIBRATION_REQUIRES_LATER_SSOT_REPLACEMENT"},
        ],
        "economic_admission": {
            "minimum_target_to_base_round_trip_cost_ratio": 3.0,
            "minimum_risk_to_base_round_trip_cost_ratio": 2.0,
            "minimum_target_to_adverse_round_trip_cost_ratio": 2.0,
            "base_and_adverse_must_both_have_positive_expectancy": True,
            "base_and_adverse_must_both_have_positive_net_pnl": True,
            "minimum_positive_walk_forward_folds": 4,
            "required_walk_forward_fold_count": 6,
            "severe_profile_is_tail_robustness_not_primary_selection": True,
            "negative_benchmark_outperformance_promotion_allowed": False,
        },
    }


def exchange_bot_benchmarks() -> list[dict[str, Any]]:
    return [
        {"bot_id": "dual_ma_trend_bot", "family": "trend", "timeframes": ["5m", "15m"], "directions": ["long", "short"], "execution": "taker_or_maker_filtered", "entry_gate": "expected_move_after_cost>=3x_base_cost", "exit": "opposite_cross_or_atr_trailing"},
        {"bot_id": "dual_donchian_trend_bot", "family": "trend", "timeframes": ["5m", "15m"], "directions": ["long", "short"], "execution": "breakout_taker", "entry_gate": "breakout_range_after_cost>=3x_base_cost", "exit": "channel_reclaim_or_atr_trailing"},
        {"bot_id": "dual_atr_volatility_bot", "family": "breakout", "timeframes": ["5m", "15m"], "directions": ["long", "short"], "execution": "taker", "entry_gate": "range_expansion_and_volume_with_cost_floor", "exit": "atr_trailing_and_timeout"},
        {"bot_id": "dual_vwap_mean_reversion_bot", "family": "mean_reversion", "timeframes": ["5m", "15m"], "directions": ["long", "short"], "execution": "maker_first", "entry_gate": "deviation_to_vwap_after_cost>=3x_base_cost", "exit": "vwap_touch_or_structural_invalidation"},
        {"bot_id": "neutral_multi_level_grid_bot", "family": "grid_range", "timeframes": ["5m", "15m"], "directions": ["neutral"], "execution": "maker_first_multi_order", "entry_gate": "grid_spacing>=3x_base_cost_and_range_regime", "exit": "realized_grid_cycles_with_inventory_cap", "single_cycle_short_allowed": False},
        {"bot_id": "directional_trend_grid_bot", "family": "grid_trend", "timeframes": ["5m", "15m"], "directions": ["long_grid", "short_grid"], "execution": "maker_first_with_trend_bias", "entry_gate": "trend_regime_and_grid_spacing>=3x_base_cost", "exit": "trend_break_or_inventory_stop"},
    ]


def self_test() -> int:
    synthetic = [{"lane_id": "x:5m", "benchmark_id": "x", "timeframe": "5m", "cost_profile_id": "cost_profile_0", "perturbation_id": "perturbation_0", "entry_price": 100.0, "target_price": 99.7, "risk_pct": 0.2, "round_trip_cost_pct": 0.12, "exit_reason": "take_profit", "net_return_pct": -0.01}]
    _, lanes = trade_audit_rows(synthetic)
    assert lanes[0]["take_profit_net_loss_count"] == 1
    assert lanes[0]["cost_exceeds_risk_pct"] == 0.0
    print("STATE=PASS_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_SELF_TEST")
    print("RC=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--a4d-contract")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.a4d_contract:
        raise SystemExit("--a4d-contract required")

    root = Path(args.root).resolve()
    required = [root / PREVIOUS_SUMMARY, root / PREVIOUS_TRADES, root / PREVIOUS_CELLS,
                root / MACRO_PLAN, root / MANIFEST, Path(args.a4d_contract).resolve()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    summary = load_json(root / PREVIOUS_SUMMARY)
    trades = load_jsonl(root / PREVIOUS_TRADES)
    cells = load_jsonl(root / PREVIOUS_CELLS)
    macro = load_json(root / MACRO_PLAN)
    manifest = load_json(root / MANIFEST)
    contract = load_json(Path(args.a4d_contract).resolve())
    blockers: list[str] = []

    if summary.get("state") != "PASS_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT":
        blockers.append("PREVIOUS_BENCHMARK_NOT_PASS")
    if int(summary.get("benchmark_lane_count") or 0) != EXPECTED_OLD_LANES:
        blockers.append("PREVIOUS_LANE_COUNT_INVALID")
    if len(cells) != EXPECTED_OLD_CELLS:
        blockers.append(f"PREVIOUS_CELL_COUNT_INVALID:{len(cells)}")
    if not trades:
        blockers.append("PREVIOUS_TRADES_EMPTY")
    if macro.get("state") != "PASS_SHORT_MACRO_ALPHA_RESET_PLAN":
        blockers.append("MACRO_PLAN_NOT_PASS")
    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    if len(segments) != EXPECTED_SEGMENTS:
        blockers.append(f"SEGMENT_COUNT_INVALID:{len(segments)}")
    profiles = cost_profiles(contract)
    if len(profiles) != 3:
        blockers.append(f"COST_PROFILE_COUNT_INVALID:{len(profiles)}")

    if blockers:
        print("STATE=HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    _, lane_audit = trade_audit_rows(trades)
    bots = exchange_bot_benchmarks()
    v2_lanes = [f"{bot['bot_id']}:{timeframe}" for bot in bots for timeframe in bot["timeframes"]]
    if len(bots) != EXPECTED_V2_BOTS or len(v2_lanes) != EXPECTED_V2_LANES:
        blockers.append("V2_BENCHMARK_SHAPE_INVALID")

    all_ratios = [finite(row.get("median_cost_to_risk_ratio"), math.inf) for row in lane_audit]
    all_target_ratios = [finite(row.get("median_target_to_cost_ratio"), math.inf) for row in lane_audit]
    root_causes = [
        {"id": "BAR_LATENCY_UNIT_ERROR", "severity": "CRITICAL", "evidence": "latency_bars plus timing perturbation produces 0-3 full bars of entry and exit delay", "repair": "set latency_bars=0; absorb sub-bar execution delay into slippage"},
        {"id": "COST_ENVELOPE_NOT_ADMISSION_GATED", "severity": "CRITICAL", "evidence": "signals were admitted without target-to-cost or risk-to-cost floor", "repair": "reject entries below 3x base round-trip target and 2x base round-trip risk"},
        {"id": "SEVERE_PROFILE_USED_AS_PRIMARY_SELECTOR", "severity": "MAJOR", "evidence": "lane PASS required severe cell and 4/6 cells", "repair": "base and adverse determine economic viability; severe is tail robustness only"},
        {"id": "SHORT_ONLY_DIRECTION_BIAS", "severity": "MAJOR", "evidence": "all five simple benchmarks were short-only across mixed trend_up/range/trend_down regimes", "repair": "dual direction for trend/reversion; regime-routed direction for grid"},
        {"id": "GRID_MODEL_NOT_EXCHANGE_GRID", "severity": "CRITICAL", "evidence": "single-cycle upper-quartile short was labeled grid", "repair": "multi-level maker-first inventory-capped realized grid cycles"},
        {"id": "NEGATIVE_BASELINE_RELATIVE_PROMOTION_RISK", "severity": "MAJOR", "evidence": "factor engines could appear superior merely by losing less than negative baselines", "repair": "absolute positive expectancy/PnL gates remain mandatory"},
    ]

    calibration = corrected_execution_model(contract)
    output = root / OUTPUT_DIR
    state = "PASS_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN" if not blockers else "HOLD_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN"
    next_stage = "R7.A4D2_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72" if not blockers else "R7.A4D2_SHORT_ECONOMIC_CALIBRATION_DIAGNOSE"
    plan = {
        "schema": "r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan_v1",
        "official_stage": "R7.A4D2_SHORT_ECONOMIC_CALIBRATION_AND_EXCHANGE_BOT_BENCHMARK_V2_PLAN",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "previous_benchmark_lane_count": int(summary.get("benchmark_lane_count") or 0),
        "previous_benchmark_cell_count": len(cells),
        "previous_trade_instance_count_across_stress": len(trades),
        "previous_economic_pass_lane_count": int(summary.get("baseline_economic_pass_lane_count") or 0),
        "old_cost_profiles": profiles,
        "old_lane_economic_audit": lane_audit,
        "portfolio_median_lane_cost_to_risk_ratio": safe_median(all_ratios),
        "portfolio_median_lane_target_to_cost_ratio": safe_median(all_target_ratios),
        "root_causes": root_causes,
        "corrected_execution_model": calibration,
        "exchange_bot_benchmarks_v2": bots,
        "v2_benchmark_count": len(bots),
        "v2_lane_count": len(v2_lanes),
        "v2_lane_ids": v2_lanes,
        "v2_stress_cell_per_lane": EXPECTED_V2_STRESS_PER_LANE,
        "v2_cell_target": EXPECTED_V2_CELLS,
        "selected_segment_count": len(segments),
        "parameter_optimization_allowed": False,
        "strategy_mutation_allowed": False,
        "market_source_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }
    atomic_json(output / "economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json", plan)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("PREVIOUS_BENCHMARK_LANE_COUNT=" + str(plan["previous_benchmark_lane_count"]))
    print("PREVIOUS_BENCHMARK_CELL_COUNT=" + str(plan["previous_benchmark_cell_count"]))
    print("PREVIOUS_TRADE_INSTANCE_COUNT_ACROSS_STRESS=" + str(plan["previous_trade_instance_count_across_stress"]))
    print("PREVIOUS_ECONOMIC_PASS_LANE_COUNT=" + str(plan["previous_economic_pass_lane_count"]))
    print("PORTFOLIO_MEDIAN_LANE_COST_TO_RISK_RATIO=" + str(plan["portfolio_median_lane_cost_to_risk_ratio"]))
    print("PORTFOLIO_MEDIAN_LANE_TARGET_TO_COST_RATIO=" + str(plan["portfolio_median_lane_target_to_cost_ratio"]))
    print("ROOT_CAUSES=" + json.dumps(root_causes, ensure_ascii=False, sort_keys=True))
    print("CORRECTED_EXECUTION_MODEL=" + json.dumps(calibration, ensure_ascii=False, sort_keys=True))
    print("EXCHANGE_BOT_BENCHMARK_V2_COUNT=" + str(len(bots)))
    print("EXCHANGE_BOT_BENCHMARK_V2_LANE_COUNT=" + str(len(v2_lanes)))
    print("EXCHANGE_BOT_BENCHMARK_V2_CELL_TARGET=" + str(EXPECTED_V2_CELLS))
    print("EXCHANGE_BOT_BENCHMARKS_V2=" + json.dumps(bots, ensure_ascii=False, sort_keys=True))
    print("PLAN_JSON=" + str(output / "economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
