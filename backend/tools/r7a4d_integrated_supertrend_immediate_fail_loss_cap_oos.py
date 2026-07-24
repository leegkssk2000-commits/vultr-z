from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_immediate_fail_loss_cap_oos_v1"
BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
POLICY_ID = "early_invalidation_no_cost_coverage_by_bar2_v1"
EARLY_EXIT_REASON = "EARLY_INVALIDATION_NO_COST_COVERAGE_BY_BAR2"
MAX_EARLY_HOLD_BARS = 2
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


def _max_drawdown_pct(values: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    maximum = 0.0
    for value in values:
        equity *= 1.0 + float(value) / 100.0
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100.0)
    return maximum


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _matches_survivor_filter(symbol: str, context: Mapping[str, Any]) -> bool:
    return (
        source.norm_symbol(symbol) == survivor_filter.TARGET_SYMBOL
        and str(context.get("side")) == survivor_filter.TARGET_SIDE
        and str(context.get("trigger_signature")) == survivor_filter.TARGET_TRIGGER_SIGNATURE
        and str(context.get("confluence_signature")) == survivor_filter.TARGET_CONFLUENCE_SIGNATURE
    )


def _filtered_features(
    frame: pd.DataFrame,
    cfg: Any,
    *,
    symbol: str,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    features = baseline.compute_features(frame, cfg).copy()
    blocked: List[Dict[str, Any]] = []
    for position in range(len(features)):
        if not bool(features["short_entry_signal"].iloc[position]):
            continue
        context = baseline._signal_context(frame, features, position, baseline.SHORT)
        if not _matches_survivor_filter(symbol, context):
            continue
        features.loc[features.index[position], "short_entry_signal"] = False
        blocked.append(
            {
                "bar": position,
                "timestamp": baseline._timestamp(frame, position),
                "symbol": source.norm_symbol(symbol),
                "side": baseline.SHORT,
                "trigger_signature": context.get("trigger_signature"),
                "confirmation_signature": context.get("confirmation_signature"),
                "confluence_signature": context.get("confluence_signature"),
            }
        )
    return features, blocked


def _run_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    cost_bps_per_side: float,
    early_invalidation_enabled: bool,
) -> Dict[str, Any]:
    cfg = baseline.IntegratedSupertrendPullbackConfig()
    cfg.validate()
    if timeframe != cfg.timeframe:
        raise ValueError("TIMEFRAME_NOT_15M")
    if not _finite(cost_bps_per_side) or float(cost_bps_per_side) < 0:
        raise ValueError("COST_BPS_INVALID")

    validated = frame.copy()
    for column in ("open", "high", "low", "close"):
        validated[column] = pd.to_numeric(validated[column], errors="raise").astype(float)
    features, blocked_entries = _filtered_features(validated, cfg, symbol=symbol)

    position_side = baseline.FLAT
    entry_price: Optional[float] = None
    entry_ts: Any = None
    entry_bar: Optional[int] = None
    entry_signal_bar: Optional[int] = None
    entry_context: Optional[Dict[str, Any]] = None
    active_stop: Optional[float] = None
    initial_stop: Optional[float] = None
    max_favorable_pct = 0.0
    max_adverse_pct = 0.0
    pending: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    early_invalidation_signal_count = 0

    round_trip_cost_pct = 2.0 * float(cost_bps_per_side) / 100.0

    def update_excursion(position: int) -> None:
        nonlocal max_favorable_pct, max_adverse_pct
        if position_side == baseline.FLAT or entry_price is None:
            return
        high = float(validated["high"].iloc[position])
        low = float(validated["low"].iloc[position])
        if position_side == baseline.LONG:
            favorable = (high - entry_price) / entry_price * 100.0
            adverse = (low - entry_price) / entry_price * 100.0
        else:
            favorable = (entry_price - low) / entry_price * 100.0
            adverse = (entry_price - high) / entry_price * 100.0
        max_favorable_pct = max(max_favorable_pct, favorable)
        max_adverse_pct = min(max_adverse_pct, adverse)

    def mark_to_close(position: int) -> float:
        if position_side == baseline.FLAT or entry_price is None:
            raise RuntimeError("MARK_WITHOUT_OPEN_POSITION")
        close = float(validated["close"].iloc[position])
        if position_side == baseline.LONG:
            return (close - entry_price) / entry_price * 100.0
        return (entry_price - close) / entry_price * 100.0

    def close_trade(
        position: int,
        price: float,
        reason: str,
        *,
        intrabar_path_unknown: bool = False,
    ) -> None:
        nonlocal position_side, entry_price, entry_ts, entry_bar, entry_signal_bar
        nonlocal entry_context, active_stop, initial_stop, max_favorable_pct, max_adverse_pct
        if position_side == baseline.FLAT or entry_price is None or entry_bar is None:
            raise RuntimeError("CLOSE_WITHOUT_OPEN_POSITION")
        side = position_side
        if side == baseline.LONG:
            gross_pct = (price - entry_price) / entry_price * 100.0
        else:
            gross_pct = (entry_price - price) / entry_price * 100.0
        net_pct = gross_pct - round_trip_cost_pct
        context = dict(entry_context or {})
        stop_distance_pct = None
        invalid_initial_stop = None
        if initial_stop is not None:
            if side == baseline.LONG:
                stop_distance_pct = (entry_price - initial_stop) / entry_price * 100.0
                invalid_initial_stop = initial_stop >= entry_price
            else:
                stop_distance_pct = (initial_stop - entry_price) / entry_price * 100.0
                invalid_initial_stop = initial_stop <= entry_price
        trades.append(
            {
                "strategy_id": baseline.STRATEGY_ID,
                "symbol": symbol,
                "timeframe": timeframe,
                "replay_fold_id": replay_fold_id,
                "side": side,
                "entry_ts": entry_ts,
                "exit_ts": baseline._timestamp(validated, position),
                "entry_bar": entry_bar,
                "entry_signal_bar": entry_signal_bar,
                "exit_bar": position,
                "hold_bars": position - entry_bar + 1,
                "entry_price": entry_price,
                "exit_price": float(price),
                "initial_stop": initial_stop,
                "initial_stop_distance_pct": stop_distance_pct,
                "invalid_initial_stop": invalid_initial_stop,
                "exit_reason": reason,
                "gross_return_pct": gross_pct,
                "round_trip_cost_pct": round_trip_cost_pct,
                "net_return_pct": net_pct,
                "cost_bps_per_side": float(cost_bps_per_side),
                "mfe_pct": max_favorable_pct,
                "mae_pct": max_adverse_pct,
                "mae_abs_pct": abs(max_adverse_pct),
                "giveback_from_mfe_pct": max_favorable_pct - gross_pct,
                "intrabar_path_unknown": bool(intrabar_path_unknown),
                "entry_context": context,
            }
        )
        position_side = baseline.FLAT
        entry_price = None
        entry_ts = None
        entry_bar = None
        entry_signal_bar = None
        entry_context = None
        active_stop = None
        initial_stop = None
        max_favorable_pct = 0.0
        max_adverse_pct = 0.0

    for i in range(len(validated)):
        row = validated.iloc[i]
        feature = features.iloc[i]
        open_price = float(row["open"])

        if pending is not None:
            action = pending["action"]
            if action == baseline.ENTER_LONG and position_side == baseline.FLAT:
                position_side = baseline.LONG
                entry_price = open_price
                entry_ts = baseline._timestamp(validated, i)
                entry_bar = i
                entry_signal_bar = int(pending["signal_bar"])
                entry_context = dict(pending["context"])
                initial_stop = float(pending["stop"])
                active_stop = initial_stop
                entry_context["next_open_gap_pct"] = (
                    (open_price - float(entry_context["signal_close"]))
                    / float(entry_context["signal_close"])
                    * 100.0
                )
                events.append(
                    {
                        "bar": i,
                        "event": baseline.ENTER_LONG,
                        "fill_price": open_price,
                        "signal_bar": pending["signal_bar"],
                    }
                )
            elif action == baseline.ENTER_SHORT and position_side == baseline.FLAT:
                position_side = baseline.SHORT
                entry_price = open_price
                entry_ts = baseline._timestamp(validated, i)
                entry_bar = i
                entry_signal_bar = int(pending["signal_bar"])
                entry_context = dict(pending["context"])
                initial_stop = float(pending["stop"])
                active_stop = initial_stop
                entry_context["next_open_gap_pct"] = (
                    (float(entry_context["signal_close"]) - open_price)
                    / float(entry_context["signal_close"])
                    * 100.0
                )
                events.append(
                    {
                        "bar": i,
                        "event": baseline.ENTER_SHORT,
                        "fill_price": open_price,
                        "signal_bar": pending["signal_bar"],
                    }
                )
            elif action == baseline.EXIT_LONG and position_side == baseline.LONG:
                reason = str(pending.get("reason", "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN"))
                close_trade(i, open_price, reason)
                events.append(
                    {
                        "bar": i,
                        "event": baseline.EXIT_LONG,
                        "fill_price": open_price,
                        "signal_bar": pending["signal_bar"],
                        "reason": reason,
                    }
                )
            elif action == baseline.EXIT_SHORT and position_side == baseline.SHORT:
                reason = str(pending.get("reason", "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN"))
                close_trade(i, open_price, reason)
                events.append(
                    {
                        "bar": i,
                        "event": baseline.EXIT_SHORT,
                        "fill_price": open_price,
                        "signal_bar": pending["signal_bar"],
                        "reason": reason,
                    }
                )
            pending = None

        update_excursion(i)

        if position_side == baseline.LONG and active_stop is not None and float(row["low"]) <= active_stop:
            stop_fill = min(open_price, active_stop)
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP", intrabar_path_unknown=True)
            events.append(
                {
                    "bar": i,
                    "event": baseline.EXIT_LONG,
                    "fill_price": stop_fill,
                    "reason": "SUPERTREND_TRAILING_STOP",
                }
            )
        elif position_side == baseline.SHORT and active_stop is not None and float(row["high"]) >= active_stop:
            stop_fill = max(open_price, active_stop)
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP", intrabar_path_unknown=True)
            events.append(
                {
                    "bar": i,
                    "event": baseline.EXIT_SHORT,
                    "fill_price": stop_fill,
                    "reason": "SUPERTREND_TRAILING_STOP",
                }
            )

        if _finite(feature["supertrend_line"]):
            line = float(feature["supertrend_line"])
            direction = int(feature["supertrend_direction"]) if _finite(feature["supertrend_direction"]) else 0
            if position_side == baseline.LONG and direction == 1:
                active_stop = line if active_stop is None else max(active_stop, line)
            elif position_side == baseline.SHORT and direction == -1:
                active_stop = line if active_stop is None else min(active_stop, line)

        if i >= len(validated) - 1 or pending is not None:
            continue

        if position_side == baseline.LONG and bool(feature["supertrend_flip_down"]):
            pending = {
                "action": baseline.EXIT_LONG,
                "signal_bar": i,
                "reason": "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN",
            }
        elif position_side == baseline.SHORT and bool(feature["supertrend_flip_up"]):
            pending = {
                "action": baseline.EXIT_SHORT,
                "signal_bar": i,
                "reason": "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN",
            }
        elif early_invalidation_enabled and position_side != baseline.FLAT and entry_bar is not None:
            hold_bars = i - entry_bar + 1
            close_gross_pct = mark_to_close(i)
            no_cost_coverage = max_favorable_pct < round_trip_cost_pct
            close_loss_beyond_cost = close_gross_pct <= -round_trip_cost_pct
            if 1 <= hold_bars <= MAX_EARLY_HOLD_BARS and no_cost_coverage and close_loss_beyond_cost:
                action = baseline.EXIT_LONG if position_side == baseline.LONG else baseline.EXIT_SHORT
                pending = {
                    "action": action,
                    "signal_bar": i,
                    "reason": EARLY_EXIT_REASON,
                }
                early_invalidation_signal_count += 1
                events.append(
                    {
                        "bar": i,
                        "event": "EARLY_INVALIDATION_SIGNAL",
                        "side": position_side,
                        "close_gross_pct": close_gross_pct,
                        "mfe_pct": max_favorable_pct,
                        "round_trip_cost_pct": round_trip_cost_pct,
                    }
                )
        elif position_side == baseline.FLAT and bool(feature["long_entry_signal"]):
            pending = {
                "action": baseline.ENTER_LONG,
                "signal_bar": i,
                "stop": float(feature["supertrend_line"]),
                "context": baseline._signal_context(validated, features, i, baseline.LONG),
            }
        elif position_side == baseline.FLAT and bool(feature["short_entry_signal"]):
            pending = {
                "action": baseline.ENTER_SHORT,
                "signal_bar": i,
                "stop": float(feature["supertrend_line"]),
                "context": baseline._signal_context(validated, features, i, baseline.SHORT),
            }

    gross_returns = [float(trade["gross_return_pct"]) for trade in trades]
    net_returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = sum(value > 0 for value in net_returns)
    return {
        "strategy_id": baseline.STRATEGY_ID,
        "canonical_strategy_count": 1,
        "replay_profile_id": "integrated_supertrend_immediate_fail_loss_cap_replay_v1",
        "anatomy_schema_version": baseline.ANATOMY_SCHEMA_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "replay_fold_id": replay_fold_id,
        "signal_time": "CONFIRMED_BAR_CLOSE",
        "fill_time": "NEXT_BAR_OPEN",
        "terminal_force_close": False,
        "cost_bps_per_side": float(cost_bps_per_side),
        "trade_count": len(trades),
        "win_count": wins,
        "loss_count": len(trades) - wins,
        "win_rate_pct": wins / len(trades) * 100.0 if trades else None,
        "gross_return_pct": sum(gross_returns),
        "net_return_pct": sum(net_returns),
        "gross_profit_factor": _profit_factor(gross_returns),
        "net_profit_factor": _profit_factor(net_returns),
        "max_drawdown_pct": _max_drawdown_pct(net_returns),
        "open_position": {
            "side": position_side,
            "entry_price": entry_price,
            "entry_ts": entry_ts,
            "entry_bar": entry_bar,
            "entry_signal_bar": entry_signal_bar,
            "active_stop": active_stop,
            "initial_stop": initial_stop,
            "mfe_pct": max_favorable_pct if position_side != baseline.FLAT else None,
            "mae_pct": max_adverse_pct if position_side != baseline.FLAT else None,
            "entry_context": entry_context,
        },
        "pending_order": pending,
        "trades": trades,
        "events": events,
        "authority": baseline.AUTHORITY,
        "performance_claim_allowed": False,
        "survivor_entry_filter_policy_id": survivor_filter.POLICY_ID,
        "survivor_blocked_entry_signal_count": len(blocked_entries),
        "survivor_blocked_entry_signals": blocked_entries,
        "early_invalidation_enabled": bool(early_invalidation_enabled),
        "early_invalidation_policy_id": POLICY_ID if early_invalidation_enabled else None,
        "early_invalidation_signal_count": early_invalidation_signal_count,
        "early_invalidation_exit_count": sum(
            str(trade.get("exit_reason")) == EARLY_EXIT_REASON for trade in trades
        ),
    }


def _pf_match(left: Any, right: Any, tolerance: float = 1e-10) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return _finite(left) and _finite(right) and abs(float(left) - float(right)) <= tolerance


def _parity(reference: Mapping[str, Any], replay: Mapping[str, Any]) -> Dict[str, Any]:
    reference_trades = reference.get("trades") if isinstance(reference.get("trades"), list) else []
    replay_trades = replay.get("trades") if isinstance(replay.get("trades"), list) else []
    sequence_match = len(reference_trades) == len(replay_trades)
    if sequence_match:
        for left, right in zip(reference_trades, replay_trades):
            keys = ("side", "entry_bar", "exit_bar", "exit_reason")
            if any(left.get(key) != right.get(key) for key in keys):
                sequence_match = False
                break
            for key in ("gross_return_pct", "net_return_pct"):
                if not _finite(left.get(key)) or not _finite(right.get(key)):
                    sequence_match = False
                    break
                if abs(float(left[key]) - float(right[key])) > 1e-10:
                    sequence_match = False
                    break
            if not sequence_match:
                break
    checks = {
        "trade_count": int(reference.get("trade_count", -1)) == int(replay.get("trade_count", -2)),
        "gross_return_pct": abs(float(reference.get("gross_return_pct", 0.0)) - float(replay.get("gross_return_pct", 0.0))) <= 1e-10,
        "net_return_pct": abs(float(reference.get("net_return_pct", 0.0)) - float(replay.get("net_return_pct", 0.0))) <= 1e-10,
        "gross_profit_factor": _pf_match(reference.get("gross_profit_factor"), replay.get("gross_profit_factor")),
        "net_profit_factor": _pf_match(reference.get("net_profit_factor"), replay.get("net_profit_factor")),
        "trade_sequence": sequence_match,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def _trade_stats(replays: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    trades = [
        trade
        for replay in replays
        for trade in (replay.get("trades") if isinstance(replay.get("trades"), list) else [])
        if isinstance(trade, Mapping)
    ]
    net = [float(trade.get("net_return_pct", 0.0)) for trade in trades]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    valid_net_r: List[float] = []
    for trade in trades:
        stop_distance = trade.get("initial_stop_distance_pct")
        net_return = trade.get("net_return_pct")
        if not _finite(stop_distance) or not _finite(net_return) or float(stop_distance) <= 0:
            continue
        valid_net_r.append(float(net_return) / float(stop_distance))
    win_r = [value for value in valid_net_r if value > 0]
    loss_r = [value for value in valid_net_r if value < 0]
    avg_win = _mean(wins)
    avg_loss = _mean(losses)
    avg_win_r = _mean(win_r)
    avg_loss_r = _mean(loss_r)
    return {
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100.0 if trades else None,
        "avg_win_net_pct": avg_win,
        "avg_loss_net_pct": avg_loss,
        "payoff_ratio_pct": (
            avg_win / abs(avg_loss)
            if avg_win is not None and avg_loss is not None and avg_loss < 0
            else None
        ),
        "expectancy_net_pct_per_trade": _mean(net),
        "net_profit_factor": _profit_factor(net),
        "valid_r_trade_count": len(valid_net_r),
        "avg_win_net_r": avg_win_r,
        "avg_loss_net_r": avg_loss_r,
        "payoff_ratio_r": (
            avg_win_r / abs(avg_loss_r)
            if avg_win_r is not None and avg_loss_r is not None and avg_loss_r < 0
            else None
        ),
        "early_invalidation_exit_count": sum(
            str(trade.get("exit_reason")) == EARLY_EXIT_REASON for trade in trades
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only OOS test of one causal loss repair layered on the frozen LINKUSDT loss-cluster survivor: "
            "exit next open within the first two bars only when MFE never covered round-trip cost and the close loss exceeds that cost."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    baseline_dir = root / "runtime" / BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    survivor_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_early_signals = 0
    total_early_exits = 0

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
            copied_reference = _run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_LINKUSDT_SURVIVOR_COPY_PARITY",
                cost_bps_per_side=args.cost_bps_per_side,
                early_invalidation_enabled=False,
            )
            parity = _parity(survivor, copied_reference)
            if parity.get("status") != "PASS":
                raise RuntimeError(f"SURVIVOR_COPY_PARITY_FAILED:{symbol}:{parity.get('checks')}")

            candidate = _run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_IMMEDIATE_FAIL_LOSS_CAP",
                cost_bps_per_side=args.cost_bps_per_side,
                early_invalidation_enabled=True,
            )
            total_early_signals += int(candidate.get("early_invalidation_signal_count", 0))
            total_early_exits += int(candidate.get("early_invalidation_exit_count", 0))
            survivor_replays.append(survivor)
            candidate_replays.append(candidate)
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "raw_baseline_invariant": raw_invariant,
                    "survivor_copy_parity": parity,
                    "survivor_trade_count": survivor.get("trade_count"),
                    "candidate_trade_count": candidate.get("trade_count"),
                    "survivor_net_return_pct": survivor.get("net_return_pct"),
                    "candidate_net_return_pct": candidate.get("net_return_pct"),
                    "survivor_net_profit_factor": survivor.get("net_profit_factor"),
                    "candidate_net_profit_factor": candidate.get("net_profit_factor"),
                    "early_invalidation_signal_count": candidate.get("early_invalidation_signal_count"),
                    "early_invalidation_exit_count": candidate.get("early_invalidation_exit_count"),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    survivor_metrics = shared._summary_metrics(survivor_replays)
    candidate_metrics = shared._summary_metrics(candidate_replays)
    survivor_trade_stats = _trade_stats(survivor_replays)
    candidate_trade_stats = _trade_stats(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers

    survivor_avg_loss = survivor_trade_stats.get("avg_loss_net_pct")
    candidate_avg_loss = candidate_trade_stats.get("avg_loss_net_pct")
    avg_loss_improved = bool(
        _finite(survivor_avg_loss)
        and _finite(candidate_avg_loss)
        and float(candidate_avg_loss) > float(survivor_avg_loss)
    )
    causal_improvement = bool(
        data_pass
        and total_early_exits > 0
        and shared._strictly_better(
            candidate_metrics["net_return_pct_sum"], survivor_metrics["net_return_pct_sum"]
        )
        and shared._strictly_better(
            candidate_metrics["net_profit_factor"], survivor_metrics["net_profit_factor"]
        )
        and avg_loss_improved
    )
    economic_survivor = bool(
        causal_improvement
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
        state = "HOLD_R7A4D_IMMEDIATE_FAIL_LOSS_CAP_DATA_OR_PARITY_FAIL"
        next_stage = "ROLLBACK_THIS_CANDIDATE"
    elif material_improvement:
        state = "PASS_R7A4D_IMMEDIATE_FAIL_LOSS_CAP_MATERIAL_ECONOMIC_IMPROVEMENT"
        next_stage = "FREEZE_RULE_AND_RUN_SECOND_NONOVERLAPPING_OOS"
    elif economic_survivor:
        state = "PASS_R7A4D_IMMEDIATE_FAIL_LOSS_CAP_ECONOMIC_IMPROVEMENT"
        next_stage = "RUN_SECOND_NONOVERLAPPING_OOS_BEFORE_ANY_MORE_TUNING"
    elif causal_improvement:
        state = "HOLD_R7A4D_IMMEDIATE_FAIL_LOSS_CAP_IMPROVED_BUT_NOT_ECONOMIC_SURVIVOR"
        next_stage = "ROLLBACK_OR_KEEP_RESEARCH_ONLY"
    else:
        state = "HOLD_R7A4D_IMMEDIATE_FAIL_LOSS_CAP_NO_CAUSAL_IMPROVEMENT"
        next_stage = "ROLLBACK_THIS_SINGLE_RULE"

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
        "single_causal_repair": True,
        "early_invalidation_policy": {
            "policy_id": POLICY_ID,
            "max_hold_bars": MAX_EARLY_HOLD_BARS,
            "decision_time": "BAR_CLOSE",
            "execution_time": "NEXT_BAR_OPEN",
            "conditions_all_required": [
                "position remains open after canonical SuperTrend stop evaluation",
                "hold_bars <= 2",
                "MFE < round_trip_cost_pct",
                "mark_to_close_gross_pct <= -round_trip_cost_pct",
            ],
            "future_data_used": False,
            "same_bar_intrabar_path_claimed": False,
        },
        "total_early_invalidation_signal_count": total_early_signals,
        "total_early_invalidation_exit_count": total_early_exits,
        "results": results,
        "survivor": survivor_metrics,
        "candidate": candidate_metrics,
        "survivor_trade_stats": survivor_trade_stats,
        "candidate_trade_stats": candidate_trade_stats,
        "delta": {
            "trade_count": candidate_metrics["trade_count"] - survivor_metrics["trade_count"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - survivor_metrics["net_return_pct_sum"],
            "net_profit_factor": (
                candidate_metrics["net_profit_factor"] - survivor_metrics["net_profit_factor"]
                if _finite(candidate_metrics["net_profit_factor"])
                and _finite(survivor_metrics["net_profit_factor"])
                else None
            ),
            "avg_loss_net_pct": (
                float(candidate_avg_loss) - float(survivor_avg_loss)
                if _finite(candidate_avg_loss) and _finite(survivor_avg_loss)
                else None
            ),
            "avg_loss_net_r": (
                float(candidate_trade_stats["avg_loss_net_r"])
                - float(survivor_trade_stats["avg_loss_net_r"])
                if _finite(candidate_trade_stats.get("avg_loss_net_r"))
                and _finite(survivor_trade_stats.get("avg_loss_net_r"))
                else None
            ),
            "positive_symbol_count": candidate_metrics["positive_symbol_count"]
            - survivor_metrics["positive_symbol_count"],
        },
        "avg_loss_improved": avg_loss_improved,
        "causal_improvement": causal_improvement,
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
    print(f"EARLY_INVALIDATION_SIGNALS={total_early_signals}")
    print(f"EARLY_INVALIDATION_EXITS={total_early_exits}")
    print(f"SURVIVOR_TRADES={survivor_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"SURVIVOR_NET_RETURN_PCT_SUM={survivor_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"SURVIVOR_NET_PF={survivor_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"SURVIVOR_AVG_WIN_NET_PCT={survivor_trade_stats['avg_win_net_pct']}")
    print(f"SURVIVOR_AVG_LOSS_NET_PCT={survivor_trade_stats['avg_loss_net_pct']}")
    print(f"SURVIVOR_PAYOFF_RATIO_PCT={survivor_trade_stats['payoff_ratio_pct']}")
    print(f"CANDIDATE_AVG_WIN_NET_PCT={candidate_trade_stats['avg_win_net_pct']}")
    print(f"CANDIDATE_AVG_LOSS_NET_PCT={candidate_trade_stats['avg_loss_net_pct']}")
    print(f"CANDIDATE_PAYOFF_RATIO_PCT={candidate_trade_stats['payoff_ratio_pct']}")
    print(f"SURVIVOR_AVG_WIN_NET_R={survivor_trade_stats['avg_win_net_r']}")
    print(f"SURVIVOR_AVG_LOSS_NET_R={survivor_trade_stats['avg_loss_net_r']}")
    print(f"SURVIVOR_PAYOFF_RATIO_R={survivor_trade_stats['payoff_ratio_r']}")
    print(f"CANDIDATE_AVG_WIN_NET_R={candidate_trade_stats['avg_win_net_r']}")
    print(f"CANDIDATE_AVG_LOSS_NET_R={candidate_trade_stats['avg_loss_net_r']}")
    print(f"CANDIDATE_PAYOFF_RATIO_R={candidate_trade_stats['payoff_ratio_r']}")
    print(f"AVG_LOSS_IMPROVED={str(avg_loss_improved).lower()}")
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"MATERIAL_IMPROVEMENT={str(material_improvement).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={blockers}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
