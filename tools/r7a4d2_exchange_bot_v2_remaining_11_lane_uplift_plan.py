#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

SUMMARY_PATH = Path(
    "runtime/r7a4d2_short_exchange_bot_benchmark_v2_execution_72/"
    "exchange_bot_v2_summary_v1.json"
)
OUTPUT_DIR = Path(
    "runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_plan"
)
EXPECTED_LANE_COUNT = 12
EXPECTED_PASS_LANE_COUNT = 1
EXPECTED_FAILED_LANE_COUNT = 11
EXPECTED_REPAIR_VARIANTS_PER_LANE = 2
EXPECTED_REPAIR_BUNDLE_COUNT = 22
EXPECTED_STRESS_PER_BUNDLE = 6
EXPECTED_DISCOVERY_CELL_TARGET = 132
REFERENCE_LANE_ID = "dual_donchian_trend_bot:15m"

STRATEGY_MUTATION_ALLOWED = False
REGISTRY_MUTATION_ALLOWED = False
CONFIG_MUTATION_ALLOWED = False
ROUTER_MUTATION_ALLOWED = False
SERVICE_MUTATION_ALLOWED = False
SHADOW_START_ALLOWED = False
PAPER_LIVE_ORDER_ALLOWED = False
PARAMETER_OPTIMIZATION_ALLOWED = False
BLIND_STOP_WIDENING_ALLOWED = False
ENTRY_THRESHOLD_RELAXATION_ALLOWED = False
DISCOVERY_S_GRADE_LABEL_ALLOWED = False

LANE_REPAIR_CONTRACTS: dict[str, dict[str, Any]] = {
    "dual_atr_volatility_bot:15m": {
        "repair_class": "COST_FRAGILE_POSITIVE_BASE",
        "family": "breakout",
        "diagnosis": "base edge is positive; adverse fee/slippage destroys expectancy",
        "variants": [
            {
                "variant_id": "atr15_close_retest_maker",
                "entry": "15m expansion close then first controlled retest; maker-first limit",
                "regime": "trend_up/trend_down only; range and shock-recovery veto",
                "exit": "ATR structural stop; 3.5R target; timeout only after retest failure",
                "execution": "maker_first_then_taker_fallback_once",
            },
            {
                "variant_id": "atr15_breakout_persistence",
                "entry": "two-close persistence beyond 10-bar boundary with positive volume impulse",
                "regime": "direction aligned with 50EMA slope and market breadth proxy",
                "exit": "partial at 2R then structural runner to 4R; original risk cap preserved",
                "execution": "post_only_entry_with_cancel_replace_cap_1",
            },
        ],
    },
    "dual_atr_volatility_bot:5m": {
        "repair_class": "COST_FRAGILE_POSITIVE_BASE",
        "family": "breakout",
        "diagnosis": "strong base PnL but 5m churn and adverse costs erase edge",
        "variants": [
            {
                "variant_id": "atr5_with_15m_context_retest",
                "entry": "5m retest after expansion only when 15m trend context agrees",
                "regime": "15m trend alignment; shock-recovery and range veto",
                "exit": "5m structural stop, target at >=4x base round-trip cost",
                "execution": "maker_first",
            },
            {
                "variant_id": "atr5_impulse_quality_filter",
                "entry": "range expansion plus close-location and volume persistence filter",
                "regime": "trade only top-quality impulse quartile by causal fixed thresholds",
                "exit": "time stop shortened when MFE fails; no stop widening",
                "execution": "maker_first_or_skip",
            },
        ],
    },
    "dual_donchian_trend_bot:5m": {
        "repair_class": "COST_FRAGILE_POSITIVE_BASE",
        "family": "trend",
        "diagnosis": "base marginally positive; raw 5m breakout is highly cost-sensitive",
        "variants": [
            {
                "variant_id": "donchian5_15m_context_retest",
                "entry": "15m Donchian direction, 5m breakout-retest execution",
                "regime": "15m trend only; 5m range entries blocked",
                "exit": "prior 5m swing invalidation; midpoint reclaim exit",
                "execution": "maker_first",
            },
            {
                "variant_id": "donchian5_false_break_filter",
                "entry": "breakout must hold two closes then retest boundary",
                "regime": "exclude shock-recovery first impulse",
                "exit": "2R partial plus channel runner; fixed risk cap",
                "execution": "post_only_then_cancel",
            },
        ],
    },
    "dual_ma_trend_bot:15m": {
        "repair_class": "COST_FRAGILE_POSITIVE_BASE",
        "family": "trend",
        "diagnosis": "base slightly positive but cross entry is late and cost-fragile",
        "variants": [
            {
                "variant_id": "ma15_cross_then_pullback",
                "entry": "12/26 cross establishes context; entry waits for first pullback reclaim",
                "regime": "EMA slope persistence and Donchian location confirmation",
                "exit": "opposite reclaim or 3R target; no blind timeout extension",
                "execution": "maker_first",
            },
            {
                "variant_id": "ma15_slope_acceleration",
                "entry": "EMA separation acceleration plus close above/below both averages",
                "regime": "trend regime only; range veto",
                "exit": "ATR structural trailing after 1.5R MFE",
                "execution": "maker_first_or_skip",
            },
        ],
    },
    "dual_vwap_mean_reversion_bot:15m": {
        "repair_class": "COST_FRAGILE_POSITIVE_BASE",
        "family": "mean_reversion",
        "diagnosis": "base positive with 4/6 folds; trend contamination and costs break adverse",
        "variants": [
            {
                "variant_id": "vwap15_range_only_outer_reclaim",
                "entry": "outer deviation excursion then close back inside; maker-first",
                "regime": "range only; trend and shock-recovery veto",
                "exit": "VWAP touch partial then midpoint/structure invalidation",
                "execution": "maker_first",
            },
            {
                "variant_id": "vwap15_session_anchor_reversion",
                "entry": "session-anchored VWAP deviation with wick rejection",
                "regime": "flat anchor slope and compressed ATR only",
                "exit": "anchor touch or fixed structural stop; no threshold relaxation",
                "execution": "post_only_then_cancel",
            },
        ],
    },
    "neutral_multi_level_grid_bot:5m": {
        "repair_class": "HIGH_HIT_RATE_NEGATIVE_GEOMETRY",
        "family": "grid_range",
        "diagnosis": "70.83% win rate but spacing/cost/inventory geometry is negative",
        "variants": [
            {
                "variant_id": "neutral_grid5_cost_spaced_inventory_cap",
                "entry": "four maker levels with spacing >=4x base round-trip cost",
                "regime": "15m flat range context; trend and shock-recovery veto",
                "exit": "realized adjacent-level cycle accounting; inventory cap two",
                "execution": "maker_only",
            },
            {
                "variant_id": "neutral_grid5_volatility_scaled",
                "entry": "ATR-scaled symmetric levels inside stable range",
                "regime": "range width 5-10 ATR and flat midpoint slope",
                "exit": "inventory-weighted mean exit; hard range invalidation",
                "execution": "maker_only_no_market_chase",
            },
        ],
    },
    "dual_ma_trend_bot:5m": {
        "repair_class": "NEGATIVE_BASE_ARCHITECTURE_REBUILD",
        "family": "trend",
        "diagnosis": "independent 5m MA cross has negative base expectancy",
        "variants": [
            {
                "variant_id": "ma5_as_15m_context_trigger",
                "entry": "15m MA trend context; 5m pullback trigger only",
                "regime": "15m trend slope and breadth alignment",
                "exit": "5m swing invalidation, 15m structure target",
                "execution": "maker_first",
            },
            {
                "variant_id": "ma5_donchian_confluence",
                "entry": "5m MA reclaim only near confirmed 15m Donchian boundary",
                "regime": "trend continuation only",
                "exit": "channel midpoint failure or 3R",
                "execution": "post_only_then_cancel",
            },
        ],
    },
    "dual_vwap_mean_reversion_bot:5m": {
        "repair_class": "NEGATIVE_BASE_ARCHITECTURE_REBUILD",
        "family": "mean_reversion",
        "diagnosis": "shock-heavy 5m standalone VWAP is structurally negative",
        "variants": [
            {
                "variant_id": "vwap5_with_15m_range_context",
                "entry": "15m range context plus 5m 2-sigma excursion reclaim",
                "regime": "range only; shock-recovery veto",
                "exit": "VWAP touch partial and opposite deviation stop",
                "execution": "maker_first",
            },
            {
                "variant_id": "vwap5_failed_auction_reclaim",
                "entry": "failed auction wick plus volume contraction after excursion",
                "regime": "flat 15m anchor and non-trending breadth",
                "exit": "anchor touch or local swing invalidation",
                "execution": "post_only_or_skip",
            },
        ],
    },
    "neutral_multi_level_grid_bot:15m": {
        "repair_class": "NEGATIVE_BASE_ARCHITECTURE_REBUILD",
        "family": "grid_range",
        "diagnosis": "15m standalone cycles are sparse and negative",
        "variants": [
            {
                "variant_id": "grid15_context_5m_execution",
                "entry": "15m range defines inventory bands; 5m executes maker levels",
                "regime": "stable 15m range only",
                "exit": "adjacent-level realized cycles; range break hard stop",
                "execution": "maker_only",
            },
            {
                "variant_id": "grid15_session_range_engine",
                "entry": "session range bands with minimum cost-adjusted spacing",
                "regime": "session range persistence and low directional slope",
                "exit": "session close inventory flatten or range invalidation",
                "execution": "maker_only_inventory_cap_2",
            },
        ],
    },
    "directional_trend_grid_bot:15m": {
        "repair_class": "SIGNAL_STARVED_ROUTE_REBUILD",
        "family": "grid_trend",
        "diagnosis": "only two trades; lane cannot be judged or promoted standalone",
        "variants": [
            {
                "variant_id": "trend_grid15_context_5m_ladder",
                "entry": "15m trend context creates 5m pullback ladder",
                "regime": "Donchian15 breakout plus EMA50 slope",
                "exit": "inventory-capped scale-out into trend continuation",
                "execution": "maker_only_max_two_levels",
            },
            {
                "variant_id": "trend_grid15_breakout_retest_ladder",
                "entry": "15m breakout-retest seeds two maker pullback levels",
                "regime": "trend only; no range/shock first impulse",
                "exit": "breakout boundary failure or 2.5R aggregate target",
                "execution": "maker_only_no_overlap",
            },
        ],
    },
    "directional_trend_grid_bot:5m": {
        "repair_class": "SIGNAL_STARVED_ROUTE_REBUILD",
        "family": "grid_trend",
        "diagnosis": "one trade; standalone 5m route is invalid",
        "variants": [
            {
                "variant_id": "trend_grid5_donchian15_context",
                "entry": "5m pullback ladder only after Donchian15 direction lock",
                "regime": "15m trend context mandatory",
                "exit": "5m swing failure or aggregate 2.5R",
                "execution": "maker_only_inventory_cap_2",
            },
            {
                "variant_id": "trend_grid5_impulse_retest",
                "entry": "5m impulse then controlled retest with 15m slope confirmation",
                "regime": "trend continuation; range and shock-recovery veto",
                "exit": "first failed reclaim closes all inventory",
                "execution": "post_only_then_cancel",
            },
        ],
    },
}

def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)

def finite(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return default

def lane_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    base = row.get("base_metrics") or {}
    adverse = row.get("adverse_metrics") or {}
    severe = row.get("severe_tail_metrics") or {}
    return {
        "lane_id": str(row.get("lane_id")),
        "benchmark_v2_economic_pass": bool(row.get("benchmark_v2_economic_pass")),
        "signal_count_after_admission": int(row.get("signal_count_after_admission") or 0),
        "positive_primary_cell_count": int(row.get("positive_primary_cell_count") or 0),
        "base": {
            "trade_count": int(base.get("trade_count") or 0),
            "profit_factor": finite(base.get("profit_factor")),
            "expectancy_r": finite(base.get("expectancy_r")),
            "net_pnl_sum_pct": finite(base.get("net_pnl_sum_pct")),
            "max_drawdown_pct": finite(base.get("max_drawdown_pct")),
            "positive_fold_count": int((base.get("fold_metrics") or {}).get("positive_fold_count") or 0),
        },
        "adverse": {
            "trade_count": int(adverse.get("trade_count") or 0),
            "profit_factor": finite(adverse.get("profit_factor")),
            "expectancy_r": finite(adverse.get("expectancy_r")),
            "net_pnl_sum_pct": finite(adverse.get("net_pnl_sum_pct")),
            "max_drawdown_pct": finite(adverse.get("max_drawdown_pct")),
            "positive_fold_count": int((adverse.get("fold_metrics") or {}).get("positive_fold_count") or 0),
        },
        "severe": {
            "trade_count": int(severe.get("trade_count") or 0),
            "profit_factor": finite(severe.get("profit_factor")),
            "expectancy_r": finite(severe.get("expectancy_r")),
            "net_pnl_sum_pct": finite(severe.get("net_pnl_sum_pct")),
            "max_drawdown_pct": finite(severe.get("max_drawdown_pct")),
            "positive_fold_count": int((severe.get("fold_metrics") or {}).get("positive_fold_count") or 0),
        },
    }

def self_test() -> int:
    assert len(LANE_REPAIR_CONTRACTS) == EXPECTED_FAILED_LANE_COUNT
    variants = [
        variant
        for contract in LANE_REPAIR_CONTRACTS.values()
        for variant in contract["variants"]
    ]
    assert len(variants) == EXPECTED_REPAIR_BUNDLE_COUNT
    assert len({row["variant_id"] for row in variants}) == EXPECTED_REPAIR_BUNDLE_COUNT
    assert all(len(contract["variants"]) == EXPECTED_REPAIR_VARIANTS_PER_LANE
               for contract in LANE_REPAIR_CONTRACTS.values())
    assert not any([
        STRATEGY_MUTATION_ALLOWED,
        REGISTRY_MUTATION_ALLOWED,
        CONFIG_MUTATION_ALLOWED,
        ROUTER_MUTATION_ALLOWED,
        SERVICE_MUTATION_ALLOWED,
        SHADOW_START_ALLOWED,
        PAPER_LIVE_ORDER_ALLOWED,
        PARAMETER_OPTIMIZATION_ALLOWED,
        BLIND_STOP_WIDENING_ALLOWED,
        ENTRY_THRESHOLD_RELAXATION_ALLOWED,
        DISCOVERY_S_GRADE_LABEL_ALLOWED,
    ])
    print("STATE=PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN_SELF_TEST")
    print("RC=0")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", default="UNKNOWN")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    summary_path = root / SUMMARY_PATH
    if not summary_path.is_file():
        print("STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps([f"REQUIRED_SUMMARY_MISSING:{summary_path}"]))
        print("RC=2")
        return 2

    summary = load_json(summary_path)
    lanes = [row for row in summary.get("lane_rows", []) if isinstance(row, dict)]
    blockers: list[str] = []
    if summary.get("state") != "PASS_SHORT_EXCHANGE_BOT_BENCHMARK_V2_EXECUTION_72":
        blockers.append("BENCHMARK_V2_SUMMARY_NOT_PASS")
    if len(lanes) != EXPECTED_LANE_COUNT:
        blockers.append(f"LANE_COUNT_INVALID:{len(lanes)}")

    pass_rows = [row for row in lanes if bool(row.get("benchmark_v2_economic_pass"))]
    fail_rows = [row for row in lanes if not bool(row.get("benchmark_v2_economic_pass"))]
    if len(pass_rows) != EXPECTED_PASS_LANE_COUNT:
        blockers.append(f"PASS_LANE_COUNT_INVALID:{len(pass_rows)}")
    if len(fail_rows) != EXPECTED_FAILED_LANE_COUNT:
        blockers.append(f"FAILED_LANE_COUNT_INVALID:{len(fail_rows)}")
    pass_ids = {str(row.get("lane_id")) for row in pass_rows}
    if pass_ids != {REFERENCE_LANE_ID}:
        blockers.append("REFERENCE_PASS_LANE_INVALID")
    fail_ids = {str(row.get("lane_id")) for row in fail_rows}
    if fail_ids != set(LANE_REPAIR_CONTRACTS):
        blockers.append("FAILED_LANE_SET_INVALID")

    if blockers:
        print("STATE=HOLD_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN_INPUT")
        print("BLOCKER_COUNT=" + str(len(blockers)))
        print("BLOCKERS=" + json.dumps(blockers))
        print("RC=2")
        return 2

    rows_by_id = {str(row["lane_id"]): row for row in lanes}
    uplift_rows: list[dict[str, Any]] = []
    class_histogram: Counter[str] = Counter()
    family_histogram: Counter[str] = Counter()
    for lane_id, contract in sorted(LANE_REPAIR_CONTRACTS.items()):
        class_histogram[str(contract["repair_class"])] += 1
        family_histogram[str(contract["family"])] += 1
        baseline = lane_snapshot(rows_by_id[lane_id])
        for variant in contract["variants"]:
            uplift_rows.append({
                "lane_id": lane_id,
                "repair_class": contract["repair_class"],
                "family": contract["family"],
                "diagnosis": contract["diagnosis"],
                "variant_id": variant["variant_id"],
                "entry_contract": variant["entry"],
                "regime_contract": variant["regime"],
                "exit_contract": variant["exit"],
                "execution_contract": variant["execution"],
                "baseline_metrics": baseline,
                "causal_constraints": {
                    "blind_stop_widening_allowed": False,
                    "entry_threshold_relaxation_allowed": False,
                    "parameter_optimization_allowed": False,
                    "negative_baseline_relative_promotion_allowed": False,
                    "reference_lane_to_beat": REFERENCE_LANE_ID,
                },
            })

    plan = {
        "state": "PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN",
        "target_sha": args.target_sha,
        "reference_pass_lane_id": REFERENCE_LANE_ID,
        "reference_metrics": lane_snapshot(rows_by_id[REFERENCE_LANE_ID]),
        "failed_lane_count": len(fail_rows),
        "repair_bundle_count": len(uplift_rows),
        "stress_cell_per_bundle": EXPECTED_STRESS_PER_BUNDLE,
        "discovery_cell_target": len(uplift_rows) * EXPECTED_STRESS_PER_BUNDLE,
        "repair_class_histogram": dict(sorted(class_histogram.items())),
        "family_histogram": dict(sorted(family_histogram.items())),
        "uplift_rows": uplift_rows,
        "validation_policy": {
            "discovery_s_grade_label_allowed": False,
            "base_and_adverse_positive_required": True,
            "minimum_trade_count": 24,
            "minimum_symbol_count": 3,
            "minimum_positive_walk_forward_folds": 4,
            "minimum_positive_primary_cells": 3,
            "must_beat_reference_on_risk_adjusted_score": True,
            "severe_profile_role": "TAIL_ROBUSTNESS_ONLY",
            "disjoint_validation_required_after_discovery": True,
            "multiple_testing_penalty_required": True,
        },
        "mutation_policy": {
            "strategy_mutation_allowed": False,
            "registry_mutation_allowed": False,
            "config_mutation_allowed": False,
            "router_mutation_allowed": False,
            "service_mutation_allowed": False,
            "shadow_start_allowed": False,
            "paper_live_order_allowed": False,
        },
        "next_stage": "R7.A4D2_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132",
    }

    output_path = root / OUTPUT_DIR / "remaining_11_lane_uplift_plan_v1.json"
    atomic_json(output_path, plan)

    print("STATE=PASS_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_PLAN")
    print("BLOCKER_COUNT=0")
    print("REFERENCE_PASS_LANE_ID=" + REFERENCE_LANE_ID)
    print("FAILED_LANE_COUNT=" + str(len(fail_rows)))
    print("REPAIR_BUNDLE_COUNT=" + str(len(uplift_rows)))
    print("DISCOVERY_CELL_TARGET=" + str(len(uplift_rows) * EXPECTED_STRESS_PER_BUNDLE))
    print("REPAIR_CLASS_HISTOGRAM=" + json.dumps(dict(sorted(class_histogram.items())), sort_keys=True))
    print("FAMILY_HISTOGRAM=" + json.dumps(dict(sorted(family_histogram.items())), sort_keys=True))
    print("UPLIFT_PLAN_JSON=" + str(output_path))
    print("NEXT_STAGE=R7.A4D2_EXCHANGE_BOT_V2_REMAINING_11_LANE_UPLIFT_EXECUTION_132")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
