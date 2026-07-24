from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_early_fail_reentry_lock_oos as candidate_source
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_entry_origin_anatomy_v1"
ANALYSIS_ID = "single_strategy_entry_origin_win_loss_decomposition_v1"
TOP_LIMIT = 30


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _profit_factor(values: Iterable[float]) -> Optional[float]:
    materialized = [float(value) for value in values]
    gains = sum(value for value in materialized if value > 0.0)
    losses = abs(sum(value for value in materialized if value < 0.0))
    if losses == 0.0:
        return None if gains == 0.0 else float("inf")
    return gains / losses


def _mean(values: Iterable[Any]) -> Optional[float]:
    materialized = [float(value) for value in values if _finite(value)]
    if not materialized:
        return None
    return sum(materialized) / len(materialized)


def _stats(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    returns = [float(trade.get("net_return_pct", 0.0)) for trade in trades]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value <= 0.0]
    strict_losses = [value for value in returns if value < 0.0]
    avg_win = _mean(wins)
    avg_loss = _mean(strict_losses)
    payoff = None
    if avg_win is not None and avg_loss not in (None, 0.0):
        payoff = avg_win / abs(avg_loss)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "strict_loss_count": len(strict_losses),
        "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else None,
        "net_return_pct_sum": sum(returns),
        "net_profit_factor": _profit_factor(returns),
        "avg_win_net_pct": avg_win,
        "avg_loss_net_pct": avg_loss,
        "payoff_ratio_pct": payoff,
        "mean_hold_bars": _mean(trade.get("hold_bars") for trade in trades),
        "mean_mfe_pct": _mean(trade.get("mfe_pct") for trade in trades),
        "mean_mae_pct": _mean(trade.get("mae_pct") for trade in trades),
    }


def _components(context: Mapping[str, Any], key: str) -> List[str]:
    raw = context.get(key)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item)]


def _entry_origin(trigger_components: Sequence[str]) -> str:
    trigger_set = set(trigger_components)
    if "supertrend_flip" in trigger_set:
        return "PRIMARY_ST_FLIP"
    if "dema_cross" in trigger_set:
        return "ALTERNATIVE_DEMA_CROSS"
    if "confirmation_edge" in trigger_set:
        return "AUXILIARY_CONFIRMATION_EDGE_ONLY"
    return "UNRESOLVED_ENTRY_ORIGIN"


def _source_role(entry_origin: str) -> str:
    if entry_origin == "PRIMARY_ST_FLIP":
        return "CORE_PRIMARY_ENTRY"
    if entry_origin == "ALTERNATIVE_DEMA_CROSS":
        return "SOURCE_DESCRIBED_ALTERNATIVE_ENTRY"
    if entry_origin == "AUXILIARY_CONFIRMATION_EDGE_ONLY":
        return "AUXILIARY_CONFIRMATION_PROMOTED_TO_ENTRY"
    return "UNRESOLVED"


def _confirmation_family(confirmation_components: Sequence[str]) -> str:
    items = set(confirmation_components)
    families: List[str] = []
    if items.intersection({"bullish_engulfing", "bearish_engulfing", "hammer"}):
        families.append("CANDLE_CONFIRM")
    if items.intersection({"counter_trend_break_up", "counter_trend_break_down"}):
        families.append("COUNTER_TRENDLINE")
    if items.intersection({"rsi_cross_up", "rsi_cross_down"}):
        families.append("RSI50_CONFIRM")
    return "+".join(families) if families else "NO_CONFIRMATION_FAMILY"


def _enrich(trade: Mapping[str, Any]) -> Dict[str, Any]:
    item = dict(trade)
    context = item.get("entry_context") if isinstance(item.get("entry_context"), Mapping) else {}
    trigger_components = _components(context, "trigger_components")
    confirmation_components = _components(context, "confirmation_components")
    confluence_components = _components(context, "confluence_components")
    entry_origin = _entry_origin(trigger_components)
    trigger_signature = str(context.get("trigger_signature") or "UNRESOLVED")
    confirmation_signature = str(context.get("confirmation_signature") or "UNRESOLVED")
    confluence_signature = str(context.get("confluence_signature") or "NONE")
    confirmation_family = _confirmation_family(confirmation_components)
    item.update(
        {
            "outcome": "WIN" if float(item.get("net_return_pct", 0.0)) > 0.0 else "LOSS",
            "entry_origin": entry_origin,
            "source_role": _source_role(entry_origin),
            "trigger_signature": trigger_signature,
            "trigger_overlap_signature": "+".join(trigger_components) if trigger_components else "UNRESOLVED",
            "confirmation_family": confirmation_family,
            "confirmation_signature": confirmation_signature,
            "confluence_signature": confluence_signature,
            "full_cluster": "|".join(
                [
                    str(item.get("symbol", "UNKNOWN")),
                    str(item.get("side", "UNKNOWN")),
                    entry_origin,
                    trigger_signature,
                    confirmation_signature,
                    confluence_signature,
                ]
            ),
        }
    )
    return item


def _group(trades: Sequence[Mapping[str, Any]], field: str) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        buckets[str(trade.get(field, "UNKNOWN"))].append(trade)
    rows = []
    for key, bucket in buckets.items():
        rows.append({"group": key, **_stats(bucket)})
    rows.sort(
        key=lambda row: (
            -int(row["trade_count"]),
            float(row["net_return_pct_sum"]),
            str(row["group"]),
        )
    )
    return rows


def _pf_delta(left: Any, right: Any) -> Optional[float]:
    if not _finite(left) or not _finite(right):
        return None
    return float(left) - float(right)


def _single_group_removal_candidates(
    trades: Sequence[Mapping[str, Any]],
    overall: Mapping[str, Any],
    fields: Sequence[str],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for field in fields:
        values = sorted({str(trade.get(field, "UNKNOWN")) for trade in trades})
        for value in values:
            removed = [trade for trade in trades if str(trade.get(field, "UNKNOWN")) == value]
            if not removed:
                continue
            removed_stats = _stats(removed)
            if float(removed_stats["net_return_pct_sum"]) >= 0.0:
                continue
            remaining = [trade for trade in trades if str(trade.get(field, "UNKNOWN")) != value]
            remaining_stats = _stats(remaining)
            candidates.append(
                {
                    "dimension": field,
                    "group": value,
                    "removed": removed_stats,
                    "remaining": remaining_stats,
                    "net_return_improvement_pct": (
                        float(remaining_stats["net_return_pct_sum"])
                        - float(overall["net_return_pct_sum"])
                    ),
                    "net_pf_improvement": _pf_delta(
                        remaining_stats.get("net_profit_factor"),
                        overall.get("net_profit_factor"),
                    ),
                    "win_rate_delta_pct_point": (
                        float(remaining_stats["win_rate_pct"])
                        - float(overall["win_rate_pct"])
                    )
                    if remaining_stats.get("win_rate_pct") is not None
                    and overall.get("win_rate_pct") is not None
                    else None,
                    "winner_contamination_count": int(removed_stats["win_count"]),
                    "losses_removed_count": int(removed_stats["loss_count"]),
                    "loss_precision_pct": (
                        float(removed_stats["loss_count"])
                        / float(removed_stats["trade_count"])
                        * 100.0
                    ),
                    "high_precision_single_cause_candidate": bool(
                        int(removed_stats["loss_count"]) >= 10
                        and int(removed_stats["win_count"]) <= 1
                        and float(remaining_stats["net_return_pct_sum"])
                        > float(overall["net_return_pct_sum"])
                    ),
                }
            )
    candidates.sort(
        key=lambda row: (
            -float(row["net_return_improvement_pct"]),
            int(row["winner_contamination_count"]),
            -int(row["losses_removed_count"]),
            str(row["dimension"]),
            str(row["group"]),
        )
    )
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only decomposition of the failed 227-trade arm into entry origin, exact trigger, "
            "confirmation family, confluence and full symbol-side clusters. No strategy mutation."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    baseline_dir = root / "runtime" / candidate_source.BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    all_trades: List[Dict[str, Any]] = []
    per_symbol: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_rules = 0
    total_applied = 0
    all_fixed = True

    for symbol in symbols:
        try:
            frame = shared._load_frame(baseline_dir / f"{symbol.lower()}_15m.csv")
            replay, lock_audit = candidate_source._fixed_point_candidate(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            enriched = [_enrich(trade) for trade in replay.get("trades", []) if isinstance(trade, Mapping)]
            all_trades.extend(enriched)
            total_rules += int(lock_audit.get("rule_count", 0))
            total_applied += int(lock_audit.get("applied_count", 0))
            all_fixed = all_fixed and bool(lock_audit.get("fixed_point"))
            per_symbol.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "trade_stats": _stats(enriched),
                    "entry_origin_stats": _group(enriched, "entry_origin"),
                    "lock_audit": lock_audit,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            per_symbol.append({"symbol": symbol, "status": "HOLD", "error": error})

    overall = _stats(all_trades)
    grouping_fields = (
        "entry_origin",
        "source_role",
        "trigger_signature",
        "trigger_overlap_signature",
        "confirmation_family",
        "confirmation_signature",
        "confluence_signature",
        "full_cluster",
    )
    grouped = {field: _group(all_trades, field) for field in grouping_fields}
    removal_candidates = _single_group_removal_candidates(
        all_trades,
        overall,
        (
            "entry_origin",
            "trigger_signature",
            "confirmation_family",
            "confirmation_signature",
            "confluence_signature",
            "full_cluster",
        ),
    )
    high_precision = [
        row for row in removal_candidates if bool(row["high_precision_single_cause_candidate"])
    ]

    data_pass = bool(
        len(per_symbol) == len(symbols)
        and not blockers
        and all_fixed
        and int(overall["trade_count"]) > 0
    )
    state = (
        "PASS_R7A4D_ENTRY_ORIGIN_WIN_LOSS_DECOMPOSITION"
        if data_pass
        else "HOLD_R7A4D_ENTRY_ORIGIN_DECOMPOSITION_DATA_FAIL"
    )
    next_stage = (
        "SELECT_ONE_HIGH_PRECISION_ENTRY_FILTER_FROM_ANATOMY"
        if data_pass and high_precision
        else "REVIEW_TOP_SINGLE_REMOVAL_CANDIDATES_WITHOUT_PATCHING"
        if data_pass
        else "REPAIR_DATA_OR_REPLAY_PARITY_ONLY"
    )

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "analysis_id": ANALYSIS_ID,
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "target_sha": args.target_sha,
        "source_candidate_branch_policy": candidate_source.POLICY_ID,
        "source_directory": str(baseline_dir),
        "output_directory": str(output_dir),
        "symbols": symbols,
        "interval": source.INTERVAL,
        "cost_bps_per_side": args.cost_bps_per_side,
        "reentry_lock_rule_count": total_rules,
        "reentry_lock_applied_count": total_applied,
        "all_symbols_fixed_point": all_fixed,
        "overall": overall,
        "per_symbol": per_symbol,
        "grouped": grouped,
        "top_loss_clusters": sorted(
            grouped["full_cluster"],
            key=lambda row: (float(row["net_return_pct_sum"]), -int(row["loss_count"])),
        )[:TOP_LIMIT],
        "top_single_group_removal_candidates": removal_candidates[:TOP_LIMIT],
        "high_precision_single_cause_candidates": high_precision[:TOP_LIMIT],
        "blockers": blockers,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={sum(row.get('status') == 'PASS' for row in per_symbol)}/{len(symbols)}")
    print(f"TRADES={overall['trade_count']}")
    print(f"WINS={overall['win_count']}")
    print(f"LOSSES={overall['loss_count']}")
    print(f"WIN_RATE_PCT={overall['win_rate_pct']}")
    print(f"NET_RETURN_PCT_SUM={overall['net_return_pct_sum']:.6f}")
    print(f"NET_PF={overall['net_profit_factor']}")
    print(f"PAYOFF_RATIO_PCT={overall['payoff_ratio_pct']}")
    print(f"ENTRY_ORIGIN_STATS={source.json.dumps(grouped['entry_origin'], ensure_ascii=False, sort_keys=True)}")
    print(f"TRIGGER_SIGNATURE_STATS={source.json.dumps(grouped['trigger_signature'], ensure_ascii=False, sort_keys=True)}")
    print(f"CONFIRMATION_FAMILY_STATS={source.json.dumps(grouped['confirmation_family'], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_LOSS_CLUSTERS={source.json.dumps(summary['top_loss_clusters'][:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_SINGLE_REMOVAL_CANDIDATES={source.json.dumps(removal_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"HIGH_PRECISION_CANDIDATE_COUNT={len(high_precision)}")
    print(f"OUTPUT={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={source.json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
