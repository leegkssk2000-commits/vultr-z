from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos_v1"
BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
POLICY_ID = "reject_linkusdt_short_confirmation_edge_sr_touch_plus_trendline_touch_v1"
TARGET_SYMBOL = "LINKUSDT"
TARGET_SIDE = baseline.SHORT
TARGET_TRIGGER_SIGNATURE = "confirmation_edge"
TARGET_CONFLUENCE_SIGNATURE = "sr_touch+trendline_touch"
DIAGNOSTIC_EXIT_REASON = "SUPERTREND_TRAILING_STOP"


def _matches_target_cluster(symbol: str, context: Mapping[str, Any]) -> bool:
    return (
        source.norm_symbol(symbol) == TARGET_SYMBOL
        and str(context.get("side")) == TARGET_SIDE
        and str(context.get("trigger_signature")) == TARGET_TRIGGER_SIGNATURE
        and str(context.get("confluence_signature")) == TARGET_CONFLUENCE_SIGNATURE
    )


def _run_filtered_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    cost_bps_per_side: float,
) -> Dict[str, Any]:
    original_compute: Callable[..., pd.DataFrame] = baseline.compute_features
    blocked: List[Dict[str, Any]] = []

    def filtered_compute(source_frame: pd.DataFrame, cfg: Any) -> pd.DataFrame:
        features = original_compute(source_frame, cfg).copy()
        for position in range(len(features)):
            if not bool(features["short_entry_signal"].iloc[position]):
                continue
            context = baseline._signal_context(source_frame, features, position, baseline.SHORT)
            if not _matches_target_cluster(symbol, context):
                continue
            features.loc[features.index[position], "short_entry_signal"] = False
            blocked.append(
                {
                    "bar": position,
                    "timestamp": baseline._timestamp(source_frame, position),
                    "symbol": source.norm_symbol(symbol),
                    "side": baseline.SHORT,
                    "trigger_signature": context["trigger_signature"],
                    "confirmation_signature": context["confirmation_signature"],
                    "confluence_signature": context["confluence_signature"],
                    "dema_distance_atr": context.get("dema_distance_atr"),
                    "rsi14": context.get("rsi14"),
                }
            )
        return features

    baseline.compute_features = filtered_compute
    try:
        replay = baseline.run_replay(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            replay_fold_id=replay_fold_id,
            cost_bps_per_side=cost_bps_per_side,
        )
    finally:
        baseline.compute_features = original_compute

    replay["replay_profile_id"] = "integrated_supertrend_linkusdt_single_loss_cluster_replay_v1"
    replay["single_causal_entry_filter"] = True
    replay["entry_filter_policy_id"] = POLICY_ID
    replay["entry_filter_definition"] = {
        "symbol": TARGET_SYMBOL,
        "side": TARGET_SIDE,
        "trigger_signature": TARGET_TRIGGER_SIGNATURE,
        "confluence_signature": TARGET_CONFLUENCE_SIGNATURE,
        "symbol_specific": True,
        "diagnostic_exit_reason": DIAGNOSTIC_EXIT_REASON,
        "exit_reason_used_for_filtering": False,
        "future_data_used": False,
    }
    replay["blocked_entry_signal_count"] = len(blocked)
    replay["blocked_entry_signals"] = blocked
    return replay


def _scope_is_exact(replays: List[Mapping[str, Any]]) -> bool:
    for replay in replays:
        for blocked in replay.get("blocked_entry_signals", []):
            if not isinstance(blocked, Mapping):
                return False
            if source.norm_symbol(str(blocked.get("symbol", ""))) != TARGET_SYMBOL:
                return False
            if str(blocked.get("side")) != TARGET_SIDE:
                return False
            if str(blocked.get("trigger_signature")) != TARGET_TRIGGER_SIGNATURE:
                return False
            if str(blocked.get("confluence_signature")) != TARGET_CONFLUENCE_SIGNATURE:
                return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only OOS test removing only the planned LINKUSDT short loss cluster: "
            "confirmation_edge at sr_touch+trendline_touch."
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

    if TARGET_SYMBOL not in symbols:
        raise ValueError(f"TARGET_SYMBOL_MISSING:{TARGET_SYMBOL}")

    baseline_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_blocked = 0

    for symbol in symbols:
        try:
            csv_path = baseline_dir / f"{symbol.lower()}_15m.csv"
            stored_replay_path = baseline_dir / f"{symbol.lower()}_replay.json"
            frame = shared._load_frame(csv_path)
            stored_replay = shared._load_json(stored_replay_path)

            same_window_baseline = baseline.run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_BASELINE_RECHECK",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            invariant = shared._baseline_invariant(same_window_baseline, stored_replay)
            if invariant["status"] != "PASS":
                raise RuntimeError(f"BASELINE_INVARIANT_FAILED:{symbol}:{invariant['checks']}")

            candidate = _run_filtered_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_LINKUSDT_SINGLE_LOSS_CLUSTER",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            blocked = int(candidate["blocked_entry_signal_count"])
            total_blocked += blocked
            baseline_replays.append(same_window_baseline)
            candidate_replays.append(candidate)
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "blocked_entry_signal_count": blocked,
                    "baseline_invariant": invariant,
                    "baseline_trade_count": same_window_baseline["trade_count"],
                    "candidate_trade_count": candidate["trade_count"],
                    "baseline_gross_return_pct": same_window_baseline["gross_return_pct"],
                    "candidate_gross_return_pct": candidate["gross_return_pct"],
                    "baseline_net_return_pct": same_window_baseline["net_return_pct"],
                    "candidate_net_return_pct": candidate["net_return_pct"],
                    "baseline_gross_profit_factor": same_window_baseline["gross_profit_factor"],
                    "candidate_gross_profit_factor": candidate["gross_profit_factor"],
                    "baseline_net_profit_factor": same_window_baseline["net_profit_factor"],
                    "candidate_net_profit_factor": candidate["net_profit_factor"],
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    baseline_metrics = shared._summary_metrics(baseline_replays)
    candidate_metrics = shared._summary_metrics(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers
    exact_scope = data_pass and total_blocked > 0 and _scope_is_exact(candidate_replays)
    causal_improvement = bool(
        exact_scope
        and candidate_metrics["trade_count"] < baseline_metrics["trade_count"]
        and shared._strictly_better(
            candidate_metrics["gross_return_pct_sum"], baseline_metrics["gross_return_pct_sum"]
        )
        and shared._strictly_better(
            candidate_metrics["gross_profit_factor"], baseline_metrics["gross_profit_factor"]
        )
        and shared._strictly_better(
            candidate_metrics["net_return_pct_sum"], baseline_metrics["net_return_pct_sum"]
        )
        and shared._strictly_better(
            candidate_metrics["net_profit_factor"], baseline_metrics["net_profit_factor"]
        )
    )
    economic_survivor = bool(
        causal_improvement
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and candidate_metrics["net_profit_factor"] is not None
        and candidate_metrics["net_profit_factor"] > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )

    if not data_pass or not exact_scope:
        state = "HOLD_R7A4D_LINKUSDT_SINGLE_LOSS_CLUSTER_SCOPE_OR_DATA_FAIL"
        next_stage = "ROLLBACK_THIS_CANDIDATE"
    elif economic_survivor:
        state = "PASS_R7A4D_LINKUSDT_SINGLE_LOSS_CLUSTER_ECONOMIC_SURVIVOR"
        next_stage = "RUN_SECOND_NONOVERLAPPING_OOS_WITH_SAME_SINGLE_FILTER"
    elif causal_improvement:
        state = "HOLD_R7A4D_LINKUSDT_SINGLE_LOSS_CLUSTER_IMPROVED_NOT_POSITIVE"
        next_stage = "KEEP_RESEARCH_ONLY_AND_REPORT_EXACT_DELTA"
    else:
        state = "HOLD_R7A4D_LINKUSDT_SINGLE_LOSS_CLUSTER_NO_CAUSAL_IMPROVEMENT"
        next_stage = "ROLLBACK_THIS_SINGLE_FILTER"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "single_loss_cluster_only": True,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "target_sha": args.target_sha,
        "source_directory": str(baseline_dir),
        "output_directory": str(output_dir),
        "source": "existing BingX public 15m fixed-window baseline CSVs",
        "interval": source.INTERVAL,
        "symbols": symbols,
        "cost_bps_per_side": args.cost_bps_per_side,
        "entry_filter_policy_id": POLICY_ID,
        "source_loss_cluster": {
            "symbol": TARGET_SYMBOL,
            "side": TARGET_SIDE,
            "trigger_signature": TARGET_TRIGGER_SIGNATURE,
            "confluence_signature": TARGET_CONFLUENCE_SIGNATURE,
            "diagnostic_exit_reason": DIAGNOSTIC_EXIT_REASON,
        },
        "filter_contract": {
            "symbol": TARGET_SYMBOL,
            "side": TARGET_SIDE,
            "trigger_signature": TARGET_TRIGGER_SIGNATURE,
            "confluence_signature": TARGET_CONFLUENCE_SIGNATURE,
            "exit_reason_used_for_filtering": False,
            "future_data_used": False,
        },
        "blocked_entry_signal_count": total_blocked,
        "exact_scope": exact_scope,
        "results": results,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "delta": {
            "trade_count": candidate_metrics["trade_count"] - baseline_metrics["trade_count"],
            "gross_return_pct_sum": candidate_metrics["gross_return_pct_sum"]
            - baseline_metrics["gross_return_pct_sum"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"]
            - baseline_metrics["net_return_pct_sum"],
            "gross_profit_factor": (
                candidate_metrics["gross_profit_factor"] - baseline_metrics["gross_profit_factor"]
                if shared._finite(candidate_metrics["gross_profit_factor"])
                and shared._finite(baseline_metrics["gross_profit_factor"])
                else None
            ),
            "net_profit_factor": (
                candidate_metrics["net_profit_factor"] - baseline_metrics["net_profit_factor"]
                if shared._finite(candidate_metrics["net_profit_factor"])
                and shared._finite(baseline_metrics["net_profit_factor"])
                else None
            ),
            "positive_symbol_count": candidate_metrics["positive_symbol_count"]
            - baseline_metrics["positive_symbol_count"],
        },
        "causal_improvement": causal_improvement,
        "economic_survivor": economic_survivor,
        "blockers": blockers,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"TARGET_CLUSTER={TARGET_SYMBOL}|{TARGET_SIDE}|{TARGET_TRIGGER_SIGNATURE}|{TARGET_CONFLUENCE_SIGNATURE}")
    print(f"BLOCKED_ENTRY_SIGNALS={total_blocked}")
    print(f"EXACT_SCOPE={str(exact_scope).lower()}")
    print(f"BASELINE_TRADES={baseline_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"BASELINE_GROSS_RETURN_PCT_SUM={baseline_metrics['gross_return_pct_sum']:.6f}")
    print(f"CANDIDATE_GROSS_RETURN_PCT_SUM={candidate_metrics['gross_return_pct_sum']:.6f}")
    print(f"BASELINE_NET_RETURN_PCT_SUM={baseline_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"BASELINE_GROSS_PF={baseline_metrics['gross_profit_factor']}")
    print(f"CANDIDATE_GROSS_PF={candidate_metrics['gross_profit_factor']}")
    print(f"BASELINE_NET_PF={baseline_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"POSITIVE_SYMBOLS={candidate_metrics['positive_symbol_count']}/{len(symbols)}")
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"RC={0 if data_pass and exact_scope else 2}")
    return 0 if data_pass and exact_scope else 2


if __name__ == "__main__":
    raise SystemExit(main())
