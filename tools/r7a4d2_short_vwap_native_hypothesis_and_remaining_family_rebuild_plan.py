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

REPORT = Path("runtime/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit/economic_execution_and_uplift_audit_v1.json")
CAUSAL = Path("runtime/r7a4d2_short_second_order_repair_causal_audit/causal_audit_v1.json")
VERIFIED_PLAN = Path("runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_effective_execution_plan_v3.json")
VWAP_PLAN = Path("runtime/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild/repair_plan_v1.json")
OUTPUT = Path("runtime/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan/rebuild_plan_v1.json")

EXPECTED_STRATEGIES = 11
EXPECTED_BUNDLES = 22
EXPECTED_STRESS_PER_BUNDLE = 6
EXPECTED_DISCOVERY_CELLS = 132


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


def bundle(bundle_id: str, context_tf: str, setup_tf: str, trigger_tf: str, entry: str, regimes: list[str], exit_rule: str, stop_rule: str, vetoes: list[str], role: str = "standalone_candidate") -> dict[str, Any]:
    return {
        "bundle_id": bundle_id,
        "context_timeframe": context_tf,
        "setup_timeframe": setup_tf,
        "trigger_timeframe": trigger_tf,
        "entry_contract": entry,
        "allowed_regimes": regimes,
        "exit_contract": exit_rule,
        "stop_contract": stop_rule,
        "vetoes": vetoes,
        "role": role,
        "single_position_only": True,
        "stop_first_collision": True,
        "future_selection_allowed": False,
    }


def specifications() -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": "vol_spike_fade", "family": "event_reversal", "batch": 1,
            "current_failure": "COST_FRICTION_SENSITIVITY",
            "forbidden_legacy": ["standalone_1m_high_turnover", "duplicate_entries_inside_same_spike"],
            "bundles": [
                bundle("vol_spike_fade:15m_context_5m_exhaustion", "15m", "5m", "5m", "unique volume shock then failed continuation and bearish close back inside event range", ["shock_recovery", "range"], "partial30 at event midpoint then runner to pre-spike VWAP; event timeout", "above event extreme plus structural buffer", ["same-event reentry", "trend-up continuation", "insufficient gross excursion versus cost"]),
                bundle("vol_spike_fade:5m_climax_reclaim", "5m", "5m", "5m", "climax volume plus upper-wick rejection plus next-bar reclaim failure", ["shock_recovery"], "single full exit at VWAP or timeout; no churn", "above climax high", ["cooldown violation", "second entry before new event id"]),
            ],
        },
        {
            "strategy_id": "keltner_trend", "family": "trend", "batch": 1,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["late_channel_chase", "shared_obv_signal_path"],
            "bundles": [
                bundle("keltner_trend:15m_slope_5m_pullback", "15m", "5m", "5m", "15m channel slope down and 5m pullback to mid or upper channel followed by bearish rejection", ["trend_down"], "partial30 at prior low then runner on lower channel", "above pullback swing high", ["flat channel", "trend-up", "entry after extended lower-channel break"]),
                bundle("keltner_trend:breakdown_retest", "15m", "5m", "5m", "confirmed lower-channel breakdown then first failed retest from below", ["trend_down", "shock_recovery"], "target next structural low with timeout if channel slope flattens", "above retest high", ["second-or-later retest", "range compression"]),
            ],
        },
        {
            "strategy_id": "obv_trend", "family": "trend", "batch": 1,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["keltner_callable_alias", "price-only trigger"],
            "bundles": [
                bundle("obv_trend:15m_distribution_5m_break", "15m", "5m", "5m", "15m OBV lower high while price retests resistance, followed by 5m structure break", ["trend_down", "range"], "partial30 at local low then runner while OBV remains below signal line", "above divergence swing high", ["OBV confirmation absent", "volume feed discontinuity"]),
                bundle("obv_trend:volume_impulse_retest", "15m", "5m", "5m", "negative OBV impulse and first price retest with weak positive volume", ["trend_down"], "exit on OBV reversal or structural target", "above retest swing", ["positive OBV divergence", "late chase"]),
            ],
        },
        {
            "strategy_id": "anchor_vwap_trend", "family": "trend", "batch": 1,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["unanchored_vwap_reuse", "post-breakdown_chase"],
            "bundles": [
                bundle("anchor_vwap_trend:session_anchor_retest", "15m", "5m", "5m", "price below session or impulse anchor VWAP and first 5m retest rejects below anchor", ["trend_down"], "partial30 at prior low then trail below falling anchor VWAP", "above anchor retest high", ["anchor slope non-negative", "price already overextended"]),
                bundle("anchor_vwap_trend:event_anchor_confluence", "15m", "5m", "5m", "event anchor VWAP aligns with prior resistance and bearish reclaim fails", ["trend_down", "shock_recovery"], "exit at next liquidity low or anchor slope reversal", "above confluence high", ["anchor ambiguity", "multiple anchors without hierarchy"]),
            ],
        },
        {
            "strategy_id": "vwap_revert", "family": "mean_reversion", "batch": 2,
            "current_failure": "NATIVE_ENTRY_REGIME_HYPOTHESIS_INVALID",
            "forbidden_legacy": ["standalone_1m_promotion", "blind_vwap_touch", "trend-up chase"],
            "bundles": [
                bundle("vwap_revert:15m_context_5m_reclaim", "15m", "5m", "5m", "15m VWAP slope neutral or down; 5m upper deviation excursion then bearish close back toward VWAP", ["range", "shock_recovery"], "partial30 at VWAP touch then runner to lower deviation; timeout from time-to-MFE", "above excursion high", ["15m trend-up", "duplicate liquidity event", "gross excursion below cost floor"]),
                bundle("vwap_revert:5m_setup_1m_confirmation", "15m", "5m", "1m", "5m deviation and reclaim setup; 1m only confirms lower high and bearish close", ["range", "shock_recovery"], "VWAP touch primary exit; no 1m thesis or independent promotion", "above 5m sweep high", ["1m signal without 5m setup", "trend-up context"], role="trigger_module_candidate"),
            ],
        },
        {
            "strategy_id": "bb_revert", "family": "mean_reversion", "batch": 2,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["standalone_1m_band_touch", "range_fade_alias"],
            "bundles": [
                bundle("bb_revert:15m_neutral_5m_close_inside", "15m", "5m", "5m", "15m basis slope neutral; 5m close outside upper band followed by close back inside", ["range"], "basis partial30 then opposite inner band runner", "above excursion high", ["band expansion trend", "trend-up", "no close-back-inside"]),
                bundle("bb_revert:double_excursion_lower_high", "15m", "5m", "5m", "two upper-band excursions with second lower high and volatility contraction", ["range", "shock_recovery"], "basis target with volatility timeout", "above first excursion high", ["single touch only", "basis slope rising"]),
            ],
        },
        {
            "strategy_id": "range_fade", "family": "mean_reversion", "batch": 2,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["bb_revert_alias", "unconfirmed_range"],
            "bundles": [
                bundle("range_fade:confirmed_boundary_reject", "15m", "5m", "5m", "confirmed 15m range with repeated boundary tests; 5m upper-bound rejection", ["range"], "range midpoint partial30 then lower quartile runner", "outside confirmed range high", ["range width below cost floor", "trend transition", "first unconfirmed touch"]),
                bundle("range_fade:false_break_reentry", "15m", "5m", "5m", "false breakout above range then close back inside and failed retest", ["range", "shock_recovery"], "midpoint target then time stop", "above false-break extreme", ["acceptance above range", "second false-break cycle"]),
            ],
        },
        {
            "strategy_id": "liquidity_sweep", "family": "event_reversal", "batch": 3,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["standalone_1m_sweep", "same_pool_reentry"],
            "bundles": [
                bundle("liquidity_sweep:5m_prior_high_reclaim", "15m", "5m", "5m", "5m sweeps prior confirmed high, closes back below, then next bar confirms lower high", ["range", "shock_recovery", "trend_down"], "partial30 at sweep origin then runner to opposing liquidity", "above sweep extreme", ["no close-back-below", "same liquidity pool reused", "trend-up continuation"]),
                bundle("liquidity_sweep:equal_high_cluster", "15m", "5m", "5m", "clustered equal highs swept with volume expansion and immediate rejection", ["range", "shock_recovery"], "target range midpoint or imbalance fill", "above cluster sweep", ["single isolated high", "late entry after displacement"]),
            ],
        },
        {
            "strategy_id": "scalp_snap", "family": "scalp", "batch": 3,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["standalone_1m_strategy", "cost_subscale_target"],
            "bundles": [
                bundle("scalp_snap:15m_down_5m_pullback_1m_trigger", "15m", "5m", "1m", "15m trend down and 5m pullback rejection; 1m lower-high trigger only", ["trend_down"], "5m structural target with 1m execution only", "above 5m pullback high", ["1m signal without higher-timeframe setup", "target excursion below cost floor"]),
                bundle("scalp_snap:5m_impulse_retest", "15m", "5m", "1m", "5m bearish impulse then shallow retest; 1m rejection trigger", ["trend_down", "shock_recovery"], "partial30 at impulse low then runner", "above 5m retest high", ["deep retrace", "range noise"]),
            ],
        },
        {
            "strategy_id": "ema_ribbon_scalp", "family": "scalp", "batch": 3,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["standalone_1m_ribbon_cross", "scalp_snap_alias"],
            "bundles": [
                bundle("ema_ribbon_scalp:15m_stack_5m_compression_1m_retest", "15m", "5m", "1m", "15m bearish ribbon stack; 5m compression breaks down; 1m retest rejects", ["trend_down"], "5m ATR target with trailing after partial30", "above 5m compression high", ["ribbon flat", "cross-only entry", "1m without 5m break"]),
                bundle("ema_ribbon_scalp:5m_stack_pullback", "15m", "5m", "1m", "5m bearish ribbon stack and first pullback to fast ribbon; 1m lower high", ["trend_down"], "exit on 5m fast-ribbon reclaim or target", "above pullback high", ["late third pullback", "ribbon inversion"]),
            ],
        },
        {
            "strategy_id": "grid_rebalance", "family": "grid_range", "batch": 3,
            "current_failure": "NEGATIVE_EDGE_ENTRY_OR_REGIME",
            "forbidden_legacy": ["standalone_1m_grid", "multi_inventory", "trend_regime_grid"],
            "bundles": [
                bundle("grid_rebalance:15m_flat_5m_outer_quartile", "15m", "5m", "5m", "15m flat regime and stable range; single short at 5m upper outer quartile", ["range"], "rebalance at midpoint; one cycle only", "outside range plus ATR buffer", ["trend slope", "second inventory", "range width below cost floor"]),
                bundle("grid_rebalance:5m_atr_single_cycle", "15m", "5m", "5m", "5m ATR-normalized range with confirmed upper boundary and one rebalance cycle", ["range"], "midpoint full exit; no pyramiding", "one grid interval above boundary", ["volatility expansion", "open inventory", "grid spacing below fee-slippage floor"]),
            ],
        },
    ]


def self_test() -> int:
    specs = specifications()
    assert len(specs) == EXPECTED_STRATEGIES
    bundles = [item for spec in specs for item in spec["bundles"]]
    assert len(bundles) == EXPECTED_BUNDLES
    ids = [item["bundle_id"] for item in bundles]
    assert len(ids) == len(set(ids))
    contracts = [json.dumps({k: item[k] for k in ("entry_contract", "allowed_regimes", "exit_contract", "stop_contract", "vetoes")}, sort_keys=True) for item in bundles]
    assert len(contracts) == len(set(contracts))
    assert EXPECTED_BUNDLES * EXPECTED_STRESS_PER_BUNDLE == EXPECTED_DISCOVERY_CELLS
    print("STATE=PASS_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_SELF_TEST")
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
    required = [root / REPORT, root / CAUSAL, root / VERIFIED_PLAN, root / VWAP_PLAN]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("STATE=HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN_INPUT")
        print("BLOCKER_COUNT=1")
        print("BLOCKERS=" + json.dumps(["REQUIRED_EVIDENCE_MISSING:" + ",".join(missing)]))
        print("RC=2")
        return 2

    before = {str(path): sha256_file(path) for path in required}
    report = load_json(root / REPORT)
    causal = load_json(root / CAUSAL)
    blockers: list[str] = []
    if report.get("state") != "PASS_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT":
        blockers.append("VWAP_ECONOMIC_AUDIT_NOT_PASS")
    if int(report.get("economic_survivor_count", -1)) != 0:
        blockers.append("ZERO_VWAP_SURVIVOR_PRECONDITION_INVALID")
    if report.get("selected_candidate") is not None:
        blockers.append("VWAP_SELECTED_CANDIDATE_MUST_BE_NULL")
    remaining = report.get("remaining_uplift_rows") if isinstance(report.get("remaining_uplift_rows"), list) else []
    if len(remaining) != 10:
        blockers.append(f"REMAINING_STRATEGY_COUNT_INVALID:{len(remaining)}")
    if int(causal.get("strategy_count", -1)) != 11:
        blockers.append("CAUSAL_STRATEGY_COUNT_INVALID")

    specs = specifications()
    expected_ids = {spec["strategy_id"] for spec in specs}
    observed_ids = {str(row.get("strategy_id")) for row in remaining} | {"vwap_revert"}
    if observed_ids != expected_ids:
        blockers.append("STRATEGY_SET_MISMATCH")

    bundles = []
    for spec in specs:
        for item in spec["bundles"]:
            row = dict(item)
            row.update({"strategy_id": spec["strategy_id"], "family": spec["family"], "batch": spec["batch"], "current_failure": spec["current_failure"]})
            bundles.append(row)
    if len(bundles) != EXPECTED_BUNDLES:
        blockers.append("ARCHITECTURE_BUNDLE_COUNT_INVALID")
    contract_hashes = [hashlib.sha256(json.dumps({k: row[k] for k in ("entry_contract", "allowed_regimes", "exit_contract", "stop_contract", "vetoes")}, sort_keys=True).encode()).hexdigest() for row in bundles]
    if len(contract_hashes) != len(set(contract_hashes)):
        blockers.append("CROSS_STRATEGY_CONTRACT_ALIAS_DETECTED")

    after = {str(path): sha256_file(path) for path in required}
    mutations = sorted(path for path in before if before[path] != after[path])
    if mutations:
        blockers.append("INPUT_MUTATION_DETECTED:" + json.dumps(mutations))

    batch_histogram = dict(sorted(Counter(str(row["batch"]) for row in bundles).items()))
    family_histogram = dict(sorted(Counter(row["family"] for row in bundles).items()))
    state = "PASS_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN" if not blockers else "HOLD_SHORT_VWAP_NATIVE_HYPOTHESIS_AND_REMAINING_FAMILY_REBUILD_PLAN"
    plan = {
        "schema": "r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan_v1",
        "official_stage": "R7.A4D2_SHORT_VWAP_NATIVE_HYPOTHESIS_REBUILD_AND_REMAINING_10_STRATEGY_FAMILY_REBUILD_PLAN",
        "state": state,
        "target_commit": args.target_sha,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_count": len(specs),
        "architecture_bundle_count": len(bundles),
        "stress_cell_per_bundle": EXPECTED_STRESS_PER_BUNDLE,
        "discovery_cell_target": len(bundles) * EXPECTED_STRESS_PER_BUNDLE,
        "batch_histogram": batch_histogram,
        "family_histogram": family_histogram,
        "strategy_rebuild_rows": specs,
        "architecture_bundles": bundles,
        "discovery_batches": [
            {"batch": 1, "strategies": ["vol_spike_fade", "keltner_trend", "obv_trend", "anchor_vwap_trend"], "bundle_count": 8, "cell_target": 48},
            {"batch": 2, "strategies": ["vwap_revert", "bb_revert", "range_fade"], "bundle_count": 6, "cell_target": 36},
            {"batch": 3, "strategies": ["liquidity_sweep", "scalp_snap", "ema_ribbon_scalp", "grid_rebalance"], "bundle_count": 8, "cell_target": 48},
        ],
        "economic_gate": {
            "severe_trade_count_min": 8,
            "severe_profit_factor_gt": 1.0,
            "severe_expectancy_r_gt": 0.0,
            "severe_net_pnl_pct_gt": 0.0,
            "positive_stress_cell_min": 4,
            "drawdown_nonworsening_vs_native_or_family_reference": True,
        },
        "execution_policy": "NATIVE_STRATEGY_SPECIFIC_COMPLETE_ARCHITECTURE_BUNDLES_NO_GENERIC_SINGLE_AXIS_REUSE",
        "cross_strategy_alias_allowed": False,
        "standalone_1m_promotion_allowed": False,
        "retirement_before_bundle_execution_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "input_sha256": {str(path.relative_to(root)): sha256_file(path) for path in required},
        "input_mutation_paths": mutations,
        "next_stage": "R7.A4D2_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132",
    }
    atomic_json(root / OUTPUT, plan)
    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("STRATEGY_COUNT=" + str(len(specs)))
    print("ARCHITECTURE_BUNDLE_COUNT=" + str(len(bundles)))
    print("DISCOVERY_CELL_TARGET=" + str(len(bundles) * EXPECTED_STRESS_PER_BUNDLE))
    print("BATCH_HISTOGRAM=" + json.dumps(batch_histogram, sort_keys=True))
    print("FAMILY_HISTOGRAM=" + json.dumps(family_histogram, sort_keys=True))
    print("REBUILD_STRATEGY_IDS=" + json.dumps([spec["strategy_id"] for spec in specs]))
    print("ARCHITECTURE_BUNDLE_IDS=" + json.dumps([row["bundle_id"] for row in bundles]))
    print("CROSS_STRATEGY_ALIAS_ALLOWED=false")
    print("RETIREMENT_BEFORE_BUNDLE_EXECUTION_ALLOWED=false")
    print("PLAN_JSON=" + str(root / OUTPUT))
    print("NEXT_STAGE=" + plan["next_stage"])
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
