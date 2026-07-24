from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_causal_atlas as atlas
import r7a4d_integrated_supertrend_entry_origin_anatomy as anatomy
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared
import r7a4d_integrated_supertrend_survivor_dema_gate_and_loss_surgery_audit as surgery
import r7a4d_integrated_supertrend_survivor_dema_second_nonoverlap_oos as second_oos

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_second_oos_causal_atlas_v1"
ANALYSIS_ID = "second_nonoverlap_159_loss_vs_63_win_causal_atlas_v1"
SECOND_DATA_DIRNAME = second_oos.OUTPUT_DIRNAME
FIRST_DATA_DIRNAME = survivor_filter.BASELINE_DIRNAME

EXPECTED_SECOND_TRADES = 222
EXPECTED_SECOND_WINS = 63
EXPECTED_SECOND_LOSSES = 159
TOP_LIMIT = 50

LOCK_ACTIVATION_R = (0.25, 0.50, 0.75, 1.00)
LOCK_NET_FLOOR_PCT = (0.00, 0.02, 0.05, 0.10)

VIDEO_EVIDENCE = {
    "authority": "USER_SUPPLIED_GEMINI_SUMMARIES_AND_PUBLIC_VIDEO_DESCRIPTIONS_ONLY",
    "performance_claim_allowed": False,
    "videos": [
        {
            "video_id": "R2hZlnh37fQ",
            "title": "Master this Pullback Trading Strategy and NEVER WORK AGAIN",
            "rule_clues": [
                "trend structure first",
                "pullback into support/resistance, trendline, or moving-average confluence",
                "reversal candle or counter-trendline break confirmation",
                "next-bar execution after confirmation",
            ],
        },
        {
            "video_id": "g-PLctW8aU0",
            "title": "Highly Profitable DEMA + SuperTrend Trading Strategy",
            "rule_clues": [
                "200 DEMA direction filter",
                "SuperTrend direction flip or already-aligned DEMA recross entry",
                "signal candle must close before next-bar entry",
                "SuperTrend line used as stop/trailing exit",
            ],
        },
        {
            "video_id": "cKKLujAdvzk",
            "title": "Best Pullback Trading Strategy That Will Change The Way You Trade",
            "rule_clues": [
                "existing trend plus pullback to key level",
                "50 MA, support/resistance, or trendline confluence",
                "engulfing, hammer, counter-trendline break, or RSI-50 confirmation",
                "entry after confirmation candle",
            ],
        },
    ],
    "gemini_questions": [
        "Is the pullback rule restricted to the first pullback after a fresh trend break, or are repeated pullbacks allowed?",
        "What exact pivot lookback and ATR tolerance define support/resistance and trendline touch?",
        "For the DEMA plus SuperTrend method, is an already-aligned SuperTrend plus DEMA recross a separate entry from a fresh SuperTrend flip?",
        "Which ATR smoothing method is used by SuperTrend: TradingView RMA default, SMA, or EMA?",
        "Are engulfing and hammer patterns strict numeric definitions or discretionary visual examples?",
        "Is RSI crossing 50 an OR condition with candle/trendline confirmation, or an additional AND requirement?",
        "Is the SuperTrend exit evaluated intrabar, at candle close, or at the next candle open?",
        "Are multiple entries in the same trend permitted, and what exact reset condition authorizes re-entry?",
    ],
}


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


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON_NOT_FOUND:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def _bucket(value: Any, cuts: Sequence[float], labels: Sequence[str]) -> str:
    number = _num(value)
    if number is None:
        return "UNKNOWN"
    for cut, label in zip(cuts, labels):
        if number <= cut:
            return label
    return labels[-1]


def _stats(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return anatomy._stats(list(trades))


def _metric_delta(candidate: Any, baseline: Any) -> Optional[float]:
    if not (_finite(candidate) and _finite(baseline)):
        return None
    return float(candidate) - float(baseline)


def _payoff_preserved(candidate: Mapping[str, Any], baseline: Mapping[str, Any], floor: float = 0.95) -> bool:
    return bool(
        _finite(candidate.get("payoff_ratio_pct"))
        and _finite(baseline.get("payoff_ratio_pct"))
        and float(candidate["payoff_ratio_pct"]) >= floor * float(baseline["payoff_ratio_pct"])
    )


def _entry_time_features(entry_ts: Any) -> Dict[str, Any]:
    timestamp = pd.to_datetime(entry_ts, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return {"entry_hour_utc": None, "entry_hour_bucket": "UNKNOWN", "entry_weekday": "UNKNOWN"}
    hour = int(timestamp.hour)
    if hour <= 7:
        bucket = "UTC_00_07"
    elif hour <= 13:
        bucket = "UTC_08_13"
    elif hour <= 20:
        bucket = "UTC_14_20"
    else:
        bucket = "UTC_21_23"
    return {
        "entry_hour_utc": hour,
        "entry_hour_bucket": bucket,
        "entry_weekday": str(timestamp.day_name()).upper(),
    }


def _video_features(item: Mapping[str, Any]) -> Dict[str, Any]:
    context = item.get("entry_context") if isinstance(item.get("entry_context"), Mapping) else {}
    trigger = set(str(value) for value in context.get("trigger_components", []) if value)
    confirmation = set(str(value) for value in context.get("confirmation_components", []) if value)
    confluence = set(str(value) for value in context.get("confluence_components", []) if value)
    side = str(item.get("side", "UNKNOWN")).lower()
    st_direction = int(context.get("supertrend_direction", 0) or 0)
    dema_distance = _num(item.get("trend_dema_distance_atr"))
    atr = _num(context.get("atr14_geometry"))
    close = _num(context.get("signal_close"))
    st_line = _num(context.get("supertrend_line"))

    aligned_st = (side == "long" and st_direction > 0) or (side == "short" and st_direction < 0)
    st_distance_atr = None
    if atr not in (None, 0.0) and close is not None and st_line is not None:
        raw = (close - st_line) / atr
        st_distance_atr = raw if side == "long" else -raw

    flags = {
        "video_dema200_supertrend_flip": bool("supertrend_flip" in trigger and aligned_st),
        "video_dema_recross_st_aligned": bool("dema_cross" in trigger and aligned_st),
        "video_confirmation_edge": bool("confirmation_edge" in trigger),
        "video_sr_pullback": bool("sr_touch" in confluence),
        "video_trendline_pullback": bool("trendline_touch" in confluence),
        "video_ma50_pullback": bool("ma50_touch" in confluence),
        "video_multi_confluence": bool(len(confluence) >= 2),
        "video_candle_reversal": bool({"bullish_engulfing", "bearish_engulfing", "hammer"} & confirmation),
        "video_rsi50_confirmation": bool({"rsi_cross_up", "rsi_cross_down"} & confirmation),
        "video_counter_trend_break": bool({"counter_trend_break_up", "counter_trend_break_down"} & confirmation),
        "video_structure_confirmed": bool(item.get("structure_valid")),
        "video_dema_side_aligned": bool(dema_distance is not None and dema_distance > 0.0),
    }
    active = sorted(name for name, active in flags.items() if active)
    return {
        **flags,
        "video_rule_signature": "+".join(active) if active else "NONE",
        "supertrend_distance_atr": st_distance_atr,
        "supertrend_distance_atr_bucket": _bucket(
            st_distance_atr,
            (0.0, 0.25, 0.50, 1.00, 2.00, float("inf")),
            ("LE_0", "0_TO_0_25", "0_25_TO_0_50", "0_50_TO_1_00", "1_TO_2", "GT_2"),
        ),
        "entry_atr_pct": atr / close * 100.0 if atr not in (None, 0.0) and close not in (None, 0.0) else None,
    }


def _enrich_trade(trade: Mapping[str, Any], frame: pd.DataFrame, window_id: str) -> Dict[str, Any]:
    item = surgery._enrich_with_path(trade, frame)
    item.update(_entry_time_features(item.get("entry_ts")))
    item.update(_video_features(item))
    item["entry_atr_pct_bucket"] = _bucket(
        item.get("entry_atr_pct"),
        (0.25, 0.50, 0.75, 1.00, 1.50, float("inf")),
        ("LE_0_25", "0_25_TO_0_50", "0_50_TO_0_75", "0_75_TO_1_00", "1_TO_1_50", "GT_1_50"),
    )
    item["window_id"] = window_id
    return item


def _load_window_trades(
    *,
    data_dir: Path,
    symbols: Sequence[str],
    fold_id: str,
    cost_bps_per_side: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], List[Dict[str, Any]], List[str]]:
    trades: List[Dict[str, Any]] = []
    frames: Dict[str, pd.DataFrame] = {}
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []

    for symbol in symbols:
        try:
            frame = shared._load_frame(data_dir / f"{symbol.lower()}_15m.csv")
            frames[symbol] = frame
            replay = surgery._run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=fold_id,
                cost_bps_per_side=cost_bps_per_side,
                dema_gate_enabled=False,
            )
            enriched = [
                _enrich_trade(trade, frame, fold_id)
                for trade in replay.get("trades", [])
                if isinstance(trade, Mapping)
            ]
            trades.extend(enriched)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "rows": len(frame),
                    "trade_stats": _stats(enriched),
                    "frozen_survivor_blocked_entry_signal_count": replay.get(
                        "frozen_survivor_blocked_entry_signal_count"
                    ),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    return trades, frames, results, blockers


def _matches(trade: Mapping[str, Any], fields: Sequence[str], values: Sequence[str]) -> bool:
    return all(str(trade.get(field, "UNKNOWN")) == value for field, value in zip(fields, values))


def _window_filter_effect(
    trades: Sequence[Mapping[str, Any]], fields: Sequence[str], values: Sequence[str]
) -> Optional[Dict[str, Any]]:
    baseline_stats = _stats(trades)
    removed = [trade for trade in trades if _matches(trade, fields, values)]
    if not removed or len(removed) == len(trades):
        return None
    remaining = [trade for trade in trades if not _matches(trade, fields, values)]
    removed_stats = _stats(removed)
    remaining_stats = _stats(remaining)
    removed_count = int(removed_stats["trade_count"])
    loss_precision = (
        float(removed_stats["strict_loss_count"]) / removed_count * 100.0 if removed_count > 0 else 0.0
    )
    return {
        "baseline": baseline_stats,
        "removed": removed_stats,
        "remaining": remaining_stats,
        "loss_precision_pct": loss_precision,
        "winner_contamination_count": int(removed_stats["win_count"]),
        "losses_removed_count": int(removed_stats["strict_loss_count"]),
        "trade_count_delta": int(remaining_stats["trade_count"]) - int(baseline_stats["trade_count"]),
        "win_rate_delta_pct_point": _metric_delta(remaining_stats.get("win_rate_pct"), baseline_stats.get("win_rate_pct")),
        "net_return_delta_pct": float(remaining_stats["net_return_pct_sum"]) - float(baseline_stats["net_return_pct_sum"]),
        "net_pf_delta": _metric_delta(remaining_stats.get("net_profit_factor"), baseline_stats.get("net_profit_factor")),
        "payoff_ratio_delta_pct": _metric_delta(remaining_stats.get("payoff_ratio_pct"), baseline_stats.get("payoff_ratio_pct")),
        "payoff_preserved_within_5pct": _payoff_preserved(remaining_stats, baseline_stats),
    }


def _candidate_rules(
    first_trades: Sequence[Mapping[str, Any]],
    second_trades: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    single_fields = (
        "symbol", "side", "entry_origin", "trigger_signature", "confirmation_signature",
        "confirmation_family", "confluence_signature", "structure_valid",
        "confluence_count_bucket", "dema_distance_atr_bucket", "dema_distance_pct_bucket",
        "next_open_gap_bucket", "rsi_strength_bucket", "stop_distance_bucket",
        "entry_atr_pct_bucket", "supertrend_distance_atr_bucket", "entry_hour_bucket",
        "entry_weekday", "video_dema200_supertrend_flip", "video_dema_recross_st_aligned",
        "video_confirmation_edge", "video_sr_pullback", "video_trendline_pullback",
        "video_ma50_pullback", "video_multi_confluence", "video_candle_reversal",
        "video_rsi50_confirmation", "video_counter_trend_break", "video_structure_confirmed",
        "video_dema_side_aligned",
    )
    pair_fields = (
        ("side", "entry_origin"), ("side", "confirmation_signature"),
        ("entry_origin", "confirmation_signature"), ("entry_origin", "confluence_signature"),
        ("confirmation_signature", "confluence_signature"),
        ("confirmation_signature", "dema_distance_atr_bucket"),
        ("confirmation_signature", "rsi_strength_bucket"),
        ("confluence_signature", "dema_distance_atr_bucket"),
        ("confluence_signature", "rsi_strength_bucket"),
        ("dema_distance_atr_bucket", "supertrend_distance_atr_bucket"),
        ("dema_distance_atr_bucket", "entry_atr_pct_bucket"),
        ("rsi_strength_bucket", "entry_atr_pct_bucket"),
        ("symbol", "confirmation_signature"), ("symbol", "entry_origin"),
        ("entry_hour_bucket", "confirmation_signature"),
        ("video_counter_trend_break", "confluence_signature"),
        ("video_candle_reversal", "confluence_signature"),
        ("video_dema_recross_st_aligned", "confirmation_signature"),
        ("video_dema200_supertrend_flip", "confirmation_signature"),
    )

    rules: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = []
    for field in single_fields:
        for value in sorted({str(trade.get(field, "UNKNOWN")) for trade in second_trades}):
            if field.startswith("video_") and value != "True":
                continue
            rules.append(((field,), (value,)))
    for fields in pair_fields:
        for values in sorted({tuple(str(trade.get(field, "UNKNOWN")) for field in fields) for trade in second_trades}):
            if any(field.startswith("video_") and value != "True" for field, value in zip(fields, values)):
                continue
            rules.append((tuple(fields), tuple(values)))

    combined = list(first_trades) + list(second_trades)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for fields, values in rules:
        key = (fields, values)
        if key in seen:
            continue
        seen.add(key)
        second_effect = _window_filter_effect(second_trades, fields, values)
        first_effect = _window_filter_effect(first_trades, fields, values)
        combined_effect = _window_filter_effect(combined, fields, values)
        if second_effect is None or combined_effect is None or int(second_effect["losses_removed_count"]) < 3:
            continue

        second_high_precision = bool(
            int(second_effect["losses_removed_count"]) >= 8
            and int(second_effect["winner_contamination_count"]) <= 1
            and float(second_effect["loss_precision_pct"]) >= 85.0
        )
        first_same_direction = bool(
            first_effect is not None
            and int(first_effect["losses_removed_count"]) >= 2
            and float(first_effect["net_return_delta_pct"]) >= 0.0
            and (first_effect.get("win_rate_delta_pct_point") or 0.0) >= 0.0
            and (first_effect.get("net_pf_delta") is None or float(first_effect["net_pf_delta"]) >= -0.01)
        )
        second_economic_improvement = bool(
            float(second_effect["net_return_delta_pct"]) > 0.0
            and (second_effect.get("win_rate_delta_pct_point") or 0.0) > 0.0
            and (second_effect.get("net_pf_delta") or 0.0) > 0.0
            and bool(second_effect["payoff_preserved_within_5pct"])
        )
        combined_economic_improvement = bool(
            float(combined_effect["net_return_delta_pct"]) > 0.0
            and (combined_effect.get("win_rate_delta_pct_point") or 0.0) > 0.0
            and (combined_effect.get("net_pf_delta") or 0.0) > 0.0
            and bool(combined_effect["payoff_preserved_within_5pct"])
        )
        cross_window_repeat = bool(
            first_same_direction and second_economic_improvement and combined_economic_improvement
            and int(second_effect["winner_contamination_count"])
            <= max(1, int(second_effect["losses_removed_count"]) // 5)
        )
        rows.append({
            "dimension": "+".join(fields), "group": "|".join(values),
            "fields": list(fields), "values": list(values),
            "second_window": second_effect, "first_window": first_effect,
            "combined": combined_effect, "second_high_precision": second_high_precision,
            "first_same_direction": first_same_direction,
            "second_economic_improvement": second_economic_improvement,
            "combined_economic_improvement": combined_economic_improvement,
            "cross_window_repeat_candidate": cross_window_repeat,
        })

    rows.sort(key=lambda row: (
        -int(bool(row["cross_window_repeat_candidate"])),
        -int(bool(row["second_high_precision"])),
        -float(row["combined"]["net_return_delta_pct"]),
        -float(row["second_window"]["net_return_delta_pct"]),
        int(row["second_window"]["winner_contamination_count"]),
        -int(row["second_window"]["losses_removed_count"]),
        str(row["dimension"]), str(row["group"]),
    ))
    return rows


def _simulate_lock_trade(trade: Mapping[str, Any], frame: pd.DataFrame, activation_r: float, net_floor_pct: float) -> Dict[str, Any]:
    original_net = float(trade.get("net_return_pct", 0.0))
    entry_bar = int(trade.get("entry_bar", -1))
    exit_bar = int(trade.get("exit_bar", -1))
    entry_price = _num(trade.get("entry_price"))
    stop_distance_pct = _num(trade.get("initial_stop_distance_pct"))
    side = str(trade.get("side", "")).lower()
    cost_pct = max(float(trade.get("round_trip_cost_pct", 0.0)), 0.0)
    result = {
        "valid": False, "activated": False, "lock_hit": False,
        "original_net_pct": original_net, "candidate_net_pct": original_net,
        "delta_net_pct": 0.0, "activation_bar": None, "exit_bar": exit_bar,
        "exit_price": trade.get("exit_price"), "loss_to_win": False, "win_to_loss": False,
    }
    if (entry_price in (None, 0.0) or stop_distance_pct in (None, 0.0)
        or stop_distance_pct <= 0.0 or entry_bar < 0 or exit_bar <= entry_bar
        or exit_bar >= len(frame) or side not in ("long", "short")):
        return result

    activation_bar: Optional[int] = None
    for bar in range(entry_bar, exit_bar):
        close = float(frame["close"].iloc[bar])
        gross_pct = ((close - entry_price) / entry_price * 100.0 if side == "long"
                     else (entry_price - close) / entry_price * 100.0)
        if gross_pct / stop_distance_pct >= activation_r and gross_pct - cost_pct >= net_floor_pct:
            activation_bar = bar
            break
    result["valid"] = True
    if activation_bar is None:
        return result

    result["activated"] = True
    result["activation_bar"] = activation_bar
    lock_gross_pct = cost_pct + net_floor_pct
    lock_price = (entry_price * (1.0 + lock_gross_pct / 100.0) if side == "long"
                  else entry_price * (1.0 - lock_gross_pct / 100.0))
    candidate_exit_price: Optional[float] = None
    candidate_exit_bar: Optional[int] = None
    for bar in range(activation_bar + 1, exit_bar + 1):
        open_price = float(frame["open"].iloc[bar])
        high = float(frame["high"].iloc[bar])
        low = float(frame["low"].iloc[bar])
        if side == "long":
            if open_price <= lock_price:
                candidate_exit_price, candidate_exit_bar = open_price, bar
                break
            if low <= lock_price:
                candidate_exit_price, candidate_exit_bar = lock_price, bar
                break
        else:
            if open_price >= lock_price:
                candidate_exit_price, candidate_exit_bar = open_price, bar
                break
            if high >= lock_price:
                candidate_exit_price, candidate_exit_bar = lock_price, bar
                break
    if candidate_exit_price is None or candidate_exit_bar is None:
        return result

    candidate_gross = ((candidate_exit_price - entry_price) / entry_price * 100.0 if side == "long"
                       else (entry_price - candidate_exit_price) / entry_price * 100.0)
    candidate_net = candidate_gross - cost_pct
    result.update({
        "lock_hit": True, "candidate_net_pct": candidate_net,
        "delta_net_pct": candidate_net - original_net, "exit_bar": candidate_exit_bar,
        "exit_price": candidate_exit_price,
        "loss_to_win": bool(original_net <= 0.0 and candidate_net > 0.0),
        "win_to_loss": bool(original_net > 0.0 and candidate_net <= 0.0),
    })
    return result


def _lock_window_effect(trades: Sequence[Mapping[str, Any]], frames: Mapping[str, pd.DataFrame], activation_r: float, net_floor_pct: float) -> Dict[str, Any]:
    baseline_stats = _stats(trades)
    candidate_trades: List[Dict[str, Any]] = []
    simulations: List[Dict[str, Any]] = []
    for trade in trades:
        symbol = source.norm_symbol(str(trade.get("symbol")))
        simulation = _simulate_lock_trade(trade, frames[symbol], activation_r, net_floor_pct)
        simulations.append(simulation)
        candidate = dict(trade)
        candidate["net_return_pct"] = float(simulation["candidate_net_pct"])
        candidate["gross_return_pct"] = float(simulation["candidate_net_pct"]) + float(trade.get("round_trip_cost_pct", 0.0))
        candidate_trades.append(candidate)
    candidate_stats = _stats(candidate_trades)
    return {
        "activation_r": activation_r, "net_floor_pct": net_floor_pct,
        "baseline": baseline_stats, "candidate": candidate_stats,
        "activated_count": sum(bool(item["activated"]) for item in simulations),
        "lock_hit_count": sum(bool(item["lock_hit"]) for item in simulations),
        "loss_to_win_count": sum(bool(item["loss_to_win"]) for item in simulations),
        "win_to_loss_count": sum(bool(item["win_to_loss"]) for item in simulations),
        "net_return_delta_pct": float(candidate_stats["net_return_pct_sum"]) - float(baseline_stats["net_return_pct_sum"]),
        "win_rate_delta_pct_point": _metric_delta(candidate_stats.get("win_rate_pct"), baseline_stats.get("win_rate_pct")),
        "net_pf_delta": _metric_delta(candidate_stats.get("net_profit_factor"), baseline_stats.get("net_profit_factor")),
        "payoff_ratio_delta_pct": _metric_delta(candidate_stats.get("payoff_ratio_pct"), baseline_stats.get("payoff_ratio_pct")),
        "payoff_preserved_within_5pct": _payoff_preserved(candidate_stats, baseline_stats),
        "trade_substitution_only_reentry_not_replayed": True,
    }


def _profit_lock_grid(first_trades: Sequence[Mapping[str, Any]], first_frames: Mapping[str, pd.DataFrame], second_trades: Sequence[Mapping[str, Any]], second_frames: Mapping[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for activation_r in LOCK_ACTIVATION_R:
        for net_floor_pct in LOCK_NET_FLOOR_PCT:
            first = _lock_window_effect(first_trades, first_frames, activation_r, net_floor_pct)
            second = _lock_window_effect(second_trades, second_frames, activation_r, net_floor_pct)
            combined_baseline = _stats(list(first_trades) + list(second_trades))
            combined_candidate_values: List[Dict[str, Any]] = []
            combined_sims: List[Dict[str, Any]] = []
            for window_trades, window_frames in ((first_trades, first_frames), (second_trades, second_frames)):
                for trade in window_trades:
                    symbol = source.norm_symbol(str(trade.get("symbol")))
                    simulation = _simulate_lock_trade(trade, window_frames[symbol], activation_r, net_floor_pct)
                    combined_sims.append(simulation)
                    candidate = dict(trade)
                    candidate["net_return_pct"] = float(simulation["candidate_net_pct"])
                    candidate["gross_return_pct"] = float(simulation["candidate_net_pct"]) + float(trade.get("round_trip_cost_pct", 0.0))
                    combined_candidate_values.append(candidate)
            combined_candidate = _stats(combined_candidate_values)
            combined = {
                "baseline": combined_baseline, "candidate": combined_candidate,
                "activated_count": sum(bool(item["activated"]) for item in combined_sims),
                "lock_hit_count": sum(bool(item["lock_hit"]) for item in combined_sims),
                "loss_to_win_count": sum(bool(item["loss_to_win"]) for item in combined_sims),
                "win_to_loss_count": sum(bool(item["win_to_loss"]) for item in combined_sims),
                "net_return_delta_pct": float(combined_candidate["net_return_pct_sum"]) - float(combined_baseline["net_return_pct_sum"]),
                "win_rate_delta_pct_point": _metric_delta(combined_candidate.get("win_rate_pct"), combined_baseline.get("win_rate_pct")),
                "net_pf_delta": _metric_delta(combined_candidate.get("net_profit_factor"), combined_baseline.get("net_profit_factor")),
                "payoff_ratio_delta_pct": _metric_delta(combined_candidate.get("payoff_ratio_pct"), combined_baseline.get("payoff_ratio_pct")),
                "payoff_preserved_within_5pct": _payoff_preserved(combined_candidate, combined_baseline),
            }
            two_window_candidate = bool(
                float(first["net_return_delta_pct"]) > 0.0 and float(second["net_return_delta_pct"]) > 0.0
                and (first.get("net_pf_delta") or 0.0) > 0.0 and (second.get("net_pf_delta") or 0.0) > 0.0
                and (first.get("win_rate_delta_pct_point") or 0.0) > 0.0
                and (second.get("win_rate_delta_pct_point") or 0.0) > 0.0
                and bool(first["payoff_preserved_within_5pct"]) and bool(second["payoff_preserved_within_5pct"])
                and int(combined["loss_to_win_count"]) > int(combined["win_to_loss_count"])
            )
            rows.append({
                "activation_r": activation_r, "net_floor_pct": net_floor_pct,
                "first_window": first, "second_window": second, "combined": combined,
                "two_window_profit_lock_candidate": two_window_candidate,
                "full_replay_required_before_patch": True,
            })
    rows.sort(key=lambda row: (
        -int(bool(row["two_window_profit_lock_candidate"])),
        -float(row["combined"]["net_return_delta_pct"]),
        -float(row["combined"].get("win_rate_delta_pct_point") or 0.0),
        -float(row["combined"].get("net_pf_delta") or 0.0),
        float(row["activation_r"]), float(row["net_floor_pct"]),
    ))
    return rows


def _group(trades: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = tuple(str(trade.get(field, "UNKNOWN")) for field in fields)
        buckets[key].append(trade)
    rows: List[Dict[str, Any]] = []
    for key, bucket in buckets.items():
        rows.append({
            "dimension": "+".join(fields), "group": "|".join(key), **_stats(bucket),
            "ever_close_net_positive_count": sum(bool(item.get("ever_close_net_positive")) for item in bucket),
            "next_open_positive_conversion_count": sum(bool(item.get("convertible_next_open_after_first_positive_close")) for item in bucket),
            "next_open_0_25r_conversion_count": sum(bool(item.get("convertible_next_open_after_0_25r_close")) for item in bucket),
            "mean_max_close_net_pct": _mean(item.get("max_close_net_pct") for item in bucket),
            "mean_mfe_pct": _mean(item.get("mfe_pct") for item in bucket),
            "mean_mae_pct": _mean(item.get("mae_pct") for item in bucket),
        })
    rows.sort(key=lambda row: (float(row["net_return_pct_sum"]), -int(row["strict_loss_count"]), str(row["group"])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Read-only second non-overlapping OOS causal atlas for the exact 159 losses versus 63 winners "
        "of the frozen survivor. It contrasts losses against matched winners, tests winner-preserving "
        "pre-entry filters across both windows, and performs causal next-bar profit-lock diagnostics."
    ))
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()
    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    first_dir = root / "runtime" / FIRST_DATA_DIRNAME
    second_dir = root / "runtime" / SECOND_DATA_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip()))

    blockers: List[str] = []
    previous_summary: Dict[str, Any] = {}
    try:
        previous_summary = _load_json(second_dir / "summary_v1.json")
        previous_survivor = previous_summary.get("second_window_survivor_trade_stats")
        if not isinstance(previous_survivor, Mapping):
            raise ValueError("PREVIOUS_SECOND_SURVIVOR_STATS_MISSING")
        if int(previous_survivor.get("trade_count", -1)) != EXPECTED_SECOND_TRADES:
            raise ValueError(f"EXPECTED_SECOND_TRADES_MISMATCH:{previous_survivor.get('trade_count')}")
        if int(previous_survivor.get("win_count", -1)) != EXPECTED_SECOND_WINS:
            raise ValueError(f"EXPECTED_SECOND_WINS_MISMATCH:{previous_survivor.get('win_count')}")
        if int(previous_survivor.get("loss_count", -1)) != EXPECTED_SECOND_LOSSES:
            raise ValueError(f"EXPECTED_SECOND_LOSSES_MISMATCH:{previous_survivor.get('loss_count')}")
    except Exception as exc:
        blockers.append(f"PREVIOUS_SUMMARY:{type(exc).__name__}:{exc}")

    first_trades, first_frames, first_results, first_blockers = _load_window_trades(
        data_dir=first_dir, symbols=symbols,
        fold_id="FIRST_WINDOW_FROZEN_SURVIVOR_CAUSAL_ATLAS",
        cost_bps_per_side=args.cost_bps_per_side,
    )
    second_trades, second_frames, second_results, second_blockers = _load_window_trades(
        data_dir=second_dir, symbols=symbols,
        fold_id="SECOND_NONOVERLAP_FROZEN_SURVIVOR_CAUSAL_ATLAS",
        cost_bps_per_side=args.cost_bps_per_side,
    )
    blockers.extend(first_blockers)
    blockers.extend(second_blockers)

    first_stats = _stats(first_trades)
    second_stats = _stats(second_trades)
    second_count_parity = bool(
        int(second_stats["trade_count"]) == EXPECTED_SECOND_TRADES
        and int(second_stats["win_count"]) == EXPECTED_SECOND_WINS
        and int(second_stats["loss_count"]) == EXPECTED_SECOND_LOSSES
    )
    if not second_count_parity:
        blockers.append(f"SECOND_COUNT_PARITY:{second_stats['trade_count']}:{second_stats['win_count']}:{second_stats['loss_count']}")

    second_wins = [trade for trade in second_trades if float(trade.get("net_return_pct", 0.0)) > 0.0]
    second_losses = [trade for trade in second_trades if float(trade.get("net_return_pct", 0.0)) <= 0.0]
    winner_indexes = atlas._winner_indexes(second_wins)
    loss_records: List[Dict[str, Any]] = []
    for loss in second_losses:
        record = dict(loss)
        record["matched_winner_contrast"] = atlas._matched_winner_contrast(record, winner_indexes)
        loss_records.append(record)

    matched_deviations = atlas._deviation_summary(loss_records)
    loss_lane_stats = _group(loss_records, ("causal_lane",))
    path_failure_stats = _group(loss_records, ("path_failure_class",))
    video_failure_stats = sorted(
        _group(loss_records, ("video_rule_signature", "causal_lane"))
        + _group(loss_records, ("confirmation_signature", "confluence_signature", "causal_lane"))
        + _group(loss_records, ("entry_origin", "trigger_signature", "causal_lane")),
        key=lambda row: (float(row["net_return_pct_sum"]), -int(row["strict_loss_count"]), str(row["group"])),
    )
    symbol_side_failure_stats = sorted(
        _group(loss_records, ("symbol", "side", "causal_lane"))
        + _group(loss_records, ("entry_hour_bucket", "causal_lane"))
        + _group(loss_records, ("entry_weekday", "causal_lane")),
        key=lambda row: (float(row["net_return_pct_sum"]), -int(row["strict_loss_count"]), str(row["group"])),
    )

    entry_filter_candidates = _candidate_rules(first_trades, second_trades)
    cross_window_entry_candidates = [row for row in entry_filter_candidates if bool(row["cross_window_repeat_candidate"])]
    second_high_precision_candidates = [row for row in entry_filter_candidates if bool(row["second_high_precision"])]
    profit_lock_grid = _profit_lock_grid(first_trades, first_frames, second_trades, second_frames)
    two_window_profit_lock_candidates = [row for row in profit_lock_grid if bool(row["two_window_profit_lock_candidate"])]

    lane_counts: Dict[str, int] = defaultdict(int)
    for loss in loss_records:
        lane_counts[str(loss.get("causal_lane", "UNKNOWN"))] += 1

    data_pass = bool(
        not blockers and len(first_results) == len(symbols) and len(second_results) == len(symbols)
        and second_count_parity and len(second_losses) == EXPECTED_SECOND_LOSSES
        and len(second_wins) == EXPECTED_SECOND_WINS
    )
    if not data_pass:
        state = "HOLD_R7A4D_SECOND_OOS_CAUSAL_ATLAS_DATA_OR_PARITY_FAIL"
        next_stage = "REPAIR_SECOND_OOS_PARITY_ONLY"
    elif cross_window_entry_candidates:
        state = "PASS_R7A4D_SECOND_OOS_CAUSAL_ATLAS_CROSS_WINDOW_ENTRY_CANDIDATE_FOUND"
        next_stage = "VALIDATE_TOP_ONE_CROSS_WINDOW_ENTRY_FILTER_FULL_REPLAY"
    elif two_window_profit_lock_candidates:
        state = "PASS_R7A4D_SECOND_OOS_CAUSAL_ATLAS_TWO_WINDOW_EXIT_CANDIDATE_FOUND"
        next_stage = "VALIDATE_TOP_ONE_CAUSAL_PROFIT_LOCK_FULL_REPLAY"
    else:
        state = "PASS_R7A4D_SECOND_OOS_CAUSAL_ATLAS_NO_SURVIVOR_YET"
        next_stage = "ASK_VIDEO_GAP_QUESTIONS_AND_REFINE_ONE_RULE_DIMENSION"

    summary = {
        "state": state, "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "analysis_id": ANALYSIS_ID, "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1, "target_sha": args.target_sha,
        "symbols": symbols, "interval": source.INTERVAL,
        "cost_bps_per_side": args.cost_bps_per_side,
        "expected_second_window_counts": {"trades": EXPECTED_SECOND_TRADES, "wins": EXPECTED_SECOND_WINS, "losses": EXPECTED_SECOND_LOSSES},
        "second_count_parity": second_count_parity,
        "previous_second_oos_summary_state": previous_summary.get("state"),
        "first_window_stats": first_stats, "second_window_stats": second_stats,
        "second_loss_lane_counts": dict(sorted(lane_counts.items())),
        "matched_winner_deviation_summary": matched_deviations,
        "loss_lane_stats": loss_lane_stats, "path_failure_stats": path_failure_stats,
        "video_rule_failure_stats": video_failure_stats[:TOP_LIMIT],
        "symbol_side_time_failure_stats": symbol_side_failure_stats[:TOP_LIMIT],
        "top_cross_window_entry_filter_candidates": cross_window_entry_candidates[:TOP_LIMIT],
        "top_second_high_precision_entry_candidates": second_high_precision_candidates[:TOP_LIMIT],
        "top_all_entry_filter_candidates": entry_filter_candidates[:TOP_LIMIT],
        "top_two_window_profit_lock_candidates": two_window_profit_lock_candidates[:TOP_LIMIT],
        "profit_lock_grid": profit_lock_grid, "video_evidence": VIDEO_EVIDENCE,
        "loss_records": loss_records, "first_results": first_results, "second_results": second_results,
        "blockers": blockers, "source_strategy_mutated": False, "registry_mutated": False,
        "service_mutated": False, "shadow_started": False,
        "paper_live_order_allowed": False, "performance_claim_allowed": False,
        "promotion_allowed": False, "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_FIRST_SYMBOLS={sum(row.get('status') == 'PASS' for row in first_results)}/{len(symbols)}")
    print(f"PASSED_SECOND_SYMBOLS={sum(row.get('status') == 'PASS' for row in second_results)}/{len(symbols)}")
    print(f"SECOND_COUNT_PARITY={str(second_count_parity).lower()}")
    print(f"SECOND_TRADES={second_stats['trade_count']}")
    print(f"SECOND_WINS={second_stats['win_count']}")
    print(f"SECOND_LOSSES={second_stats['loss_count']}")
    print(f"SECOND_WIN_RATE_PCT={second_stats['win_rate_pct']}")
    print(f"SECOND_NET_RETURN_PCT_SUM={second_stats['net_return_pct_sum']:.6f}")
    print(f"SECOND_NET_PF={second_stats['net_profit_factor']}")
    print(f"SECOND_PAYOFF_RATIO_PCT={second_stats['payoff_ratio_pct']}")
    print(f"LOSS_LANE_COUNTS={json.dumps(dict(sorted(lane_counts.items())), ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_MATCHED_WIN_DEVIATIONS={json.dumps(matched_deviations[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_CROSS_WINDOW_ENTRY_FILTERS={json.dumps(cross_window_entry_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_SECOND_HIGH_PRECISION_ENTRY_FILTERS={json.dumps(second_high_precision_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_TWO_WINDOW_PROFIT_LOCKS={json.dumps(two_window_profit_lock_candidates[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"TOP_PROFIT_LOCK_GRID={json.dumps(profit_lock_grid[:10], ensure_ascii=False, sort_keys=True)}")
    print(f"VIDEO_GAP_QUESTIONS={json.dumps(VIDEO_EVIDENCE['gemini_questions'], ensure_ascii=False)}")
    print(f"OUTPUT={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
