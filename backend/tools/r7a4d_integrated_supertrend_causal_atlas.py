from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import r7a4d_integrated_supertrend_entry_origin_anatomy as parent

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_causal_atlas_v1"
ANALYSIS_ID = "full_160_loss_matched_winner_causal_atlas_v1"
TOP_LIMIT = 30
MIN_MATCHED_WINNERS = 3


PREENTRY_NUMERIC_FIELDS = (
    "trend_dema_distance_atr",
    "trend_dema_distance_pct",
    "favorable_next_open_gap_pct",
    "rsi_trend_strength",
    "initial_stop_distance_pct",
    "confluence_count",
)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _num(value: Any) -> Optional[float]:
    return float(value) if _finite(value) else None


def _mean(values: Iterable[Any]) -> Optional[float]:
    materialized = [float(value) for value in values if _finite(value)]
    return sum(materialized) / len(materialized) if materialized else None


def _quantile(values: Iterable[Any], fraction: float) -> Optional[float]:
    materialized = sorted(float(value) for value in values if _finite(value))
    if not materialized:
        return None
    if len(materialized) == 1:
        return materialized[0]
    position = (len(materialized) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return materialized[lower]
    weight = position - lower
    return materialized[lower] * (1.0 - weight) + materialized[upper] * weight


def _bucket(value: Any, cuts: Sequence[float], labels: Sequence[str]) -> str:
    number = _num(value)
    if number is None:
        return "UNKNOWN"
    for cut, label in zip(cuts, labels):
        if number <= cut:
            return label
    return labels[-1]


def _signed_for_side(value: Any, side: str) -> Optional[float]:
    number = _num(value)
    if number is None:
        return None
    return number if str(side).lower() == "long" else -number


def _trade_key(trade: Mapping[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        str(trade.get("symbol", "UNKNOWN")),
        str(trade.get("side", "UNKNOWN")),
        str(trade.get("entry_ts", "UNKNOWN")),
        str(trade.get("entry_bar", "UNKNOWN")),
        str(trade.get("exit_bar", "UNKNOWN")),
    )


def _path_failure(item: Mapping[str, Any]) -> Tuple[str, str]:
    cost = max(float(item.get("round_trip_cost_pct", 0.0)), 0.0)
    gross = float(item.get("gross_return_pct", 0.0))
    mfe = max(float(item.get("mfe_pct", 0.0)), 0.0)
    hold = int(item.get("hold_bars", 0) or 0)
    giveback = max(float(item.get("giveback_from_mfe_pct", 0.0)), 0.0)
    exit_reason = str(item.get("exit_reason", "UNKNOWN"))

    if bool(item.get("invalid_initial_stop")):
        return "ENTRY_CONTRACT_FAILURE", "INVALID_INITIAL_STOP"
    if gross > 0.0 and gross <= cost:
        return "COST_FAILURE", "GROSS_WIN_NET_LOSS"
    if mfe <= cost + 1e-12:
        return "ENTRY_QUALITY_FAILURE", "NO_EDGE_COST_UNRECOVERED"
    if hold <= 3 and mfe <= max(cost * 2.0, 0.25):
        return "ENTRY_QUALITY_FAILURE", "EARLY_NO_EDGE"

    capture_50 = 0.50 * mfe - cost
    if capture_50 > 0.0:
        if exit_reason == "SUPERTREND_TRAILING_STOP":
            return "EXIT_CAPTURE_FAILURE", "TRAILING_STOP_GIVEBACK"
        if exit_reason == "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN":
            return "EXIT_CAPTURE_FAILURE", "OPPOSITE_FLIP_GIVEBACK"
        if giveback >= max(0.25, 0.50 * mfe):
            return "EXIT_CAPTURE_FAILURE", "PROFIT_GIVEBACK_OTHER"
        return "EXIT_CAPTURE_FAILURE", "EDGE_NOT_CAPTURED"

    if exit_reason == "SUPERTREND_TRAILING_STOP":
        return "MIXED_FAILURE", "TRAILING_STOP_BEFORE_BREAKEVEN"
    if exit_reason == "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN":
        return "MIXED_FAILURE", "OPPOSITE_FLIP_BEFORE_BREAKEVEN"
    return "MIXED_FAILURE", "UNRESOLVED_LOSS_PATH"


def _enrich(trade: Mapping[str, Any]) -> Dict[str, Any]:
    item = parent._enrich(trade)
    context = item.get("entry_context") if isinstance(item.get("entry_context"), Mapping) else {}
    side = str(item.get("side", "UNKNOWN"))

    dema_atr = _signed_for_side(context.get("dema_distance_atr"), side)
    dema_pct = _signed_for_side(context.get("dema_distance_pct"), side)
    next_gap = _signed_for_side(context.get("next_open_gap_pct"), side)
    rsi14 = _num(context.get("rsi14"))
    rsi_strength = None
    if rsi14 is not None:
        rsi_strength = rsi14 - 50.0 if side.lower() == "long" else 50.0 - rsi14

    confluence_count = _num(context.get("confluence_count"))
    stop_distance = _num(item.get("initial_stop_distance_pct"))
    mfe = max(float(item.get("mfe_pct", 0.0)), 0.0)
    cost = max(float(item.get("round_trip_cost_pct", 0.0)), 0.0)
    net = float(item.get("net_return_pct", 0.0))
    lane, failure_class = _path_failure(item)

    capture_rows: Dict[str, Any] = {}
    for label, fraction in (("25", 0.25), ("50", 0.50), ("75", 0.75)):
        hypothetical = fraction * mfe - cost
        capture_rows[f"oracle_net_at_{label}pct_mfe"] = hypothetical
        capture_rows[f"convertible_at_{label}pct_mfe"] = bool(net <= 0.0 and hypothetical > 0.0)

    breakeven_fraction = None
    if mfe > 0.0:
        breakeven_fraction = cost / mfe

    item.update(
        {
            "trade_key": "|".join(_trade_key(item)),
            "trend_dema_distance_atr": dema_atr,
            "trend_dema_distance_pct": dema_pct,
            "favorable_next_open_gap_pct": next_gap,
            "rsi_trend_strength": rsi_strength,
            "confluence_count": int(confluence_count) if confluence_count is not None else None,
            "initial_stop_distance_pct": stop_distance,
            "dema_distance_atr_bucket": _bucket(
                dema_atr,
                (0.0, 0.25, 0.50, 1.00, float("inf")),
                ("LE_0", "0_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "GT_1_00"),
            ),
            "dema_distance_pct_bucket": _bucket(
                dema_pct,
                (0.0, 0.10, 0.25, 0.50, float("inf")),
                ("LE_0", "0_TO_0_10", "0_10_TO_0_25", "0_25_TO_0_50", "GT_0_50"),
            ),
            "next_open_gap_bucket": _bucket(
                next_gap,
                (-0.10, 0.0, 0.05, 0.15, float("inf")),
                (
                    "ADVERSE_GT_0_10",
                    "ADVERSE_TO_FLAT",
                    "FAVORABLE_0_TO_0_05",
                    "FAVORABLE_0_05_TO_0_15",
                    "FAVORABLE_GT_0_15",
                ),
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
                if confluence_count is None
                else "0"
                if int(confluence_count) <= 0
                else "1"
                if int(confluence_count) == 1
                else "2"
                if int(confluence_count) == 2
                else "3_PLUS"
            ),
            "causal_lane": lane,
            "path_failure_class": failure_class,
            "minimum_mfe_capture_fraction_to_breakeven": breakeven_fraction,
            "conservative_path_known": bool(
                not item.get("intrabar_path_unknown") and int(item.get("hold_bars", 0) or 0) > 1
            ),
            **capture_rows,
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
        stats = parent._stats(bucket)
        row = {
            "dimension": "+".join(fields),
            "group": "|".join(key),
            **stats,
        }
        if all(float(trade.get("net_return_pct", 0.0)) <= 0.0 for trade in bucket):
            row.update(_exit_upper_bound(bucket))
        rows.append(row)
    rows.sort(
        key=lambda row: (
            float(row["net_return_pct_sum"]),
            -int(row["strict_loss_count"]),
            int(row["win_count"]),
            str(row["group"]),
        )
    )
    return rows


def _exit_upper_bound(losses: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    current = sum(float(trade.get("net_return_pct", 0.0)) for trade in losses)
    for label in ("25", "50", "75"):
        field = f"oracle_net_at_{label}pct_mfe"
        hypothetical = sum(float(trade.get(field, 0.0)) for trade in losses)
        converted = sum(bool(trade.get(f"convertible_at_{label}pct_mfe")) for trade in losses)
        conservative = sum(
            bool(trade.get(f"convertible_at_{label}pct_mfe"))
            and bool(trade.get("conservative_path_known"))
            for trade in losses
        )
        result[f"oracle_{label}pct_mfe_net_sum"] = hypothetical
        result[f"oracle_{label}pct_mfe_improvement"] = hypothetical - current
        result[f"convertible_count_at_{label}pct_mfe"] = converted
        result[f"conservative_convertible_count_at_{label}pct_mfe"] = conservative
    return result


def _winner_indexes(wins: Sequence[Mapping[str, Any]]) -> List[Tuple[str, Tuple[str, ...], Dict[Tuple[str, ...], List[Mapping[str, Any]]]]]:
    specs = (
        (
            "EXACT",
            (
                "symbol",
                "side",
                "entry_origin",
                "trigger_signature",
                "confirmation_signature",
                "confluence_signature",
            ),
        ),
        (
            "NO_SYMBOL",
            (
                "side",
                "entry_origin",
                "trigger_signature",
                "confirmation_signature",
                "confluence_signature",
            ),
        ),
        (
            "CONFIRMATION_FAMILY",
            ("side", "entry_origin", "confirmation_family", "confluence_signature"),
        ),
        ("ENTRY_ORIGIN", ("side", "entry_origin")),
        ("SIDE_ONLY", ("side",)),
    )
    output = []
    for name, fields in specs:
        index: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
        for trade in wins:
            key = tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
            index[key].append(trade)
        output.append((name, fields, index))
    return output


def _matched_winner_contrast(
    loss: Mapping[str, Any],
    indexes: Sequence[Tuple[str, Tuple[str, ...], Dict[Tuple[str, ...], List[Mapping[str, Any]]]]],
) -> Dict[str, Any]:
    selected_name = "UNMATCHED"
    selected_fields: Tuple[str, ...] = tuple()
    cohort: List[Mapping[str, Any]] = []

    fallback: Optional[Tuple[str, Tuple[str, ...], List[Mapping[str, Any]]]] = None
    for name, fields, index in indexes:
        key = tuple(str(loss.get(field, "UNKNOWN")) for field in fields)
        candidates = list(index.get(key, []))
        if candidates and fallback is None:
            fallback = (name, fields, candidates)
        if len(candidates) >= MIN_MATCHED_WINNERS:
            selected_name, selected_fields, cohort = name, fields, candidates
            break
    if not cohort and fallback is not None:
        selected_name, selected_fields, cohort = fallback

    profile: Dict[str, Any] = {}
    deviations: List[str] = []
    for field in PREENTRY_NUMERIC_FIELDS:
        values = [trade.get(field) for trade in cohort]
        q10 = _quantile(values, 0.10)
        q50 = _quantile(values, 0.50)
        q90 = _quantile(values, 0.90)
        profile[field] = {"p10": q10, "median": q50, "p90": q90}
        value = _num(loss.get(field))
        if value is None or q10 is None or q90 is None:
            continue
        if value < q10:
            deviations.append(f"{field}:BELOW_WIN_P10")
        elif value > q90:
            deviations.append(f"{field}:ABOVE_WIN_P90")

    return {
        "match_level": selected_name,
        "match_fields": list(selected_fields),
        "matched_winner_count": len(cohort),
        "matched_winner_profile": profile,
        "preentry_deviation_flags": deviations,
    }


def _filter_candidate(
    trades: Sequence[Mapping[str, Any]],
    overall: Mapping[str, Any],
    fields: Sequence[str],
    values: Sequence[str],
) -> Optional[Dict[str, Any]]:
    removed = [
        trade
        for trade in trades
        if all(str(trade.get(field, "UNKNOWN")) == value for field, value in zip(fields, values))
    ]
    if not removed or len(removed) == len(trades):
        return None
    removed_stats = parent._stats(removed)
    if float(removed_stats["net_return_pct_sum"]) >= 0.0:
        return None
    remaining = [trade for trade in trades if trade not in removed]
    remaining_stats = parent._stats(remaining)
    precision = (
        float(removed_stats["strict_loss_count"]) / float(removed_stats["trade_count"]) * 100.0
        if int(removed_stats["trade_count"]) > 0
        else 0.0
    )
    high_precision = bool(
        int(removed_stats["strict_loss_count"]) >= 8
        and int(removed_stats["win_count"]) <= 1
        and precision >= 85.0
    )
    economic_survivor = bool(
        float(remaining_stats["net_return_pct_sum"]) > 0.0
        and _finite(remaining_stats.get("net_profit_factor"))
        and float(remaining_stats["net_profit_factor"]) > 1.0
    )
    return {
        "dimension": "+".join(fields),
        "group": "|".join(values),
        "removed": removed_stats,
        "remaining": remaining_stats,
        "loss_precision_pct": precision,
        "winner_contamination_count": int(removed_stats["win_count"]),
        "losses_removed_count": int(removed_stats["strict_loss_count"]),
        "net_return_improvement_pct": (
            float(remaining_stats["net_return_pct_sum"]) - float(overall["net_return_pct_sum"])
        ),
        "win_rate_delta_pct_point": (
            float(remaining_stats["win_rate_pct"]) - float(overall["win_rate_pct"])
            if remaining_stats.get("win_rate_pct") is not None and overall.get("win_rate_pct") is not None
            else None
        ),
        "high_precision_preentry_candidate": high_precision,
        "economic_survivor_candidate": economic_survivor,
    }


def _preentry_candidates(
    trades: Sequence[Mapping[str, Any]], overall: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    single_fields = (
        "symbol",
        "side",
        "entry_origin",
        "trigger_signature",
        "confirmation_signature",
        "confirmation_family",
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
        ("entry_origin", "confirmation_signature"),
        ("entry_origin", "confluence_signature"),
        ("entry_origin", "dema_distance_atr_bucket"),
        ("entry_origin", "next_open_gap_bucket"),
        ("confirmation_signature", "confluence_signature"),
        ("confirmation_signature", "dema_distance_atr_bucket"),
        ("confirmation_signature", "next_open_gap_bucket"),
        ("confirmation_family", "confluence_signature"),
        ("confluence_signature", "dema_distance_atr_bucket"),
        ("confluence_signature", "next_open_gap_bucket"),
        ("dema_distance_atr_bucket", "next_open_gap_bucket"),
        ("rsi_strength_bucket", "next_open_gap_bucket"),
        ("symbol", "confirmation_signature"),
        ("symbol", "entry_origin"),
    )

    candidates: List[Dict[str, Any]] = []
    for field in single_fields:
        for value in sorted({str(trade.get(field, "UNKNOWN")) for trade in trades}):
            row = _filter_candidate(trades, overall, (field,), (value,))
            if row is not None:
                candidates.append(row)
    for fields in pair_fields:
        values_set = sorted(
            {
                tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
                for trade in trades
            }
        )
        for values in values_set:
            row = _filter_candidate(trades, overall, fields, values)
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


def _deviation_summary(loss_records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    matched = 0
    for loss in loss_records:
        contrast = loss.get("matched_winner_contrast")
        if not isinstance(contrast, Mapping):
            continue
        if int(contrast.get("matched_winner_count", 0)) > 0:
            matched += 1
        for flag in contrast.get("preentry_deviation_flags", []):
            counts[str(flag)] += 1
    rows = [
        {
            "flag": flag,
            "loss_count": count,
            "pct_of_all_losses": count / len(loss_records) * 100.0 if loss_records else 0.0,
            "pct_of_matched_losses": count / matched * 100.0 if matched else 0.0,
        }
        for flag, count in counts.items()
    ]
    rows.sort(key=lambda row: (-int(row["loss_count"]), str(row["flag"])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only causal atlas for all losing trades in the failed 227-trade arm. "
            "Separates entry-quality failures from exit-capture failures and contrasts each loss "
            "against matched winners using pre-entry information only."
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
        dict.fromkeys(
            parent.source.norm_symbol(item)
            for item in args.symbols.split(",")
            if item.strip()
        )
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
            trades = [
                _enrich(trade)
                for trade in replay.get("trades", [])
                if isinstance(trade, Mapping)
            ]
            all_trades.extend(trades)
            all_fixed = all_fixed and bool(lock_audit.get("fixed_point"))
            per_symbol.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "trade_stats": parent._stats(trades),
                    "loss_lane_stats": _group(
                        [trade for trade in trades if float(trade.get("net_return_pct", 0.0)) <= 0.0],
                        ("causal_lane",),
                    ),
                    "lock_audit": lock_audit,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            per_symbol.append({"symbol": symbol, "status": "HOLD", "error": error})

    overall = parent._stats(all_trades)
    wins = [trade for trade in all_trades if float(trade.get("net_return_pct", 0.0)) > 0.0]
    losses = [trade for trade in all_trades if float(trade.get("net_return_pct", 0.0)) <= 0.0]
    indexes = _winner_indexes(wins)

    loss_records: List[Dict[str, Any]] = []
    for loss in losses:
        record = dict(loss)
        record["matched_winner_contrast"] = _matched_winner_contrast(loss, indexes)
        loss_records.append(record)

    loss_lane_stats = _group(loss_records, ("causal_lane",))
    path_failure_stats = _group(loss_records, ("path_failure_class",))
    exit_reason_stats = _group(loss_records, ("exit_reason",))
    origin_failure_stats = _group(loss_records, ("entry_origin", "causal_lane"))
    confirmation_failure_stats = _group(
        loss_records,
        ("confirmation_signature", "causal_lane"),
    )
    deviation_summary = _deviation_summary(loss_records)
    preentry_candidates = _preentry_candidates(all_trades, overall)
    high_precision = [
        row for row in preentry_candidates if bool(row["high_precision_preentry_candidate"])
    ]
    economic_survivors = [
        row for row in preentry_candidates if bool(row["economic_survivor_candidate"])
    ]

    matched_coverage: Dict[str, int] = defaultdict(int)
    for record in loss_records:
        contrast = record.get("matched_winner_contrast", {})
        matched_coverage[str(contrast.get("match_level", "UNMATCHED"))] += 1

    overall_exit_upper_bound = _exit_upper_bound(loss_records)
    exit_repair_groups = sorted(
        path_failure_stats + exit_reason_stats + origin_failure_stats + confirmation_failure_stats,
        key=lambda row: (
            -float(row.get("oracle_50pct_mfe_improvement", 0.0)),
            -int(row.get("convertible_count_at_50pct_mfe", 0)),
            str(row.get("dimension")),
            str(row.get("group")),
        ),
    )

    data_pass = bool(
        len(per_symbol) == len(symbols)
        and not blockers
        and all_fixed
        and int(overall["trade_count"]) > 0
        and len(loss_records) == int(overall["loss_count"])
    )
    state = (
        "PASS_R7A4D_FULL_LOSS_CAUSAL_ATLAS"
        if data_pass
        else "HOLD_R7A4D_CAUSAL_ATLAS_DATA_FAIL"
    )
    next_stage = (
        "VALIDATE_ONE_ECONOMIC_SURVIVOR_PREENTRY_FILTER"
        if data_pass and economic_survivors
        else "VALIDATE_ONE_HIGH_PRECISION_PREENTRY_FILTER"
        if data_pass and high_precision
        else "DESIGN_ONE_CONSERVATIVE_EXIT_REPLAY_FROM_CAUSAL_ATLAS"
        if data_pass and int(overall_exit_upper_bound.get("convertible_count_at_50pct_mfe", 0)) > 0
        else "REFINE_MATCHED_WIN_LOSS_CONTRAST"
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
        "symbols": symbols,
        "interval": parent.source.INTERVAL,
        "cost_bps_per_side": args.cost_bps_per_side,
        "source_directory": str(baseline_dir),
        "output_directory": str(output_dir),
        "all_symbols_fixed_point": all_fixed,
        "overall": overall,
        "winner_count": len(wins),
        "loss_record_count": len(loss_records),
        "matched_winner_coverage": dict(sorted(matched_coverage.items())),
        "overall_exit_conversion_upper_bound": overall_exit_upper_bound,
        "loss_lane_stats": loss_lane_stats,
        "path_failure_stats": path_failure_stats,
        "exit_reason_stats": exit_reason_stats,
        "origin_failure_stats": origin_failure_stats,
        "confirmation_failure_stats": confirmation_failure_stats,
        "matched_winner_deviation_summary": deviation_summary,
        "top_preentry_filter_candidates": preentry_candidates[:TOP_LIMIT],
        "high_precision_preentry_candidates": high_precision[:TOP_LIMIT],
        "economic_survivor_preentry_candidates": economic_survivors[:TOP_LIMIT],
        "top_exit_repair_oracle_groups": exit_repair_groups[:TOP_LIMIT],
        "loss_records": loss_records,
        "per_symbol": per_symbol,
        "blockers": blockers,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    parent.source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={sum(row.get('status') == 'PASS' for row in per_symbol)}/{len(symbols)}")
    print(f"TRADES={overall['trade_count']}")
    print(f"WINS={overall['win_count']}")
    print(f"LOSSES={overall['loss_count']}")
    print(f"WIN_RATE_PCT={overall['win_rate_pct']}")
    print(f"NET_RETURN_PCT_SUM={overall['net_return_pct_sum']:.6f}")
    print(f"NET_PF={overall['net_profit_factor']}")
    print(f"PAYOFF_RATIO_PCT={overall['payoff_ratio_pct']}")
    print(f"MATCHED_WINNER_COVERAGE={json.dumps(dict(sorted(matched_coverage.items())), ensure_ascii=False, sort_keys=True)}")
    print(f"LOSS_LANE_STATS={json.dumps(loss_lane_stats, ensure_ascii=False, sort_keys=True)}")
    print(f"PATH_FAILURE_STATS={json.dumps(path_failure_stats, ensure_ascii=False, sort_keys=True)}")
    print(f"EXIT_CONVERSION_UPPER_BOUND={json.dumps(overall_exit_upper_bound, ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_PREENTRY_FILTERS={json.dumps(preentry_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_EXIT_REPAIR_GROUPS={json.dumps(exit_repair_groups[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_MATCHED_WIN_DEVIATIONS={json.dumps(deviation_summary[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"HIGH_PRECISION_PREENTRY_COUNT={len(high_precision)}")
    print(f"ECONOMIC_SURVIVOR_PREENTRY_COUNT={len(economic_survivors)}")
    print(f"OUTPUT={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
