#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CONTRACT = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1/SCALP_INTRADAY_CONTRACT.json"
BENCHMARK = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1/BENCHMARK_DOSSIER.json"
DEFAULT_OUT = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1/ROUND0_RESULT.json"
SCHEMA = "zel.g4_scalp_intraday_rebase.round0_result.v1"

POLICY_GROUPS: dict[str, dict[str, Any]] = {
    "turtle": {
        "module": "backend.research.rebuild.turtle_trend_policy_v2",
        "config": "TurtleTrendPolicyConfig",
        "strategies": ["turtle_trend"],
    },
    "vwap_bb": {
        "module": "backend.research.rebuild.vwap_bb_policy_batch_v1",
        "config": "CommonPolicyConfig",
        "strategies": ["bb_revert", "anchor_vwap_trend", "vwap_revert"],
    },
    "breakout": {
        "module": "backend.research.rebuild.breakout_policy_batch_v1",
        "config": "BreakoutPolicyConfig",
        "strategies": ["break_and_continue", "keltner_trend", "squeeze_break"],
    },
    "trend": {
        "module": "backend.research.rebuild.trend_policy_batch_v1",
        "config": "TrendPolicyConfig",
        "strategies": ["supertrend_pullback", "trend_ma_macd", "trend_rider"],
    },
    "microstructure": {
        "module": "backend.research.rebuild.microstructure_policy_batch_v1",
        "config": "MicroPolicyConfig",
        "strategies": ["liquidity_sweep", "scalp_snap", "vol_spike_fade"],
    },
    "reversal_range": {
        "module": "backend.research.rebuild.reversal_range_policy_batch_v1",
        "config": "ReversalRangeConfig",
        "strategies": ["range_fade", "fvg_revert", "pivot_reversal", "rsi_swing_fail"],
    },
    "indicator_core": {
        "module": "backend.research.rebuild.indicator_core_policy_batch_v1",
        "config": "IndicatorCoreConfig",
        "strategies": ["alpha_combo", "ema_ribbon_scalp", "mfi_rsi_div", "obv_trend"],
    },
    "final_four": {
        "module": "backend.research.rebuild.final_four_policy_batch_v1",
        "config": "FinalFourConfig",
        "strategies": ["grid_rebalance", "rbreaker_like", "session_bias", "sr_levels"],
    },
}

EXPECTED_SCALP_NATIVE = {
    "liquidity_sweep", "scalp_snap", "vol_spike_fade",
    "range_fade", "fvg_revert", "pivot_reversal", "rsi_swing_fail",
    "alpha_combo", "ema_ribbon_scalp", "mfi_rsi_div", "obv_trend",
    "grid_rebalance", "rbreaker_like", "session_bias", "sr_levels",
}
EXPECTED_FAST_CHILD = {
    "bb_revert", "anchor_vwap_trend", "vwap_revert",
    "break_and_continue", "keltner_trend", "squeeze_break",
    "supertrend_pullback", "trend_ma_macd", "trend_rider",
}
EXPECTED_DONOR_ONLY = {"turtle_trend"}

FAST_CHILD_TARGETS: dict[str, dict[str, Any]] = {
    "bb_revert": {"target_timeframes": ["5m", "15m"], "benchmark_focus": "regime-gated band reentry"},
    "anchor_vwap_trend": {"target_timeframes": ["5m", "15m"], "benchmark_focus": "AVWAP reaction/reclaim confirmation"},
    "vwap_revert": {"target_timeframes": ["5m"], "benchmark_focus": "VWAP displacement/reclaim plus Level2/flow"},
    "break_and_continue": {"target_timeframes": ["5m", "15m"], "benchmark_focus": "compression-break-pullback-continuation"},
    "keltner_trend": {"target_timeframes": ["15m"], "benchmark_focus": "volatility expansion plus trend structure"},
    "squeeze_break": {"target_timeframes": ["5m", "15m"], "benchmark_focus": "BB/KC compression release plus momentum"},
    "supertrend_pullback": {"target_timeframes": ["15m"], "benchmark_focus": "trend-first pullback/reclaim"},
    "trend_ma_macd": {"target_timeframes": ["15m"], "benchmark_focus": "trend state then momentum reacceleration"},
    "trend_rider": {"target_timeframes": ["15m"], "benchmark_focus": "trend persistence with faster lifecycle"},
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy_rows() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for group_name, spec in POLICY_GROUPS.items():
        module = importlib.import_module(str(spec["module"]))
        cls = getattr(module, str(spec["config"]))
        cfg = cls()
        timeframe_ms = int(getattr(cfg, "timeframe_ms"))
        timeout_bars = int(getattr(cfg, "timeout_bars"))
        module_path = Path(module.__file__).resolve()
        for sid in spec["strategies"]:
            rows[str(sid)] = {
                "policy_group": group_name,
                "policy_module": str(spec["module"]),
                "policy_path": str(module_path.relative_to(ROOT)),
                "policy_sha256": sha256_file(module_path),
                "config_class": str(spec["config"]),
                "timeframe_ms": timeframe_ms,
                "timeout_bars": timeout_bars,
                "hard_timeout_minutes": timeframe_ms * timeout_bars / 60000.0,
            }
    return rows


def classify(sid: str, row: dict[str, Any], contract: dict[str, Any]) -> str:
    r0 = contract["round0"]
    tf = int(row["timeframe_ms"])
    hold = float(row["hard_timeout_minutes"])
    scalp = r0["scalp"]
    day = r0["daytrade"]
    if tf <= int(scalp["decision_timeframe_ms_max"]) and hold <= float(scalp["hard_timeout_minutes_max"]):
        return "SCALP_NATIVE_ROUND1_ELIGIBLE"
    if tf <= int(day["decision_timeframe_ms_max"]) and hold <= float(day["hard_timeout_minutes_max"]):
        return "DAYTRADE_NATIVE_ROUND1_ELIGIBLE"
    if sid in EXPECTED_DONOR_ONLY:
        return "DONOR_ONLY_CURRENT"
    return "FAST_CHILD_REQUIRED_BEFORE_ROUND1"


def build_result() -> dict[str, Any]:
    inventory = read_json(INVENTORY)
    contract = read_json(CONTRACT)
    benchmark = read_json(BENCHMARK)
    inv_ids = set(inventory.get("strategies", {}).keys())
    bench_ids = set(benchmark.get("strategies", {}).keys())
    rows = policy_rows()
    policy_ids = set(rows.keys())
    if len(inv_ids) != 25:
        raise RuntimeError(f"EXACT25_COUNT_DRIFT:{len(inv_ids)}")
    if inv_ids != bench_ids:
        raise RuntimeError(f"BENCHMARK_IDENTITY_DRIFT:missing={sorted(inv_ids-bench_ids)}:extra={sorted(bench_ids-inv_ids)}")
    if inv_ids != policy_ids:
        raise RuntimeError(f"POLICY_IDENTITY_DRIFT:missing={sorted(inv_ids-policy_ids)}:extra={sorted(policy_ids-inv_ids)}")
    if benchmark.get("authority", {}).get("benchmark_selection_authority") is not False:
        raise RuntimeError("BENCHMARK_AUTHORITY_MUST_BE_FALSE")

    strategies: dict[str, Any] = {}
    buckets: dict[str, list[str]] = {
        "SCALP_NATIVE_ROUND1_ELIGIBLE": [],
        "DAYTRADE_NATIVE_ROUND1_ELIGIBLE": [],
        "FAST_CHILD_REQUIRED_BEFORE_ROUND1": [],
        "DONOR_ONLY_CURRENT": [],
    }
    for sid in sorted(inv_ids):
        row = dict(rows[sid])
        cls = classify(sid, row, contract)
        buckets[cls].append(sid)
        bench = benchmark["strategies"][sid]
        row.update({
            "classification": cls,
            "benchmark_ids": list(bench.get("benchmark_ids", [])),
            "benchmark_strength": bench.get("benchmark_strength"),
            "lane_hint": bench.get("lane_hint"),
            "round0_economics_used": false,
            "old_pnl_used_for_classification": false,
        })
        if sid in FAST_CHILD_TARGETS:
            row["fast_child_authorization"] = FAST_CHILD_TARGETS[sid]
        strategies[sid] = row

    scalp = set(buckets["SCALP_NATIVE_ROUND1_ELIGIBLE"])
    fast = set(buckets["FAST_CHILD_REQUIRED_BEFORE_ROUND1"])
    donor = set(buckets["DONOR_ONLY_CURRENT"])
    if scalp != EXPECTED_SCALP_NATIVE:
        raise RuntimeError(f"SCALP_CENSUS_DRIFT:{sorted(scalp ^ EXPECTED_SCALP_NATIVE)}")
    if fast != EXPECTED_FAST_CHILD:
        raise RuntimeError(f"FAST_CHILD_CENSUS_DRIFT:{sorted(fast ^ EXPECTED_FAST_CHILD)}")
    if donor != EXPECTED_DONOR_ONLY:
        raise RuntimeError(f"DONOR_CENSUS_DRIFT:{sorted(donor ^ EXPECTED_DONOR_ONLY)}")
    if buckets["DAYTRADE_NATIVE_ROUND1_ELIGIBLE"]:
        raise RuntimeError("UNEXPECTED_CURRENT_DAYTRADE_NATIVE")

    return {
        "schema_version": SCHEMA,
        "scope_key": contract["scope_key"],
        "issue": contract["issue"],
        "state": "ROUND0_COMPLETE_OPERABILITY_REBASE_READY_FOR_NATIVE_ROUND1_AND_FAST_CHILD_BUILD",
        "source_identity": {
            "inventory_path": str(INVENTORY.relative_to(ROOT)),
            "inventory_sha256": sha256_file(INVENTORY),
            "contract_path": str(CONTRACT.relative_to(ROOT)),
            "contract_sha256": sha256_file(CONTRACT),
            "benchmark_path": str(BENCHMARK.relative_to(ROOT)),
            "benchmark_sha256": sha256_file(BENCHMARK),
        },
        "counts": {
            "exact25": len(inv_ids),
            "scalp_native_round1_eligible": len(buckets["SCALP_NATIVE_ROUND1_ELIGIBLE"]),
            "daytrade_native_round1_eligible": len(buckets["DAYTRADE_NATIVE_ROUND1_ELIGIBLE"]),
            "fast_child_required_before_round1": len(buckets["FAST_CHILD_REQUIRED_BEFORE_ROUND1"]),
            "donor_only_current": len(buckets["DONOR_ONLY_CURRENT"]),
        },
        "buckets": buckets,
        "strategies": strategies,
        "next": {
            "native_round1": "Run common-window economics on the 15 native scalp policies without benchmark mutation first.",
            "fast_child": "Build predeclared benchmark children for the 9 slow current policies, then enter Round1 only after each child passes structural parity and operability.",
            "donor": "Keep turtle_trend as risk/payoff donor and negative/control reference; no direct Round1 current-policy candidacy.",
            "economic_priority": contract["round1_economic_priority"],
            "portfolio_closed_T_per_day_min": contract["selection_rules"]["portfolio_target_closed_T_per_day_min"],
        },
        "authority": contract["authority"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    result = build_result()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "counts": result["counts"], "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
