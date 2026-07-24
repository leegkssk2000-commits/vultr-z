from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_immediate_fail_loss_cap_oos as failed_rule
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_early_fail_reentry_lock_oos_v1"
BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
POLICY_ID = "same_symbol_side_setup_lock_until_opposite_supertrend_flip_v1"
MAX_FIXED_POINT_ITERATIONS = 16
MATERIAL_NET_PF_FLOOR = 1.05
MATERIAL_NET_RETURN_PCT_FLOOR = 2.0


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _profit_factor(values: Iterable[float]) -> Optional[float]:
    materialized = [float(value) for value in values]
    gains = sum(value for value in materialized if value > 0)
    losses = abs(sum(value for value in materialized if value < 0))
    if losses == 0:
        return None
    return gains / losses


def _setup_key(context: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(context.get("side", "")),
        str(context.get("trigger_signature", "")),
        str(context.get("confluence_signature", "")),
    )


def _rule_identity(rule: Mapping[str, Any]) -> Tuple[int, str, str, str]:
    return (
        int(rule["signal_bar"]),
        str(rule["side"]),
        str(rule["trigger_signature"]),
        str(rule["confluence_signature"]),
    )


def _opposite_reset_bar(features: pd.DataFrame, side: str, exit_bar: int) -> Optional[int]:
    reset_column = "supertrend_flip_down" if side == baseline.LONG else "supertrend_flip_up"
    for position in range(max(exit_bar + 1, 0), len(features)):
        if bool(features[reset_column].iloc[position]):
            return position
    return None


def _derive_lock_rules(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    replay: Mapping[str, Any],
    *,
    symbol: str,
    existing: Mapping[Tuple[int, str, str, str], Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    additions: List[Dict[str, Any]] = []
    trades = replay.get("trades") if isinstance(replay.get("trades"), list) else []
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        if str(trade.get("exit_reason")) != failed_rule.EARLY_EXIT_REASON:
            continue
        context = trade.get("entry_context") if isinstance(trade.get("entry_context"), Mapping) else {}
        side, trigger_signature, confluence_signature = _setup_key(context)
        if side not in (baseline.LONG, baseline.SHORT):
            continue
        if not trigger_signature or not confluence_signature:
            continue
        exit_bar = int(trade.get("exit_bar", -1))
        if exit_bar < 0:
            continue
        reset_bar = _opposite_reset_bar(features, side, exit_bar)
        end_exclusive = reset_bar if reset_bar is not None else len(features)
        signal_column = "long_entry_signal" if side == baseline.LONG else "short_entry_signal"
        for position in range(exit_bar + 1, end_exclusive):
            if not bool(features[signal_column].iloc[position]):
                continue
            signal_context = baseline._signal_context(frame, features, position, side)
            signal_key = _setup_key(signal_context)
            if signal_key != (side, trigger_signature, confluence_signature):
                continue
            rule = {
                "signal_bar": position,
                "signal_ts": baseline._timestamp(frame, position),
                "symbol": source.norm_symbol(symbol),
                "side": side,
                "trigger_signature": trigger_signature,
                "confirmation_signature": str(signal_context.get("confirmation_signature", "")),
                "confluence_signature": confluence_signature,
                "source_early_exit_bar": exit_bar,
                "source_early_exit_ts": trade.get("exit_ts"),
                "reset_bar": reset_bar,
                "reset_rule": "FIRST_OPPOSITE_SUPERTREND_FLIP_AFTER_EARLY_EXIT",
            }
            identity = _rule_identity(rule)
            if identity not in existing and all(_rule_identity(item) != identity for item in additions):
                additions.append(rule)
    return additions


def _run_with_rules(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    cost_bps_per_side: float,
    rules: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    original_filtered_features = failed_rule._filtered_features
    normalized_symbol = source.norm_symbol(symbol)
    rules_by_bar: Dict[int, List[Mapping[str, Any]]] = {}
    for rule in rules:
        if source.norm_symbol(str(rule.get("symbol", ""))) != normalized_symbol:
            continue
        rules_by_bar.setdefault(int(rule["signal_bar"]), []).append(rule)
    applied: List[Dict[str, Any]] = []

    def locked_filtered_features(
        source_frame: pd.DataFrame,
        cfg: Any,
        *,
        symbol: str,
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        features, survivor_blocked = original_filtered_features(source_frame, cfg, symbol=symbol)
        for position, bar_rules in sorted(rules_by_bar.items()):
            if position < 0 or position >= len(features):
                continue
            for rule in bar_rules:
                side = str(rule.get("side"))
                signal_column = "long_entry_signal" if side == baseline.LONG else "short_entry_signal"
                if not bool(features[signal_column].iloc[position]):
                    continue
                context = baseline._signal_context(source_frame, features, position, side)
                if _setup_key(context) != (
                    side,
                    str(rule.get("trigger_signature", "")),
                    str(rule.get("confluence_signature", "")),
                ):
                    continue
                features.loc[features.index[position], signal_column] = False
                applied.append(dict(rule))
                break
        return features, survivor_blocked

    failed_rule._filtered_features = locked_filtered_features
    try:
        replay = failed_rule._run_replay(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            replay_fold_id=replay_fold_id,
            cost_bps_per_side=cost_bps_per_side,
            early_invalidation_enabled=True,
        )
    finally:
        failed_rule._filtered_features = original_filtered_features

    unique_applied: Dict[Tuple[int, str, str, str], Dict[str, Any]] = {}
    for rule in applied:
        unique_applied[_rule_identity(rule)] = rule
    replay["reentry_lock_enabled"] = True
    replay["reentry_lock_policy_id"] = POLICY_ID
    replay["reentry_lock_rule_count"] = len(rules)
    replay["reentry_lock_applied_count"] = len(unique_applied)
    replay["reentry_lock_applied_signals"] = list(unique_applied.values())
    return replay


def _fixed_point_candidate(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    cost_bps_per_side: float,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cfg = baseline.IntegratedSupertrendPullbackConfig()
    cfg.validate()
    survivor_features, _ = failed_rule._filtered_features(frame, cfg, symbol=symbol)
    rules: Dict[Tuple[int, str, str, str], Dict[str, Any]] = {}
    replay = _run_with_rules(
        frame,
        symbol=symbol,
        timeframe=timeframe,
        replay_fold_id="BINGX_REAL_OOS_EARLY_FAIL_REENTRY_LOCK_ITERATION_0",
        cost_bps_per_side=cost_bps_per_side,
        rules=[],
    )
    iteration = 0
    fixed_point = False
    while iteration < MAX_FIXED_POINT_ITERATIONS:
        additions = _derive_lock_rules(
            frame,
            survivor_features,
            replay,
            symbol=symbol,
            existing=rules,
        )
        if not additions:
            fixed_point = True
            break
        for rule in additions:
            rules[_rule_identity(rule)] = rule
        iteration += 1
        replay = _run_with_rules(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            replay_fold_id=f"BINGX_REAL_OOS_EARLY_FAIL_REENTRY_LOCK_ITERATION_{iteration}",
            cost_bps_per_side=cost_bps_per_side,
            rules=list(rules.values()),
        )

    replay["reentry_lock_fixed_point"] = fixed_point
    replay["reentry_lock_iterations"] = iteration
    replay["reentry_lock_rules"] = list(rules.values())
    audit = {
        "fixed_point": fixed_point,
        "iterations": iteration,
        "rule_count": len(rules),
        "applied_count": int(replay.get("reentry_lock_applied_count", 0)),
        "rules": list(rules.values()),
    }
    return replay, audit


def _trade_stats(replays: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return failed_rule._trade_stats(replays)


def _pf_delta(left: Any, right: Any) -> Optional[float]:
    if not _finite(left) or not _finite(right):
        return None
    return float(left) - float(right)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only three-arm OOS audit. Preserve the frozen LINKUSDT loss-cluster survivor, "
            "reproduce the failed early-invalidation arm, then add only one new state rule: "
            "after an early invalidation, reject the same symbol/side/setup until the first opposite SuperTrend flip."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.cost_bps_per_side < 0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    baseline_dir = root / "runtime" / BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    survivor_replays: List[Dict[str, Any]] = []
    failed_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_rules = 0
    total_applied = 0
    max_iterations = 0
    all_fixed = True

    for symbol in symbols:
        try:
            csv_path = baseline_dir / f"{symbol.lower()}_15m.csv"
            stored_replay_path = baseline_dir / f"{symbol.lower()}_replay.json"
            frame = shared._load_frame(csv_path)
            stored_replay = shared._load_json(stored_replay_path)

            raw_baseline = baseline.run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_BASELINE_RECHECK",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            raw_invariant = shared._baseline_invariant(raw_baseline, stored_replay)
            if raw_invariant.get("status") != "PASS":
                raise RuntimeError(f"RAW_BASELINE_INVARIANT_FAILED:{symbol}:{raw_invariant.get('checks')}")

            survivor = survivor_filter._run_filtered_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_LINKUSDT_SURVIVOR_REFERENCE",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            copied_survivor = failed_rule._run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_LINKUSDT_SURVIVOR_COPY_PARITY",
                cost_bps_per_side=args.cost_bps_per_side,
                early_invalidation_enabled=False,
            )
            survivor_parity = failed_rule._parity(survivor, copied_survivor)
            if survivor_parity.get("status") != "PASS":
                raise RuntimeError(f"SURVIVOR_COPY_PARITY_FAILED:{symbol}:{survivor_parity.get('checks')}")

            failed_reference = failed_rule._run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FAILED_EARLY_INVALIDATION_REFERENCE",
                cost_bps_per_side=args.cost_bps_per_side,
                early_invalidation_enabled=True,
            )
            candidate, lock_audit = _fixed_point_candidate(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            total_rules += int(lock_audit["rule_count"])
            total_applied += int(lock_audit["applied_count"])
            max_iterations = max(max_iterations, int(lock_audit["iterations"]))
            all_fixed = all_fixed and bool(lock_audit["fixed_point"])

            survivor_replays.append(survivor)
            failed_replays.append(failed_reference)
            candidate_replays.append(candidate)
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "raw_baseline_invariant": raw_invariant,
                    "survivor_copy_parity": survivor_parity,
                    "lock_audit": lock_audit,
                    "survivor_trade_count": survivor.get("trade_count"),
                    "failed_trade_count": failed_reference.get("trade_count"),
                    "candidate_trade_count": candidate.get("trade_count"),
                    "survivor_net_return_pct": survivor.get("net_return_pct"),
                    "failed_net_return_pct": failed_reference.get("net_return_pct"),
                    "candidate_net_return_pct": candidate.get("net_return_pct"),
                    "survivor_net_profit_factor": survivor.get("net_profit_factor"),
                    "failed_net_profit_factor": failed_reference.get("net_profit_factor"),
                    "candidate_net_profit_factor": candidate.get("net_profit_factor"),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    survivor_metrics = shared._summary_metrics(survivor_replays)
    failed_metrics = shared._summary_metrics(failed_replays)
    candidate_metrics = shared._summary_metrics(candidate_replays)
    survivor_stats = _trade_stats(survivor_replays)
    failed_stats = _trade_stats(failed_replays)
    candidate_stats = _trade_stats(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers and all_fixed

    repair_vs_failed = bool(
        data_pass
        and total_applied > 0
        and candidate_metrics["trade_count"] <= failed_metrics["trade_count"]
        and shared._strictly_better(
            candidate_metrics["net_return_pct_sum"], failed_metrics["net_return_pct_sum"]
        )
        and shared._strictly_better(
            candidate_metrics["net_profit_factor"], failed_metrics["net_profit_factor"]
        )
    )
    restored_vs_survivor = bool(
        repair_vs_failed
        and candidate_metrics["net_return_pct_sum"] >= survivor_metrics["net_return_pct_sum"]
        and candidate_metrics["net_profit_factor"] is not None
        and survivor_metrics["net_profit_factor"] is not None
        and candidate_metrics["net_profit_factor"] >= survivor_metrics["net_profit_factor"]
        and candidate_metrics["trade_count"] <= survivor_metrics["trade_count"]
    )
    economic_survivor = bool(
        restored_vs_survivor
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and candidate_metrics["net_profit_factor"] is not None
        and candidate_metrics["net_profit_factor"] > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )
    material_improvement = bool(
        economic_survivor
        and candidate_metrics["net_profit_factor"] >= MATERIAL_NET_PF_FLOOR
        and candidate_metrics["net_return_pct_sum"] >= MATERIAL_NET_RETURN_PCT_FLOOR
    )

    if not data_pass:
        state = "HOLD_R7A4D_EARLY_FAIL_REENTRY_LOCK_DATA_PARITY_OR_FIXED_POINT_FAIL"
        next_stage = "ROLLBACK_THIS_CANDIDATE"
    elif material_improvement:
        state = "PASS_R7A4D_EARLY_FAIL_REENTRY_LOCK_MATERIAL_ECONOMIC_IMPROVEMENT"
        next_stage = "FREEZE_COMBINED_RULE_AND_RUN_SECOND_NONOVERLAPPING_OOS"
    elif economic_survivor:
        state = "PASS_R7A4D_EARLY_FAIL_REENTRY_LOCK_ECONOMIC_SURVIVOR"
        next_stage = "RUN_SECOND_NONOVERLAPPING_OOS_BEFORE_ANY_MORE_TUNING"
    elif repair_vs_failed:
        state = "HOLD_R7A4D_EARLY_FAIL_REENTRY_LOCK_REPAIRS_FAILED_ARM_BUT_NOT_SURVIVOR"
        next_stage = "ROLLBACK_EARLY_INVALIDATION_AND_REENTRY_LOCK_KEEP_FROZEN_SURVIVOR"
    else:
        state = "HOLD_R7A4D_EARLY_FAIL_REENTRY_LOCK_NO_CAUSAL_RECOVERY"
        next_stage = "ROLLBACK_EARLY_INVALIDATION_AND_REENTRY_LOCK_KEEP_FROZEN_SURVIVOR"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "target_sha": args.target_sha,
        "source_directory": str(baseline_dir),
        "output_directory": str(output_dir),
        "symbols": symbols,
        "interval": source.INTERVAL,
        "cost_bps_per_side": args.cost_bps_per_side,
        "frozen_survivor_entry_filter_policy_id": survivor_filter.POLICY_ID,
        "failed_early_invalidation_policy_id": failed_rule.POLICY_ID,
        "single_new_causal_rule": True,
        "new_rule": {
            "policy_id": POLICY_ID,
            "scope": "same symbol + same side + same trigger_signature + same confluence_signature",
            "activation": "after EARLY_INVALIDATION_NO_COST_COVERAGE_BY_BAR2 exit",
            "release": "first opposite SuperTrend flip after that exit",
            "decision_time": "confirmed bar close",
            "future_data_used": False,
            "source_strategy_mutated": False,
        },
        "total_lock_rule_count": total_rules,
        "total_lock_applied_count": total_applied,
        "max_fixed_point_iterations": max_iterations,
        "all_symbols_fixed_point": all_fixed,
        "results": results,
        "survivor": survivor_metrics,
        "failed_reference": failed_metrics,
        "candidate": candidate_metrics,
        "survivor_trade_stats": survivor_stats,
        "failed_trade_stats": failed_stats,
        "candidate_trade_stats": candidate_stats,
        "delta_candidate_vs_failed": {
            "trade_count": candidate_metrics["trade_count"] - failed_metrics["trade_count"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - failed_metrics["net_return_pct_sum"],
            "net_profit_factor": _pf_delta(
                candidate_metrics["net_profit_factor"], failed_metrics["net_profit_factor"]
            ),
        },
        "delta_candidate_vs_survivor": {
            "trade_count": candidate_metrics["trade_count"] - survivor_metrics["trade_count"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - survivor_metrics["net_return_pct_sum"],
            "net_profit_factor": _pf_delta(
                candidate_metrics["net_profit_factor"], survivor_metrics["net_profit_factor"]
            ),
        },
        "repair_vs_failed": repair_vs_failed,
        "restored_vs_survivor": restored_vs_survivor,
        "economic_survivor": economic_survivor,
        "material_improvement": material_improvement,
        "material_floors": {
            "net_profit_factor": MATERIAL_NET_PF_FLOOR,
            "net_return_pct_sum": MATERIAL_NET_RETURN_PCT_FLOOR,
        },
        "blockers": blockers,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"REENTRY_LOCK_RULES={total_rules}")
    print(f"REENTRY_LOCK_APPLIED={total_applied}")
    print(f"MAX_FIXED_POINT_ITERATIONS={max_iterations}")
    print(f"ALL_SYMBOLS_FIXED_POINT={str(all_fixed).lower()}")
    print(f"SURVIVOR_TRADES={survivor_metrics['trade_count']}")
    print(f"FAILED_TRADES={failed_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"SURVIVOR_NET_RETURN_PCT_SUM={survivor_metrics['net_return_pct_sum']:.6f}")
    print(f"FAILED_NET_RETURN_PCT_SUM={failed_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"SURVIVOR_NET_PF={survivor_metrics['net_profit_factor']}")
    print(f"FAILED_NET_PF={failed_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"SURVIVOR_WIN_RATE_PCT={survivor_stats['win_rate_pct']}")
    print(f"FAILED_WIN_RATE_PCT={failed_stats['win_rate_pct']}")
    print(f"CANDIDATE_WIN_RATE_PCT={candidate_stats['win_rate_pct']}")
    print(f"SURVIVOR_AVG_WIN_NET_PCT={survivor_stats['avg_win_net_pct']}")
    print(f"SURVIVOR_AVG_LOSS_NET_PCT={survivor_stats['avg_loss_net_pct']}")
    print(f"SURVIVOR_PAYOFF_RATIO_PCT={survivor_stats['payoff_ratio_pct']}")
    print(f"CANDIDATE_AVG_WIN_NET_PCT={candidate_stats['avg_win_net_pct']}")
    print(f"CANDIDATE_AVG_LOSS_NET_PCT={candidate_stats['avg_loss_net_pct']}")
    print(f"CANDIDATE_PAYOFF_RATIO_PCT={candidate_stats['payoff_ratio_pct']}")
    print(f"CANDIDATE_AVG_WIN_NET_R={candidate_stats['avg_win_net_r']}")
    print(f"CANDIDATE_AVG_LOSS_NET_R={candidate_stats['avg_loss_net_r']}")
    print(f"CANDIDATE_PAYOFF_RATIO_R={candidate_stats['payoff_ratio_r']}")
    print(f"REPAIR_VS_FAILED={str(repair_vs_failed).lower()}")
    print(f"RESTORED_VS_SURVIVOR={str(restored_vs_survivor).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"MATERIAL_IMPROVEMENT={str(material_improvement).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={blockers}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
