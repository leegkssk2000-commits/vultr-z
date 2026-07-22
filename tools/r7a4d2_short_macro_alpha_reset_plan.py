#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
MANIFEST = Path("runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json")
DISCOVERY = Path("runtime/r7a4d2_short_native_family_architecture_discovery_execution_132/architecture_discovery_lock_v1.json")
VALIDATION = Path("runtime/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan/strict_validation_and_rescue_plan_v1.json")
OUTPUT = Path("runtime/r7a4d2_short_macro_alpha_reset_plan/macro_alpha_reset_plan_v1.json")

RESET_STRATEGIES = {
    "anchor_vwap_trend",
    "bb_revert",
    "ema_ribbon_scalp",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "obv_trend",
    "range_fade",
    "scalp_snap",
    "vol_spike_fade",
    "vwap_revert",
}

FACTOR_ENGINES = [
    {
        "engine_id": "regime_trend_engine",
        "source_strategy_ids": ["keltner_trend", "obv_trend", "anchor_vwap_trend"],
        "economic_hypothesis": "short continuation only after higher-timeframe down-regime confirmation and failed pullback/retest",
        "required_inputs": ["ohlcv_5m", "ohlcv_15m", "volume"],
        "status": "RESET_REQUIRED",
    },
    {
        "engine_id": "range_mean_reversion_engine",
        "source_strategy_ids": ["vwap_revert", "bb_revert", "range_fade", "grid_rebalance"],
        "economic_hypothesis": "single-cycle short mean reversion only inside statistically stable ranges with cost-adjusted excursion",
        "required_inputs": ["ohlcv_5m", "ohlcv_15m", "volume"],
        "status": "RESET_REQUIRED",
    },
    {
        "engine_id": "event_reversal_engine",
        "source_strategy_ids": ["liquidity_sweep", "vol_spike_fade"],
        "economic_hypothesis": "short reversal only after displacement, rejection and failed continuation are all observed",
        "required_inputs": ["ohlcv_1m", "ohlcv_5m", "volume"],
        "status": "RESET_REQUIRED",
    },
    {
        "engine_id": "microstructure_scalp_engine",
        "source_strategy_ids": ["scalp_snap", "ema_ribbon_scalp"],
        "economic_hypothesis": "short scalp only when order-flow or liquidation microstructure confirms a higher-timeframe setup",
        "required_inputs": ["ohlcv_1m", "ohlcv_5m", "trade_flow", "order_book_imbalance", "liquidation_flow"],
        "status": "DATA_GATED",
    },
]

BENCHMARKS = [
    {
        "benchmark_id": "benchmark_ma_cross_short",
        "family": "trend",
        "timeframes": ["5m", "15m"],
        "entry": "fast EMA below slow EMA with close confirmation",
        "exit": "opposite cross or ATR stop/target",
    },
    {
        "benchmark_id": "benchmark_donchian_breakout_short",
        "family": "trend",
        "timeframes": ["5m", "15m"],
        "entry": "close below prior Donchian low",
        "exit": "mid-channel reclaim or ATR stop/target",
    },
    {
        "benchmark_id": "benchmark_atr_volatility_breakout_short",
        "family": "breakout",
        "timeframes": ["5m", "15m"],
        "entry": "downside range expansion beyond ATR threshold with volume confirmation",
        "exit": "ATR trailing stop or fixed structural target",
    },
    {
        "benchmark_id": "benchmark_vwap_mean_reversion_short",
        "family": "mean_reversion",
        "timeframes": ["5m", "15m"],
        "entry": "cost-adjusted upper VWAP excursion followed by close-back-inside",
        "exit": "VWAP/basis target or time stop",
    },
    {
        "benchmark_id": "benchmark_single_cycle_grid_short",
        "family": "grid_range",
        "timeframes": ["5m", "15m"],
        "entry": "one short at confirmed range upper quartile",
        "exit": "range midpoint; no inventory stacking",
    },
]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def self_test() -> int:
    assert len(RESET_STRATEGIES) == 11
    mapped = [strategy_id for engine in FACTOR_ENGINES for strategy_id in engine["source_strategy_ids"]]
    assert len(mapped) == 11
    assert set(mapped) == RESET_STRATEGIES
    assert len(mapped) == len(set(mapped))
    assert len(FACTOR_ENGINES) == 4
    assert len(BENCHMARKS) == 5
    assert sum(len(row["timeframes"]) for row in BENCHMARKS) == 10
    print("STATE=PASS_SHORT_MACRO_ALPHA_RESET_PLAN_SELF_TEST")
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
    required = [root / REGISTRY, root / MANIFEST, root / DISCOVERY, root / VALIDATION]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = {str(path): sha256_file(path) for path in required}
    registry = load_json(root / REGISTRY)
    manifest = load_json(root / MANIFEST)
    discovery = load_json(root / DISCOVERY)
    validation = load_json(root / VALIDATION)
    blockers: list[str] = []

    registry_entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    registry_ids = {str(row.get("strategy_id") or "") for row in registry_entries}
    if int(registry.get("strategy_count") or -1) != 25 or len(registry_ids) != 25:
        blockers.append(f"CANONICAL_STRATEGY_COUNT_INVALID:{len(registry_ids)}")
    if not RESET_STRATEGIES.issubset(registry_ids):
        blockers.append("RESET_STRATEGY_SET_NOT_IN_REGISTRY")
    kept_ids = sorted(registry_ids - RESET_STRATEGIES)
    if len(kept_ids) != 14:
        blockers.append(f"KEPT_STRATEGY_COUNT_INVALID:{len(kept_ids)}")
    if int(registry.get("active_entry_count") or 0) != 0:
        blockers.append("CANONICAL_REGISTRY_ACTIVE_ENTRY_NONZERO")

    if discovery.get("state") != "PASS_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132":
        blockers.append("DISCOVERY_EVIDENCE_NOT_PASS")
    if int(discovery.get("strategy_count") or -1) != 11:
        blockers.append("DISCOVERY_STRATEGY_COUNT_INVALID")
    if int(discovery.get("strict_s_grade_survivor_count") or 0) < 1:
        blockers.append("DISCOVERY_STRICT_CANDIDATE_MISSING")

    if validation.get("state") != "PASS_SHORT_NATIVE_ARCHITECTURE_DISJOINT_VALIDATION_AND_NEAR_MISS_RESCUE_PLAN":
        blockers.append("VALIDATION_EVIDENCE_NOT_PASS")
    if int(validation.get("validated_strict_survivor_count") or -1) != 0:
        blockers.append("ZERO_VALIDATED_SURVIVOR_PRECONDITION_INVALID")

    segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    fold_histogram = Counter(str(row.get("fold")) for row in segments)
    symbol_histogram = Counter(str(row.get("symbol") or "UNKNOWN") for row in segments)
    regime_histogram = Counter(str(row.get("regime") or "UNKNOWN") for row in segments)
    measurement_rows = sum(max(0, int(row.get("end_row_exclusive") or 0) - int(row.get("start_row") or 0)) for row in segments)
    fold_count = len(fold_histogram)
    source_path_count = len({str(row.get("source_path") or "") for row in segments})

    after = {str(path): sha256_file(path) for path in required}
    mutations = sorted(path for path in before if before[path] != after[path])
    if mutations:
        blockers.append("INPUT_MUTATION_DETECTED:" + json.dumps(mutations))

    benchmark_lane_count = sum(len(row["timeframes"]) for row in BENCHMARKS)
    stress_cell_per_lane = 6
    benchmark_cell_target = benchmark_lane_count * stress_cell_per_lane

    gate = {
        "discovery_label_policy": "NO_S_GRADE_LABEL_IN_DISCOVERY",
        "provisional_oos_gate": {
            "held_out_trade_count_min": 20,
            "severe_profit_factor_gt": 1.0,
            "severe_expectancy_r_gt": 0.0,
            "severe_net_pnl_pct_gt": 0.0,
            "positive_stress_cells_min": 4,
            "must_beat_best_matching_benchmark": True,
        },
        "s_grade_gate": {
            "pooled_oos_trade_count_min": 50,
            "minimum_symbol_count": 3,
            "maximum_single_symbol_pnl_share_pct": 50.0,
            "deflated_sharpe_probability_min": 0.95,
            "probability_of_backtest_overfitting_max": 0.10,
            "held_out_profit_factor_gt": 1.10,
            "held_out_expectancy_r_gt": 0.10,
            "drawdown_not_worse_than_best_matching_benchmark": True,
            "positive_held_out_fold_ratio_min": 0.60,
        },
    }

    state = "PASS_SHORT_MACRO_ALPHA_RESET_PLAN" if not blockers else "HOLD_SHORT_MACRO_ALPHA_RESET_PLAN"
    plan = {
        "schema": "r7a4d2_short_macro_alpha_reset_plan_v1",
        "official_stage": "R7.A4D2_SHORT_MACRO_ALPHA_RESET",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "canonical_strategy_count": len(registry_ids),
        "kept_strategy_count": len(kept_ids),
        "kept_strategy_ids": kept_ids,
        "kept_strategy_policy": "IMMUTABLE_EVIDENCE_PRESERVATION_NO_REEXECUTION_IN_RESET_STAGE",
        "reset_strategy_count": len(RESET_STRATEGIES),
        "reset_strategy_ids": sorted(RESET_STRATEGIES),
        "s_grade_label_revoked_count": len(RESET_STRATEGIES),
        "validated_s_grade_strategy_count": 0,
        "factor_engine_count": len(FACTOR_ENGINES),
        "factor_engines": FACTOR_ENGINES,
        "benchmark_count": len(BENCHMARKS),
        "benchmark_lane_count": benchmark_lane_count,
        "benchmark_cell_target": benchmark_cell_target,
        "benchmarks": BENCHMARKS,
        "benchmark_policy": "SAME_FROZEN_MARKET_DATA_SAME_COSTS_SAME_TIMING_PERTURBATIONS_BEFORE_ALPHA_ENGINE_REBUILD",
        "current_data_coverage": {
            "selected_segment_count": len(segments),
            "fold_count": fold_count,
            "fold_histogram": dict(sorted(fold_histogram.items())),
            "source_path_count": source_path_count,
            "symbol_histogram": dict(sorted(symbol_histogram.items())),
            "regime_histogram": dict(sorted(regime_histogram.items())),
            "measurement_1m_row_count": measurement_rows,
            "measurement_hours": round(measurement_rows / 60.0, 6),
        },
        "data_coverage_audit_required": True,
        "external_feature_availability_audit": {
            "funding": "REQUIRED_FOR_AUDIT_NOT_ASSUMED_AVAILABLE",
            "open_interest": "REQUIRED_FOR_AUDIT_NOT_ASSUMED_AVAILABLE",
            "basis": "REQUIRED_FOR_AUDIT_NOT_ASSUMED_AVAILABLE",
            "trade_flow": "REQUIRED_FOR_MICROSTRUCTURE_ENGINE",
            "order_book_imbalance": "REQUIRED_FOR_MICROSTRUCTURE_ENGINE",
            "liquidation_flow": "REQUIRED_FOR_MICROSTRUCTURE_ENGINE",
            "btc_lead_lag": "OPTIONAL_ENGINE_FEATURE_REQUIRES_LINEAGE",
            "session_time": "DERIVABLE_FROM_TIMESTAMP_AFTER_TIMEZONE_AUDIT",
        },
        "promotion_gate": gate,
        "walk_forward_policy": {
            "chronological_only": True,
            "purge_required": True,
            "embargo_required": True,
            "same_fold_selection_and_validation_allowed": False,
            "multiple_testing_correction_required": True,
            "pbo_required": True,
            "deflated_sharpe_required": True,
        },
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "input_sha256": {str(path.relative_to(root)): sha256_file(path) for path in required},
        "input_mutation_paths": mutations,
        "next_stage": "R7.A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT",
    }
    atomic_json(root / OUTPUT, plan)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("CANONICAL_STRATEGY_COUNT=" + str(len(registry_ids)))
    print("KEPT_STRATEGY_COUNT=" + str(len(kept_ids)))
    print("KEPT_STRATEGY_IDS=" + json.dumps(kept_ids))
    print("RESET_STRATEGY_COUNT=" + str(len(RESET_STRATEGIES)))
    print("RESET_STRATEGY_IDS=" + json.dumps(sorted(RESET_STRATEGIES)))
    print("S_GRADE_LABEL_REVOKED_COUNT=" + str(len(RESET_STRATEGIES)))
    print("VALIDATED_S_GRADE_STRATEGY_COUNT=0")
    print("FACTOR_ENGINE_COUNT=" + str(len(FACTOR_ENGINES)))
    print("FACTOR_ENGINE_IDS=" + json.dumps([row["engine_id"] for row in FACTOR_ENGINES]))
    print("BENCHMARK_COUNT=" + str(len(BENCHMARKS)))
    print("BENCHMARK_LANE_COUNT=" + str(benchmark_lane_count))
    print("BENCHMARK_CELL_TARGET=" + str(benchmark_cell_target))
    print("CURRENT_SELECTED_SEGMENT_COUNT=" + str(len(segments)))
    print("CURRENT_FOLD_COUNT=" + str(fold_count))
    print("CURRENT_MEASUREMENT_1M_ROWS=" + str(measurement_rows))
    print("CURRENT_MEASUREMENT_HOURS=" + str(round(measurement_rows / 60.0, 6)))
    print("MICROSTRUCTURE_ENGINE_DATA_GATED=true")
    print("PLAN_JSON=" + str(root / OUTPUT))
    print("NEXT_STAGE=R7.A4D2_SHORT_SIMPLE_BENCHMARK_BASELINE_EXECUTION_60_AND_DATA_COVERAGE_AUDIT")
    print("BLOCKERS=" + json.dumps(blockers))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
