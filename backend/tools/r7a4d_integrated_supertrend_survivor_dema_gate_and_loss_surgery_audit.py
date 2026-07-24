from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_causal_atlas as atlas
import r7a4d_integrated_supertrend_entry_origin_anatomy as anatomy
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_survivor_dema_gate_and_loss_surgery_audit_v1"
BASELINE_DIRNAME = survivor_filter.BASELINE_DIRNAME
POLICY_ID = "frozen_survivor_plus_side_adjusted_dema_distance_atr_0_50_to_1_00_reject_v1"
DEMA_ATR_LOWER_EXCLUSIVE = 0.50
DEMA_ATR_UPPER_INCLUSIVE = 1.00
REFERENCE_ATLAS_LOSSES = 30
TOP_LIMIT = 30


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _mean(values: Iterable[Any]) -> Optional[float]:
    materialized = [float(value) for value in values if _finite(value)]
    return sum(materialized) / len(materialized) if materialized else None


def _side_adjusted(value: Any, side: str) -> Optional[float]:
    if not _finite(value):
        return None
    number = float(value)
    return number if str(side) == baseline.LONG else -number


def _trade_signature(trade: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        str(trade.get("symbol")),
        str(trade.get("side")),
        int(trade.get("entry_bar", -1)),
        int(trade.get("exit_bar", -1)),
        str(trade.get("exit_reason")),
        round(float(trade.get("entry_price", 0.0)), 12),
        round(float(trade.get("exit_price", 0.0)), 12),
        round(float(trade.get("net_return_pct", 0.0)), 12),
    )


def _parity(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    left_trades = [
        _trade_signature(trade)
        for trade in left.get("trades", [])
        if isinstance(trade, Mapping)
    ]
    right_trades = [
        _trade_signature(trade)
        for trade in right.get("trades", [])
        if isinstance(trade, Mapping)
    ]
    checks = {
        "trade_count": int(left.get("trade_count", -1)) == int(right.get("trade_count", -2)),
        "win_count": int(left.get("win_count", -1)) == int(right.get("win_count", -2)),
        "net_return_pct": abs(float(left.get("net_return_pct", 0.0)) - float(right.get("net_return_pct", 0.0))) <= 1e-10,
        "net_profit_factor": (
            left.get("net_profit_factor") == right.get("net_profit_factor")
            if not (_finite(left.get("net_profit_factor")) and _finite(right.get("net_profit_factor")))
            else abs(float(left["net_profit_factor"]) - float(right["net_profit_factor"])) <= 1e-10
        ),
        "trade_sequence": left_trades == right_trades,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def _run_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    cost_bps_per_side: float,
    dema_gate_enabled: bool,
) -> Dict[str, Any]:
    original_compute: Callable[..., pd.DataFrame] = baseline.compute_features
    blocked_survivor: List[Dict[str, Any]] = []
    blocked_dema: List[Dict[str, Any]] = []

    def filtered_compute(source_frame: pd.DataFrame, cfg: Any) -> pd.DataFrame:
        features = original_compute(source_frame, cfg).copy()
        for position in range(len(features)):
            for side, signal_column in (
                (baseline.LONG, "long_entry_signal"),
                (baseline.SHORT, "short_entry_signal"),
            ):
                if not bool(features[signal_column].iloc[position]):
                    continue
                context = baseline._signal_context(source_frame, features, position, side)

                if survivor_filter._matches_target_cluster(symbol, context):
                    features.loc[features.index[position], signal_column] = False
                    blocked_survivor.append(
                        {
                            "bar": position,
                            "timestamp": baseline._timestamp(source_frame, position),
                            "symbol": source.norm_symbol(symbol),
                            "side": side,
                            "trigger_signature": context.get("trigger_signature"),
                            "confirmation_signature": context.get("confirmation_signature"),
                            "confluence_signature": context.get("confluence_signature"),
                        }
                    )
                    continue

                if not dema_gate_enabled:
                    continue
                trend_distance = _side_adjusted(context.get("dema_distance_atr"), side)
                if trend_distance is None:
                    continue
                if not (DEMA_ATR_LOWER_EXCLUSIVE < trend_distance <= DEMA_ATR_UPPER_INCLUSIVE):
                    continue

                features.loc[features.index[position], signal_column] = False
                blocked_dema.append(
                    {
                        "bar": position,
                        "timestamp": baseline._timestamp(source_frame, position),
                        "symbol": source.norm_symbol(symbol),
                        "side": side,
                        "trend_dema_distance_atr": trend_distance,
                        "raw_dema_distance_atr": context.get("dema_distance_atr"),
                        "trigger_signature": context.get("trigger_signature"),
                        "confirmation_signature": context.get("confirmation_signature"),
                        "confluence_signature": context.get("confluence_signature"),
                        "rsi14": context.get("rsi14"),
                        "next_open_gap_known_at_signal": False,
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

    replay["replay_profile_id"] = (
        "integrated_supertrend_survivor_dema_gate_replay_v1"
        if dema_gate_enabled
        else "integrated_supertrend_frozen_survivor_copy_replay_v1"
    )
    replay["frozen_survivor_policy_id"] = survivor_filter.POLICY_ID
    replay["dema_gate_enabled"] = bool(dema_gate_enabled)
    replay["dema_gate_policy_id"] = POLICY_ID if dema_gate_enabled else None
    replay["dema_gate_definition"] = {
        "side_adjusted_dema_distance_atr_lower_exclusive": DEMA_ATR_LOWER_EXCLUSIVE,
        "side_adjusted_dema_distance_atr_upper_inclusive": DEMA_ATR_UPPER_INCLUSIVE,
        "decision_time": "confirmed signal bar close",
        "future_data_used": False,
        "source_strategy_mutated": False,
    }
    replay["frozen_survivor_blocked_entry_signal_count"] = len(blocked_survivor)
    replay["frozen_survivor_blocked_entry_signals"] = blocked_survivor
    replay["dema_gate_blocked_entry_signal_count"] = len(blocked_dema)
    replay["dema_gate_blocked_entry_signals"] = blocked_dema
    return replay


def _bucket(value: Any, cuts: Sequence[float], labels: Sequence[str]) -> str:
    if not _finite(value):
        return "UNKNOWN"
    number = float(value)
    for cut, label in zip(cuts, labels):
        if number <= cut:
            return label
    return labels[-1]


def _path_diagnostics(trade: Mapping[str, Any], frame: pd.DataFrame) -> Dict[str, Any]:
    entry_bar = int(trade.get("entry_bar", -1))
    exit_bar = int(trade.get("exit_bar", -1))
    entry_price = float(trade.get("entry_price", 0.0))
    side = str(trade.get("side"))
    cost = max(float(trade.get("round_trip_cost_pct", 0.0)), 0.0)
    stop_distance = float(trade.get("initial_stop_distance_pct", 0.0)) if _finite(trade.get("initial_stop_distance_pct")) else None

    if entry_bar < 0 or exit_bar < entry_bar or exit_bar >= len(frame) or entry_price <= 0.0:
        return {"path_data_valid": False}

    close_rows: List[Dict[str, Any]] = []
    for bar in range(entry_bar, exit_bar + 1):
        close_price = float(frame["close"].iloc[bar])
        gross = (
            (close_price - entry_price) / entry_price * 100.0
            if side == baseline.LONG
            else (entry_price - close_price) / entry_price * 100.0
        )
        close_rows.append(
            {
                "bar": bar,
                "gross_pct": gross,
                "net_pct": gross - cost,
                "r_multiple": gross / stop_distance if stop_distance not in (None, 0.0) else None,
            }
        )

    max_close_gross = max(row["gross_pct"] for row in close_rows)
    max_close_net = max(row["net_pct"] for row in close_rows)
    max_close_r = max(
        (float(row["r_multiple"]) for row in close_rows if _finite(row.get("r_multiple"))),
        default=None,
    )

    def first_threshold(field: str, threshold: float) -> Optional[Dict[str, Any]]:
        for row in close_rows:
            value = row.get(field)
            if _finite(value) and float(value) >= threshold:
                bar = int(row["bar"])
                next_bar = bar + 1
                next_open_net = None
                if next_bar <= exit_bar and next_bar < len(frame):
                    next_open = float(frame["open"].iloc[next_bar])
                    gross = (
                        (next_open - entry_price) / entry_price * 100.0
                        if side == baseline.LONG
                        else (entry_price - next_open) / entry_price * 100.0
                    )
                    next_open_net = gross - cost
                return {
                    "bar": bar,
                    "bars_after_entry": bar - entry_bar,
                    "next_open_net_pct": next_open_net,
                }
        return None

    first_positive_net = first_threshold("net_pct", 0.0)
    first_025r = first_threshold("r_multiple", 0.25)
    first_050r = first_threshold("r_multiple", 0.50)
    first_100r = first_threshold("r_multiple", 1.00)

    return {
        "path_data_valid": True,
        "max_close_gross_pct": max_close_gross,
        "max_close_net_pct": max_close_net,
        "max_close_r": max_close_r,
        "intrabar_mfe_pct": float(trade.get("mfe_pct", 0.0)),
        "intrabar_to_close_mfe_gap_pct": float(trade.get("mfe_pct", 0.0)) - max_close_gross,
        "ever_close_net_positive": max_close_net > 0.0,
        "first_positive_net_close": first_positive_net,
        "convertible_next_open_after_first_positive_close": bool(
            first_positive_net is not None
            and _finite(first_positive_net.get("next_open_net_pct"))
            and float(first_positive_net["next_open_net_pct"]) > 0.0
        ),
        "first_0_25r_close": first_025r,
        "convertible_next_open_after_0_25r_close": bool(
            first_025r is not None
            and _finite(first_025r.get("next_open_net_pct"))
            and float(first_025r["next_open_net_pct"]) > 0.0
        ),
        "first_0_50r_close": first_050r,
        "convertible_next_open_after_0_50r_close": bool(
            first_050r is not None
            and _finite(first_050r.get("next_open_net_pct"))
            and float(first_050r["next_open_net_pct"]) > 0.0
        ),
        "first_1_00r_close": first_100r,
        "convertible_next_open_after_1_00r_close": bool(
            first_100r is not None
            and _finite(first_100r.get("next_open_net_pct"))
            and float(first_100r["next_open_net_pct"]) > 0.0
        ),
    }


def _enrich_with_path(trade: Mapping[str, Any], frame: pd.DataFrame) -> Dict[str, Any]:
    item = atlas._enrich(trade)
    item.update(_path_diagnostics(item, frame))
    item["mfe_bucket"] = _bucket(
        item.get("mfe_pct"),
        (0.08, 0.25, 0.50, 1.00, float("inf")),
        ("LE_COST", "0_08_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "GT_1_00"),
    )
    item["max_close_net_bucket"] = _bucket(
        item.get("max_close_net_pct"),
        (0.0, 0.08, 0.25, 0.50, float("inf")),
        ("LE_0", "0_TO_0_08", "0_08_TO_0_25", "0_25_TO_0_50", "GT_0_50"),
    )
    return item


def _group(trades: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
        buckets[key].append(trade)
    rows: List[Dict[str, Any]] = []
    for key, bucket in buckets.items():
        row = {"dimension": "+".join(fields), "group": "|".join(key), **anatomy._stats(bucket)}
        row.update(
            {
                "ever_close_net_positive_count": sum(bool(item.get("ever_close_net_positive")) for item in bucket),
                "next_open_positive_conversion_count": sum(
                    bool(item.get("convertible_next_open_after_first_positive_close")) for item in bucket
                ),
                "next_open_0_25r_conversion_count": sum(
                    bool(item.get("convertible_next_open_after_0_25r_close")) for item in bucket
                ),
                "next_open_0_50r_conversion_count": sum(
                    bool(item.get("convertible_next_open_after_0_50r_close")) for item in bucket
                ),
                "next_open_1_00r_conversion_count": sum(
                    bool(item.get("convertible_next_open_after_1_00r_close")) for item in bucket
                ),
                "mean_max_close_net_pct": _mean(item.get("max_close_net_pct") for item in bucket),
                "mean_intrabar_to_close_mfe_gap_pct": _mean(
                    item.get("intrabar_to_close_mfe_gap_pct") for item in bucket
                ),
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            float(row["net_return_pct_sum"]),
            -int(row["strict_loss_count"]),
            str(row["group"]),
        )
    )
    return rows


def _exit_path_summary(losses: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "loss_count": len(losses),
        "ever_close_net_positive_count": sum(bool(item.get("ever_close_net_positive")) for item in losses),
        "intrabar_only_edge_count": sum(
            float(item.get("mfe_pct", 0.0)) > float(item.get("round_trip_cost_pct", 0.0))
            and not bool(item.get("ever_close_net_positive"))
            for item in losses
        ),
        "next_open_positive_conversion_count": sum(
            bool(item.get("convertible_next_open_after_first_positive_close")) for item in losses
        ),
        "next_open_0_25r_conversion_count": sum(
            bool(item.get("convertible_next_open_after_0_25r_close")) for item in losses
        ),
        "next_open_0_50r_conversion_count": sum(
            bool(item.get("convertible_next_open_after_0_50r_close")) for item in losses
        ),
        "next_open_1_00r_conversion_count": sum(
            bool(item.get("convertible_next_open_after_1_00r_close")) for item in losses
        ),
        "mean_intrabar_mfe_pct": _mean(item.get("mfe_pct") for item in losses),
        "mean_max_close_net_pct": _mean(item.get("max_close_net_pct") for item in losses),
        "mean_intrabar_to_close_mfe_gap_pct": _mean(
            item.get("intrabar_to_close_mfe_gap_pct") for item in losses
        ),
        "diagnostic_only_no_replay_authority": True,
    }


def _payoff_ratio(replays: Sequence[Mapping[str, Any]]) -> Optional[float]:
    trades = [
        trade
        for replay in replays
        for trade in replay.get("trades", [])
        if isinstance(trade, Mapping)
    ]
    return anatomy._stats(trades).get("payoff_ratio_pct")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validation of one DEMA-distance entry gate on the frozen LINKUSDT survivor, "
            "followed by a deeper causal surgery atlas of the remaining entry-quality and exit-capture losses."
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
    baseline_dir = root / "runtime" / BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    survivor_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    frame_by_symbol: Dict[str, pd.DataFrame] = {}
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_dema_blocked = 0
    total_survivor_blocked = 0

    for symbol in symbols:
        try:
            frame = shared._load_frame(baseline_dir / f"{symbol.lower()}_15m.csv")
            frame_by_symbol[symbol] = frame
            frozen_reference = survivor_filter._run_filtered_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FROZEN_SURVIVOR_REFERENCE",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            frozen_copy = _run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FROZEN_SURVIVOR_COPY_PARITY",
                cost_bps_per_side=args.cost_bps_per_side,
                dema_gate_enabled=False,
            )
            parity = _parity(frozen_reference, frozen_copy)
            if parity["status"] != "PASS":
                raise RuntimeError(f"FROZEN_SURVIVOR_PARITY_FAILED:{symbol}:{parity['checks']}")

            candidate = _run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FROZEN_SURVIVOR_DEMA_GATE_0_50_TO_1_00_ATR",
                cost_bps_per_side=args.cost_bps_per_side,
                dema_gate_enabled=True,
            )
            survivor_replays.append(frozen_reference)
            candidate_replays.append(candidate)
            total_dema_blocked += int(candidate.get("dema_gate_blocked_entry_signal_count", 0))
            total_survivor_blocked += int(candidate.get("frozen_survivor_blocked_entry_signal_count", 0))
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "frozen_survivor_parity": parity,
                    "frozen_survivor_trade_count": frozen_reference.get("trade_count"),
                    "candidate_trade_count": candidate.get("trade_count"),
                    "dema_gate_blocked_entry_signal_count": candidate.get("dema_gate_blocked_entry_signal_count"),
                    "frozen_survivor_net_return_pct": frozen_reference.get("net_return_pct"),
                    "candidate_net_return_pct": candidate.get("net_return_pct"),
                    "frozen_survivor_net_profit_factor": frozen_reference.get("net_profit_factor"),
                    "candidate_net_profit_factor": candidate.get("net_profit_factor"),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    survivor_metrics = shared._summary_metrics(survivor_replays)
    candidate_metrics = shared._summary_metrics(candidate_replays)
    survivor_payoff = _payoff_ratio(survivor_replays)
    candidate_payoff = _payoff_ratio(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers

    all_candidate_trades: List[Dict[str, Any]] = []
    for replay in candidate_replays:
        symbol = source.norm_symbol(str(replay.get("symbol")))
        frame = frame_by_symbol[symbol]
        for trade in replay.get("trades", []):
            if isinstance(trade, Mapping):
                all_candidate_trades.append(_enrich_with_path(trade, frame))

    overall_stats = anatomy._stats(all_candidate_trades)
    losses = [trade for trade in all_candidate_trades if float(trade.get("net_return_pct", 0.0)) <= 0.0]
    entry_quality_losses = [trade for trade in losses if str(trade.get("causal_lane")) == "ENTRY_QUALITY_FAILURE"]
    exit_capture_losses = [trade for trade in losses if str(trade.get("causal_lane")) == "EXIT_CAPTURE_FAILURE"]
    mixed_losses = [trade for trade in losses if str(trade.get("causal_lane")) == "MIXED_FAILURE"]
    cost_losses = [trade for trade in losses if str(trade.get("causal_lane")) == "COST_FAILURE"]

    entry_candidates = atlas._preentry_candidates(all_candidate_trades, overall_stats) if all_candidate_trades else []
    high_precision_entry = [
        row for row in entry_candidates if bool(row.get("high_precision_preentry_candidate"))
    ]
    economic_entry = [
        row for row in entry_candidates if bool(row.get("economic_survivor_candidate"))
    ]

    wins = [trade for trade in all_candidate_trades if float(trade.get("net_return_pct", 0.0)) > 0.0]
    indexes = atlas._winner_indexes(wins)
    matched_entry_losses: List[Dict[str, Any]] = []
    for trade in entry_quality_losses:
        item = dict(trade)
        item["matched_winner_contrast"] = atlas._matched_winner_contrast(item, indexes)
        matched_entry_losses.append(item)
    entry_deviations = atlas._deviation_summary(matched_entry_losses)

    loss_lane_stats = _group(losses, ("causal_lane",))
    entry_quality_groups = sorted(
        _group(entry_quality_losses, ("entry_origin", "confirmation_signature"))
        + _group(entry_quality_losses, ("symbol", "entry_origin"))
        + _group(entry_quality_losses, ("dema_distance_atr_bucket", "rsi_strength_bucket")),
        key=lambda row: (float(row["net_return_pct_sum"]), -int(row["strict_loss_count"])),
    )
    exit_path_groups = sorted(
        _group(exit_capture_losses, ("entry_origin", "max_close_net_bucket"))
        + _group(exit_capture_losses, ("confirmation_signature", "max_close_net_bucket"))
        + _group(exit_capture_losses, ("symbol", "mfe_bucket")),
        key=lambda row: (
            -int(row.get("next_open_positive_conversion_count", 0)),
            float(row["net_return_pct_sum"]),
            -int(row["strict_loss_count"]),
        ),
    )
    exit_path_summary = _exit_path_summary(exit_capture_losses)

    payoff_preserved = bool(
        _finite(survivor_payoff)
        and _finite(candidate_payoff)
        and float(candidate_payoff) >= 0.95 * float(survivor_payoff)
    )
    causal_improvement = bool(
        data_pass
        and total_dema_blocked > 0
        and candidate_metrics["trade_count"] <= survivor_metrics["trade_count"]
        and candidate_metrics["net_return_pct_sum"] > survivor_metrics["net_return_pct_sum"]
        and _finite(candidate_metrics.get("net_profit_factor"))
        and _finite(survivor_metrics.get("net_profit_factor"))
        and float(candidate_metrics["net_profit_factor"]) > float(survivor_metrics["net_profit_factor"])
        and float(overall_stats.get("win_rate_pct") or 0.0)
        > float(anatomy._stats([
            trade
            for replay in survivor_replays
            for trade in replay.get("trades", [])
            if isinstance(trade, Mapping)
        ]).get("win_rate_pct") or 0.0)
        and payoff_preserved
    )
    economic_survivor = bool(
        causal_improvement
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and float(candidate_metrics["net_profit_factor"]) > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )

    if not data_pass:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_GATE_DATA_OR_PARITY_FAIL"
        next_stage = "REPAIR_DATA_OR_FROZEN_SURVIVOR_PARITY_ONLY"
    elif economic_survivor:
        state = "PASS_R7A4D_SURVIVOR_DEMA_GATE_ECONOMIC_IMPROVEMENT"
        next_stage = "FREEZE_DEMA_GATE_AND_VALIDATE_SECOND_NONOVERLAPPING_OOS"
    elif causal_improvement:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_GATE_IMPROVED_NOT_ECONOMIC"
        next_stage = "ROLLBACK_DEMA_GATE_KEEP_FROZEN_SURVIVOR"
    else:
        state = "HOLD_R7A4D_SURVIVOR_DEMA_GATE_NO_CAUSAL_IMPROVEMENT"
        next_stage = "ROLLBACK_DEMA_GATE_KEEP_FROZEN_SURVIVOR"

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
        "frozen_survivor_policy_id": survivor_filter.POLICY_ID,
        "single_new_entry_gate_policy_id": POLICY_ID,
        "single_new_entry_gate": {
            "field": "side_adjusted_dema_distance_atr",
            "lower_exclusive": DEMA_ATR_LOWER_EXCLUSIVE,
            "upper_inclusive": DEMA_ATR_UPPER_INCLUSIVE,
            "reference_failed_arm_loss_count": REFERENCE_ATLAS_LOSSES,
            "actual_blocked_entry_signal_count_on_frozen_survivor": total_dema_blocked,
            "future_data_used": False,
        },
        "frozen_survivor_blocked_entry_signal_count": total_survivor_blocked,
        "results": results,
        "frozen_survivor": survivor_metrics,
        "candidate": candidate_metrics,
        "frozen_survivor_payoff_ratio_pct": survivor_payoff,
        "candidate_payoff_ratio_pct": candidate_payoff,
        "payoff_preserved_within_5pct": payoff_preserved,
        "delta": {
            "trade_count": candidate_metrics["trade_count"] - survivor_metrics["trade_count"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - survivor_metrics["net_return_pct_sum"],
            "net_profit_factor": (
                float(candidate_metrics["net_profit_factor"]) - float(survivor_metrics["net_profit_factor"])
                if _finite(candidate_metrics.get("net_profit_factor")) and _finite(survivor_metrics.get("net_profit_factor"))
                else None
            ),
            "payoff_ratio_pct": (
                float(candidate_payoff) - float(survivor_payoff)
                if _finite(candidate_payoff) and _finite(survivor_payoff)
                else None
            ),
        },
        "causal_improvement": causal_improvement,
        "economic_survivor": economic_survivor,
        "candidate_loss_surgery": {
            "overall_trade_stats": overall_stats,
            "loss_count": len(losses),
            "entry_quality_loss_count": len(entry_quality_losses),
            "exit_capture_loss_count": len(exit_capture_losses),
            "mixed_loss_count": len(mixed_losses),
            "cost_loss_count": len(cost_losses),
            "loss_lane_stats": loss_lane_stats,
            "entry_quality_top_groups": entry_quality_groups[:TOP_LIMIT],
            "entry_quality_matched_winner_deviations": entry_deviations[:TOP_LIMIT],
            "entry_quality_top_preentry_filter_candidates": entry_candidates[:TOP_LIMIT],
            "entry_quality_high_precision_candidates": high_precision_entry[:TOP_LIMIT],
            "entry_quality_economic_survivor_candidates": economic_entry[:TOP_LIMIT],
            "exit_capture_close_path_summary": exit_path_summary,
            "exit_capture_top_close_path_groups": exit_path_groups[:TOP_LIMIT],
            "exit_path_diagnostics_are_not_replay_results": True,
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

    survivor_trade_stats = anatomy._stats([
        trade
        for replay in survivor_replays
        for trade in replay.get("trades", [])
        if isinstance(trade, Mapping)
    ])
    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"DEMA_GATE_BLOCKED_ENTRY_SIGNALS={total_dema_blocked}")
    print(f"REFERENCE_FAILED_ARM_LOSSES={REFERENCE_ATLAS_LOSSES}")
    print(f"SURVIVOR_TRADES={survivor_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"SURVIVOR_WINS={survivor_trade_stats['win_count']}")
    print(f"CANDIDATE_WINS={overall_stats['win_count']}")
    print(f"SURVIVOR_WIN_RATE_PCT={survivor_trade_stats['win_rate_pct']}")
    print(f"CANDIDATE_WIN_RATE_PCT={overall_stats['win_rate_pct']}")
    print(f"SURVIVOR_NET_RETURN_PCT_SUM={survivor_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"SURVIVOR_NET_PF={survivor_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"SURVIVOR_PAYOFF_RATIO_PCT={survivor_payoff}")
    print(f"CANDIDATE_PAYOFF_RATIO_PCT={candidate_payoff}")
    print(f"PAYOFF_PRESERVED_WITHIN_5PCT={str(payoff_preserved).lower()}")
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"CANDIDATE_TOTAL_LOSSES={len(losses)}")
    print(f"ENTRY_QUALITY_LOSSES={len(entry_quality_losses)}")
    print(f"EXIT_CAPTURE_LOSSES={len(exit_capture_losses)}")
    print(f"MIXED_LOSSES={len(mixed_losses)}")
    print(f"COST_LOSSES={len(cost_losses)}")
    print(f"LOSS_LANE_STATS={json.dumps(loss_lane_stats, ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_ENTRY_QUALITY_GROUPS={json.dumps(entry_quality_groups[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_ENTRY_FILTERS={json.dumps(entry_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_ENTRY_MATCHED_WIN_DEVIATIONS={json.dumps(entry_deviations[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"EXIT_CLOSE_PATH_SUMMARY={json.dumps(exit_path_summary, ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_EXIT_CLOSE_PATH_GROUPS={json.dumps(exit_path_groups[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"HIGH_PRECISION_ENTRY_COUNT={len(high_precision_entry)}")
    print(f"ECONOMIC_ENTRY_COUNT={len(economic_entry)}")
    print(f"OUTPUT={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
