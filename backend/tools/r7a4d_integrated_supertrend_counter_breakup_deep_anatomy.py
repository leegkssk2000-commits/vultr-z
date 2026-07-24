from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import r7a4d_integrated_supertrend_entry_origin_anatomy as parent

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_counter_breakup_deep_anatomy_v1"
ANALYSIS_ID = "counter_trend_break_up_preentry_subcluster_decomposition_v1"
TARGET_CONFIRMATION_SIGNATURE = "counter_trend_break_up"
TOP_LIMIT = 20


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _float(value: Any) -> Optional[float]:
    return float(value) if _finite(value) else None


def _bucket(value: Any, cuts: Sequence[float], labels: Sequence[str]) -> str:
    number = _float(value)
    if number is None:
        return "UNKNOWN"
    for cut, label in zip(cuts, labels):
        if number <= cut:
            return label
    return labels[-1]


def _trade_key(trade: Mapping[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        str(trade.get("symbol", "UNKNOWN")),
        str(trade.get("side", "UNKNOWN")),
        str(trade.get("entry_ts", "UNKNOWN")),
        str(trade.get("entry_bar", "UNKNOWN")),
        str(trade.get("exit_bar", "UNKNOWN")),
    )


def _signed_for_side(value: Any, side: str) -> Optional[float]:
    number = _float(value)
    if number is None:
        return None
    return number if str(side).lower() == "long" else -number


def _enrich_deep(trade: Mapping[str, Any]) -> Dict[str, Any]:
    item = parent._enrich(trade)
    context = item.get("entry_context") if isinstance(item.get("entry_context"), Mapping) else {}
    side = str(item.get("side", "UNKNOWN"))

    dema_distance_atr = _signed_for_side(context.get("dema_distance_atr"), side)
    dema_distance_pct = _signed_for_side(context.get("dema_distance_pct"), side)
    next_open_gap_pct = _signed_for_side(context.get("next_open_gap_pct"), side)
    rsi14 = _float(context.get("rsi14"))
    rsi_strength = None
    if rsi14 is not None:
        rsi_strength = rsi14 - 50.0 if side.lower() == "long" else 50.0 - rsi14

    stop_distance = _float(item.get("initial_stop_distance_pct"))
    mfe = _float(item.get("mfe_pct"))
    mae_abs = _float(item.get("mae_abs_pct"))
    hold_bars = _float(item.get("hold_bars"))
    confluence_count = context.get("confluence_count")

    item.update(
        {
            "structure_valid": bool(context.get("structure_valid")),
            "confluence_count": int(confluence_count) if _finite(confluence_count) else None,
            "trend_dema_distance_atr": dema_distance_atr,
            "trend_dema_distance_pct": dema_distance_pct,
            "favorable_next_open_gap_pct": next_open_gap_pct,
            "rsi_trend_strength": rsi_strength,
            "dema_distance_atr_bucket": _bucket(
                dema_distance_atr,
                (0.0, 0.25, 0.50, 1.00, float("inf")),
                ("LE_0", "0_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "GT_1_00"),
            ),
            "dema_distance_pct_bucket": _bucket(
                dema_distance_pct,
                (0.0, 0.10, 0.25, 0.50, float("inf")),
                ("LE_0", "0_TO_0_10", "0_10_TO_0_25", "0_25_TO_0_50", "GT_0_50"),
            ),
            "next_open_gap_bucket": _bucket(
                next_open_gap_pct,
                (-0.10, 0.0, 0.05, 0.15, float("inf")),
                ("ADVERSE_GT_0_10", "ADVERSE_TO_FLAT", "FAVORABLE_0_TO_0_05", "FAVORABLE_0_05_TO_0_15", "FAVORABLE_GT_0_15"),
            ),
            "rsi_strength_bucket": _bucket(
                rsi_strength,
                (0.0, 5.0, 10.0, float("inf")),
                ("LE_0", "0_TO_5", "5_TO_10", "GT_10"),
            ),
            "stop_distance_bucket": _bucket(
                stop_distance,
                (0.0, 0.25, 0.50, 1.00, float("inf")),
                ("INVALID_OR_ZERO", "0_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "GT_1_00"),
            ),
            "confluence_count_bucket": (
                "UNKNOWN"
                if not _finite(confluence_count)
                else "0"
                if int(confluence_count) <= 0
                else "1"
                if int(confluence_count) == 1
                else "2"
                if int(confluence_count) == 2
                else "3_PLUS"
            ),
            "mfe_bucket": _bucket(
                mfe,
                (0.08, 0.25, 0.50, 1.00, float("inf")),
                ("LE_ROUND_TRIP_COST", "0_08_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "GT_1_00"),
            ),
            "mae_bucket": _bucket(
                mae_abs,
                (0.25, 0.50, 1.00, 2.00, float("inf")),
                ("LE_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "1_00_TO_2_00", "GT_2_00"),
            ),
            "hold_bucket": _bucket(
                hold_bars,
                (3.0, 8.0, 16.0, 32.0, float("inf")),
                ("LE_3", "4_TO_8", "9_TO_16", "17_TO_32", "GT_32"),
            ),
        }
    )
    return item


def _group(trades: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
        buckets[key].append(trade)
    rows: List[Dict[str, Any]] = []
    for key, bucket in buckets.items():
        rows.append(
            {
                "dimension": "+".join(fields),
                "group": "|".join(key),
                **parent._stats(bucket),
            }
        )
    rows.sort(
        key=lambda row: (
            float(row["net_return_pct_sum"]),
            -int(row["strict_loss_count"]),
            int(row["win_count"]),
            str(row["group"]),
        )
    )
    return rows


def _positive_symbol_count(trades: Sequence[Mapping[str, Any]]) -> int:
    symbols = sorted({str(trade.get("symbol", "UNKNOWN")) for trade in trades})
    return sum(
        1
        for symbol in symbols
        if float(parent._stats([trade for trade in trades if str(trade.get("symbol")) == symbol])["net_return_pct_sum"]) > 0.0
    )


def _candidate(
    all_trades: Sequence[Mapping[str, Any]],
    target: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    values: Sequence[str],
    overall: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    removed = [
        trade
        for trade in target
        if all(str(trade.get(field, "UNKNOWN")) == value for field, value in zip(fields, values))
    ]
    if not removed or len(removed) == len(target):
        return None
    removed_stats = parent._stats(removed)
    if float(removed_stats["net_return_pct_sum"]) >= 0.0:
        return None

    removed_keys = {_trade_key(trade) for trade in removed}
    remaining = [trade for trade in all_trades if _trade_key(trade) not in removed_keys]
    remaining_stats = parent._stats(remaining)
    remaining_pf = remaining_stats.get("net_profit_factor")
    overall_pf = overall.get("net_profit_factor")
    pf_delta = None
    if _finite(remaining_pf) and _finite(overall_pf):
        pf_delta = float(remaining_pf) - float(overall_pf)

    loss_precision = (
        float(removed_stats["strict_loss_count"]) / float(removed_stats["trade_count"]) * 100.0
        if int(removed_stats["trade_count"]) > 0
        else 0.0
    )
    high_precision = bool(
        int(removed_stats["strict_loss_count"]) >= 4
        and int(removed_stats["win_count"]) <= 1
        and loss_precision >= 80.0
    )
    economic_survivor = bool(
        float(remaining_stats["net_return_pct_sum"]) > 0.0
        and _finite(remaining_pf)
        and float(remaining_pf) > 1.0
    )

    return {
        "dimension": "+".join(fields),
        "group": "|".join(values),
        "removed": removed_stats,
        "remaining": remaining_stats,
        "net_return_improvement_pct": float(remaining_stats["net_return_pct_sum"]) - float(overall["net_return_pct_sum"]),
        "net_pf_improvement": pf_delta,
        "win_rate_delta_pct_point": (
            float(remaining_stats["win_rate_pct"]) - float(overall["win_rate_pct"])
            if remaining_stats.get("win_rate_pct") is not None and overall.get("win_rate_pct") is not None
            else None
        ),
        "winner_contamination_count": int(removed_stats["win_count"]),
        "losses_removed_count": int(removed_stats["strict_loss_count"]),
        "loss_precision_pct": loss_precision,
        "removed_symbol_count": len({str(trade.get("symbol")) for trade in removed}),
        "remaining_positive_symbol_count": _positive_symbol_count(remaining),
        "high_precision_preentry_candidate": high_precision,
        "economic_survivor_candidate": economic_survivor,
    }


def _preentry_candidates(
    all_trades: Sequence[Mapping[str, Any]],
    target: Sequence[Mapping[str, Any]],
    overall: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    single_fields = (
        "symbol",
        "entry_origin",
        "trigger_overlap_signature",
        "confluence_signature",
        "structure_valid",
        "confluence_count_bucket",
        "dema_distance_atr_bucket",
        "dema_distance_pct_bucket",
        "next_open_gap_bucket",
        "rsi_strength_bucket",
        "stop_distance_bucket",
    )
    pair_fields = (
        ("symbol", "entry_origin"),
        ("symbol", "confluence_signature"),
        ("symbol", "dema_distance_atr_bucket"),
        ("entry_origin", "confluence_signature"),
        ("entry_origin", "dema_distance_atr_bucket"),
        ("entry_origin", "next_open_gap_bucket"),
        ("entry_origin", "rsi_strength_bucket"),
        ("trigger_overlap_signature", "confluence_signature"),
        ("trigger_overlap_signature", "dema_distance_atr_bucket"),
        ("confluence_signature", "dema_distance_atr_bucket"),
        ("confluence_signature", "next_open_gap_bucket"),
        ("confluence_signature", "rsi_strength_bucket"),
        ("structure_valid", "confluence_signature"),
        ("structure_valid", "dema_distance_atr_bucket"),
        ("dema_distance_atr_bucket", "next_open_gap_bucket"),
        ("dema_distance_atr_bucket", "rsi_strength_bucket"),
    )

    candidates: List[Dict[str, Any]] = []
    for field in single_fields:
        values = sorted({str(trade.get(field, "UNKNOWN")) for trade in target})
        if len(values) <= 1:
            continue
        for value in values:
            row = _candidate(all_trades, target, (field,), (value,), overall)
            if row is not None:
                candidates.append(row)

    for fields in pair_fields:
        values_set = sorted(
            {
                tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
                for trade in target
            }
        )
        if len(values_set) <= 1:
            continue
        for values in values_set:
            row = _candidate(all_trades, target, fields, values, overall)
            if row is not None:
                candidates.append(row)

    candidates.sort(
        key=lambda row: (
            -int(bool(row["economic_survivor_candidate"])),
            -int(bool(row["high_precision_preentry_candidate"])),
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
            "Read-only deep decomposition of the exact counter_trend_break_up confirmation group. "
            "Only pre-entry fields are eligible for removal candidates; MFE/MAE/hold are diagnostic only."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(parent.source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    baseline_dir = root / "runtime" / parent.candidate_source.BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(parent.source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    all_trades: List[Dict[str, Any]] = []
    per_symbol: List[Dict[str, Any]] = []
    blockers: List[str] = []
    all_fixed = True

    for symbol in symbols:
        try:
            frame = parent.shared._load_frame(baseline_dir / f"{symbol.lower()}_15m.csv")
            replay, lock_audit = parent.candidate_source._fixed_point_candidate(
                frame,
                symbol=symbol,
                timeframe=parent.source.INTERVAL,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            enriched = [
                _enrich_deep(trade)
                for trade in replay.get("trades", [])
                if isinstance(trade, Mapping)
            ]
            all_trades.extend(enriched)
            all_fixed = all_fixed and bool(lock_audit.get("fixed_point"))
            per_symbol.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "trade_stats": parent._stats(enriched),
                    "target_stats": parent._stats(
                        [trade for trade in enriched if trade.get("confirmation_signature") == TARGET_CONFIRMATION_SIGNATURE]
                    ),
                    "lock_audit": lock_audit,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            per_symbol.append({"symbol": symbol, "status": "HOLD", "error": error})

    overall = parent._stats(all_trades)
    target = [
        trade
        for trade in all_trades
        if str(trade.get("confirmation_signature")) == TARGET_CONFIRMATION_SIGNATURE
    ]
    target_stats = parent._stats(target)

    target_keys = {_trade_key(trade) for trade in target}
    broad_remaining = [trade for trade in all_trades if _trade_key(trade) not in target_keys]
    broad_reference = {
        "removed": target_stats,
        "remaining": parent._stats(broad_remaining),
        "not_patch_authority": True,
    }

    preentry_fields = (
        "symbol",
        "entry_origin",
        "trigger_overlap_signature",
        "confluence_signature",
        "structure_valid",
        "confluence_count_bucket",
        "dema_distance_atr_bucket",
        "dema_distance_pct_bucket",
        "next_open_gap_bucket",
        "rsi_strength_bucket",
        "stop_distance_bucket",
    )
    postentry_fields = ("exit_reason", "mfe_bucket", "mae_bucket", "hold_bucket")
    preentry_groups = {field: _group(target, (field,)) for field in preentry_fields}
    postentry_diagnostics = {field: _group(target, (field,)) for field in postentry_fields}
    candidates = _preentry_candidates(all_trades, target, overall)
    high_precision = [row for row in candidates if bool(row["high_precision_preentry_candidate"])]
    economic_survivors = [row for row in high_precision if bool(row["economic_survivor_candidate"])]

    data_pass = bool(
        len(per_symbol) == len(symbols)
        and not blockers
        and all_fixed
        and int(overall["trade_count"]) == 227
        and int(target_stats["trade_count"]) == 23
        and int(target_stats["win_count"]) == 4
        and int(target_stats["strict_loss_count"]) == 19
    )
    state = (
        "PASS_R7A4D_COUNTER_BREAK_UP_DEEP_ANATOMY"
        if data_pass
        else "HOLD_R7A4D_COUNTER_BREAK_UP_SCOPE_OR_REPLAY_PARITY_FAIL"
    )
    next_stage = (
        "SELECT_ONE_PREENTRY_SUBCLUSTER_AND_RUN_EXACT_REMOVAL_OOS"
        if data_pass and economic_survivors
        else "REVIEW_HIGH_PRECISION_PREENTRY_SUBCLUSTERS_WITHOUT_PATCHING"
        if data_pass and high_precision
        else "REJECT_SUBCLUSTER_FILTER_PATH_OR_REVIEW_BROAD_BLOCK_REFERENCE"
        if data_pass
        else "REPAIR_227_67_160_REPLAY_PARITY_ONLY"
    )

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_STRATEGY_MUTATION",
        "analysis_id": ANALYSIS_ID,
        "target_sha": args.target_sha,
        "target_confirmation_signature": TARGET_CONFIRMATION_SIGNATURE,
        "all_trade_stats": overall,
        "target_trade_stats": target_stats,
        "broad_target_removal_reference": broad_reference,
        "per_symbol": per_symbol,
        "preentry_group_stats": preentry_groups,
        "postentry_diagnostics_not_entry_filters": postentry_diagnostics,
        "top_preentry_removal_candidates": candidates[:TOP_LIMIT],
        "high_precision_preentry_candidates": high_precision[:TOP_LIMIT],
        "economic_survivor_candidates": economic_survivors[:TOP_LIMIT],
        "blockers": blockers,
        "next_stage": next_stage,
    }
    parent.source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={sum(1 for row in per_symbol if row.get('status') == 'PASS')}/{len(symbols)}")
    print(f"ALL_TRADES={overall['trade_count']}")
    print(f"ALL_WINS={overall['win_count']}")
    print(f"ALL_STRICT_LOSSES={overall['strict_loss_count']}")
    print(f"TARGET_TRADES={target_stats['trade_count']}")
    print(f"TARGET_WINS={target_stats['win_count']}")
    print(f"TARGET_STRICT_LOSSES={target_stats['strict_loss_count']}")
    print(f"TARGET_NET_RETURN_PCT_SUM={float(target_stats['net_return_pct_sum']):.6f}")
    print("BROAD_TARGET_REMOVAL_REFERENCE=" + json.dumps(broad_reference, ensure_ascii=False, sort_keys=True))
    print("TOP_PREENTRY_REMOVAL_CANDIDATES=" + json.dumps(candidates[:12], ensure_ascii=False, sort_keys=True))
    print("HIGH_PRECISION_PREENTRY_CANDIDATES=" + json.dumps(high_precision[:12], ensure_ascii=False, sort_keys=True))
    print("ECONOMIC_SURVIVOR_CANDIDATES=" + json.dumps(economic_survivors[:12], ensure_ascii=False, sort_keys=True))
    print("POSTENTRY_DIAGNOSTICS=" + json.dumps(postentry_diagnostics, ensure_ascii=False, sort_keys=True))
    print(f"OUTPUT={output_dir / 'summary_v1.json'}")
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False, sort_keys=True))
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
