from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_cost_aware_lock_replay as lock_source
from strategies.authentic.integrated_supertrend_pullback_v1 import (
    AUTHORITY,
    ENTER_LONG,
    ENTER_SHORT,
    EXIT_LONG,
    EXIT_SHORT,
    FLAT,
    LONG,
    SHORT,
    STRATEGY_ID,
    IntegratedSupertrendPullbackConfig,
    compute_features,
)

REPLAY_PROFILE_ID = "integrated_supertrend_pullback_reentry_guard_replay_v1"
ANATOMY_SCHEMA_VERSION = 1
EXIT_POLICY_ID = "completed_close_3x_cost_arm_plus_1bp_net_lock_v1"
REENTRY_GUARD_POLICY_ID = "block_same_side_after_profit_lock_until_opposite_st_or_dema200_cross_v1"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _structural_reset_reason(
    *,
    blocked_side: Optional[str],
    feature: pd.Series,
    previous_feature: Optional[pd.Series],
    close_price: float,
    previous_close: Optional[float],
) -> Optional[str]:
    if blocked_side not in {LONG, SHORT}:
        return None

    dema = float(feature["dema200"]) if _finite(feature["dema200"]) else None
    previous_dema = (
        float(previous_feature["dema200"])
        if previous_feature is not None and _finite(previous_feature["dema200"])
        else None
    )
    cross_up = bool(
        previous_close is not None
        and dema is not None
        and previous_dema is not None
        and close_price > dema
        and previous_close <= previous_dema
    )
    cross_down = bool(
        previous_close is not None
        and dema is not None
        and previous_dema is not None
        and close_price < dema
        and previous_close >= previous_dema
    )

    if blocked_side == LONG:
        if bool(feature["supertrend_flip_down"]):
            return "OPPOSITE_SUPERTREND_FLIP_DOWN"
        if cross_down:
            return "DEMA200_CROSS_DOWN"
    else:
        if bool(feature["supertrend_flip_up"]):
            return "OPPOSITE_SUPERTREND_FLIP_UP"
        if cross_up:
            return "DEMA200_CROSS_UP"
    return None


def _self_check() -> None:
    lock_source._self_check()
    long_feature = pd.Series(
        {
            "dema200": 100.0,
            "supertrend_flip_up": False,
            "supertrend_flip_down": False,
        }
    )
    previous = pd.Series({"dema200": 100.0})
    assert _structural_reset_reason(
        blocked_side=LONG,
        feature=long_feature,
        previous_feature=previous,
        close_price=101.0,
        previous_close=101.0,
    ) is None
    long_feature["supertrend_flip_down"] = True
    assert _structural_reset_reason(
        blocked_side=LONG,
        feature=long_feature,
        previous_feature=previous,
        close_price=101.0,
        previous_close=101.0,
    ) == "OPPOSITE_SUPERTREND_FLIP_DOWN"
    long_feature["supertrend_flip_down"] = False
    assert _structural_reset_reason(
        blocked_side=LONG,
        feature=long_feature,
        previous_feature=previous,
        close_price=99.0,
        previous_close=101.0,
    ) == "DEMA200_CROSS_DOWN"


def run_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "15m",
    replay_fold_id: str = "UNKNOWN",
    cost_bps_per_side: float = 0.0,
    arm_cost_multiple: float = 3.0,
    lock_net_bps: float = 1.0,
    config: Optional[IntegratedSupertrendPullbackConfig] = None,
) -> Dict[str, Any]:
    _self_check()
    cfg = config or IntegratedSupertrendPullbackConfig()
    cfg.validate()
    if timeframe != cfg.timeframe:
        raise ValueError("TIMEFRAME_NOT_15M")
    if not _finite(cost_bps_per_side) or float(cost_bps_per_side) < 0:
        raise ValueError("COST_BPS_INVALID")
    if not _finite(arm_cost_multiple) or float(arm_cost_multiple) <= 0:
        raise ValueError("ARM_COST_MULTIPLE_INVALID")
    if not _finite(lock_net_bps) or float(lock_net_bps) < 0:
        raise ValueError("LOCK_NET_BPS_INVALID")

    features = compute_features(frame, cfg)
    validated = frame.copy()
    for column in ("open", "high", "low", "close"):
        validated[column] = pd.to_numeric(validated[column], errors="raise").astype(float)

    position_side = FLAT
    entry_price: Optional[float] = None
    entry_ts: Any = None
    entry_bar: Optional[int] = None
    entry_signal_bar: Optional[int] = None
    entry_context: Optional[Dict[str, Any]] = None
    active_stop: Optional[float] = None
    initial_stop: Optional[float] = None
    profit_lock_stop: Optional[float] = None
    profit_lock_armed_bar: Optional[int] = None
    max_favorable_pct = 0.0
    max_adverse_pct = 0.0
    pending: Optional[Dict[str, Any]] = None
    reentry_block_side: Optional[str] = None
    reentry_block_bar: Optional[int] = None
    reentry_blocked_signal_count = 0
    reentry_reset_count = 0
    trades: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    def update_excursion(position: int) -> None:
        nonlocal max_favorable_pct, max_adverse_pct
        if position_side == FLAT or entry_price is None:
            return
        high = float(validated["high"].iloc[position])
        low = float(validated["low"].iloc[position])
        if position_side == LONG:
            favorable = (high - entry_price) / entry_price * 100.0
            adverse = (low - entry_price) / entry_price * 100.0
        else:
            favorable = (entry_price - low) / entry_price * 100.0
            adverse = (entry_price - high) / entry_price * 100.0
        max_favorable_pct = max(max_favorable_pct, favorable)
        max_adverse_pct = min(max_adverse_pct, adverse)

    def close_trade(
        position: int,
        price: float,
        reason: str,
        *,
        intrabar_path_unknown: bool = False,
    ) -> None:
        nonlocal position_side, entry_price, entry_ts, entry_bar, entry_signal_bar
        nonlocal entry_context, active_stop, initial_stop, profit_lock_stop, profit_lock_armed_bar
        nonlocal max_favorable_pct, max_adverse_pct, reentry_block_side, reentry_block_bar
        if position_side == FLAT or entry_price is None or entry_bar is None:
            raise RuntimeError("CLOSE_WITHOUT_OPEN_POSITION")
        closed_side = position_side
        gross_pct = (
            (price - entry_price) / entry_price * 100.0
            if closed_side == LONG
            else (entry_price - price) / entry_price * 100.0
        )
        round_trip_cost_pct = (2.0 * float(cost_bps_per_side)) / 100.0
        net_pct = gross_pct - round_trip_cost_pct
        context = dict(entry_context or {})
        stop_distance_pct = None
        invalid_initial_stop = None
        if initial_stop is not None:
            if closed_side == LONG:
                stop_distance_pct = (entry_price - initial_stop) / entry_price * 100.0
                invalid_initial_stop = initial_stop >= entry_price
            else:
                stop_distance_pct = (initial_stop - entry_price) / entry_price * 100.0
                invalid_initial_stop = initial_stop <= entry_price
        trades.append(
            {
                "strategy_id": STRATEGY_ID,
                "symbol": symbol,
                "timeframe": timeframe,
                "replay_fold_id": replay_fold_id,
                "side": closed_side,
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
                "profit_lock_stop": profit_lock_stop,
                "profit_lock_armed_bar": profit_lock_armed_bar,
                "profit_lock_armed": profit_lock_stop is not None,
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
        if reason == "COST_AWARE_PROFIT_LOCK":
            reentry_block_side = closed_side
            reentry_block_bar = position
            events.append(
                {
                    "bar": position,
                    "event": "ARM_SAME_REGIME_REENTRY_BLOCK",
                    "blocked_side": closed_side,
                    "effective_from_bar": position,
                }
            )
        position_side = FLAT
        entry_price = None
        entry_ts = None
        entry_bar = None
        entry_signal_bar = None
        entry_context = None
        active_stop = None
        initial_stop = None
        profit_lock_stop = None
        profit_lock_armed_bar = None
        max_favorable_pct = 0.0
        max_adverse_pct = 0.0

    for i in range(len(validated)):
        row = validated.iloc[i]
        feature = features.iloc[i]
        previous_feature = features.iloc[i - 1] if i > 0 else None
        previous_close = float(validated["close"].iloc[i - 1]) if i > 0 else None
        open_price = float(row["open"])

        if pending is not None:
            action = pending["action"]
            if action == ENTER_LONG and position_side == FLAT:
                position_side = LONG
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
                events.append({"bar": i, "event": ENTER_LONG, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == ENTER_SHORT and position_side == FLAT:
                position_side = SHORT
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
                events.append({"bar": i, "event": ENTER_SHORT, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == EXIT_LONG and position_side == LONG:
                close_trade(i, open_price, "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN")
                events.append({"bar": i, "event": EXIT_LONG, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == EXIT_SHORT and position_side == SHORT:
                close_trade(i, open_price, "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN")
                events.append({"bar": i, "event": EXIT_SHORT, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            pending = None

        update_excursion(i)

        if position_side == LONG and active_stop is not None and float(row["low"]) <= active_stop:
            stop_fill = min(open_price, active_stop)
            is_lock = profit_lock_stop is not None and abs(float(active_stop) - float(profit_lock_stop)) <= max(1e-12, float(entry_price or 1.0) * 1e-12)
            reason = "COST_AWARE_PROFIT_LOCK" if is_lock else "SUPERTREND_TRAILING_STOP"
            close_trade(i, stop_fill, reason, intrabar_path_unknown=True)
            events.append({"bar": i, "event": EXIT_LONG, "fill_price": stop_fill, "reason": reason})
        elif position_side == SHORT and active_stop is not None and float(row["high"]) >= active_stop:
            stop_fill = max(open_price, active_stop)
            is_lock = profit_lock_stop is not None and abs(float(active_stop) - float(profit_lock_stop)) <= max(1e-12, float(entry_price or 1.0) * 1e-12)
            reason = "COST_AWARE_PROFIT_LOCK" if is_lock else "SUPERTREND_TRAILING_STOP"
            close_trade(i, stop_fill, reason, intrabar_path_unknown=True)
            events.append({"bar": i, "event": EXIT_SHORT, "fill_price": stop_fill, "reason": reason})

        if _finite(feature["supertrend_line"]):
            line = float(feature["supertrend_line"])
            direction = int(feature["supertrend_direction"]) if _finite(feature["supertrend_direction"]) else 0
            if position_side == LONG and direction == 1:
                active_stop = line if active_stop is None else max(active_stop, line)
            elif position_side == SHORT and direction == -1:
                active_stop = line if active_stop is None else min(active_stop, line)

        if position_side != FLAT and entry_price is not None:
            next_stop, lock_floor, changed = lock_source._cost_aware_lock_stop(
                side=position_side,
                entry_price=entry_price,
                close_price=float(row["close"]),
                active_stop=active_stop,
                cost_bps_per_side=float(cost_bps_per_side),
                arm_cost_multiple=float(arm_cost_multiple),
                lock_net_bps=float(lock_net_bps),
            )
            if lock_floor is not None:
                profit_lock_stop = lock_floor if profit_lock_stop is None else (
                    max(profit_lock_stop, lock_floor) if position_side == LONG else min(profit_lock_stop, lock_floor)
                )
            if changed:
                active_stop = next_stop
                if profit_lock_armed_bar is None:
                    profit_lock_armed_bar = i
                events.append(
                    {
                        "bar": i,
                        "event": "ARM_COST_AWARE_PROFIT_LOCK",
                        "effective_from_bar": i + 1,
                        "close_price": float(row["close"]),
                        "active_stop": active_stop,
                        "lock_floor": profit_lock_stop,
                    }
                )

        reset_reason = _structural_reset_reason(
            blocked_side=reentry_block_side,
            feature=feature,
            previous_feature=previous_feature,
            close_price=float(row["close"]),
            previous_close=previous_close,
        )
        if reset_reason is not None:
            events.append(
                {
                    "bar": i,
                    "event": "RESET_SAME_REGIME_REENTRY_BLOCK",
                    "blocked_side": reentry_block_side,
                    "block_bar": reentry_block_bar,
                    "reason": reset_reason,
                }
            )
            reentry_block_side = None
            reentry_block_bar = None
            reentry_reset_count += 1

        if i >= len(validated) - 1 or pending is not None:
            continue

        if position_side == LONG and bool(feature["supertrend_flip_down"]):
            pending = {"action": EXIT_LONG, "signal_bar": i}
        elif position_side == SHORT and bool(feature["supertrend_flip_up"]):
            pending = {"action": EXIT_SHORT, "signal_bar": i}
        elif position_side == FLAT and bool(feature["long_entry_signal"]):
            if reentry_block_side == LONG:
                reentry_blocked_signal_count += 1
                events.append(
                    {
                        "bar": i,
                        "event": "BLOCK_SAME_REGIME_REENTRY_SIGNAL",
                        "blocked_side": LONG,
                        "block_bar": reentry_block_bar,
                    }
                )
            else:
                pending = {
                    "action": ENTER_LONG,
                    "signal_bar": i,
                    "stop": float(feature["supertrend_line"]),
                    "context": baseline._signal_context(validated, features, i, LONG),
                }
        elif position_side == FLAT and bool(feature["short_entry_signal"]):
            if reentry_block_side == SHORT:
                reentry_blocked_signal_count += 1
                events.append(
                    {
                        "bar": i,
                        "event": "BLOCK_SAME_REGIME_REENTRY_SIGNAL",
                        "blocked_side": SHORT,
                        "block_bar": reentry_block_bar,
                    }
                )
            else:
                pending = {
                    "action": ENTER_SHORT,
                    "signal_bar": i,
                    "stop": float(feature["supertrend_line"]),
                    "context": baseline._signal_context(validated, features, i, SHORT),
                }

    gross_returns = [float(trade["gross_return_pct"]) for trade in trades]
    net_returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = sum(value > 0 for value in net_returns)
    return {
        "strategy_id": STRATEGY_ID,
        "canonical_strategy_count": 1,
        "replay_profile_id": REPLAY_PROFILE_ID,
        "anatomy_schema_version": ANATOMY_SCHEMA_VERSION,
        "exit_policy_id": EXIT_POLICY_ID,
        "reentry_guard_policy_id": REENTRY_GUARD_POLICY_ID,
        "base_entry_signal_formula_unchanged": True,
        "post_profit_lock_reentry_guard_added": True,
        "causal_lock_uses_completed_close": True,
        "same_bar_lock_allowed": False,
        "arm_cost_multiple": float(arm_cost_multiple),
        "lock_net_bps": float(lock_net_bps),
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
        "win_rate_pct": (wins / len(trades) * 100.0) if trades else None,
        "gross_return_pct": sum(gross_returns),
        "net_return_pct": sum(net_returns),
        "gross_profit_factor": baseline._profit_factor(gross_returns),
        "net_profit_factor": baseline._profit_factor(net_returns),
        "max_drawdown_pct": baseline._max_drawdown_pct(net_returns),
        "profit_lock_armed_trade_count": sum(bool(trade.get("profit_lock_armed")) for trade in trades),
        "profit_lock_exit_count": sum(trade.get("exit_reason") == "COST_AWARE_PROFIT_LOCK" for trade in trades),
        "reentry_blocked_signal_count": reentry_blocked_signal_count,
        "reentry_reset_count": reentry_reset_count,
        "reentry_block_side_at_end": reentry_block_side,
        "reentry_block_bar_at_end": reentry_block_bar,
        "open_position": {
            "side": position_side,
            "entry_price": entry_price,
            "entry_ts": entry_ts,
            "entry_bar": entry_bar,
            "entry_signal_bar": entry_signal_bar,
            "active_stop": active_stop,
            "initial_stop": initial_stop,
            "profit_lock_stop": profit_lock_stop,
            "profit_lock_armed_bar": profit_lock_armed_bar,
            "mfe_pct": max_favorable_pct if position_side != FLAT else None,
            "mae_pct": max_adverse_pct if position_side != FLAT else None,
            "entry_context": entry_context,
        },
        "pending_order": pending,
        "trades": trades,
        "events": events,
        "authority": AUTHORITY,
        "performance_claim_allowed": False,
    }


def _load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only post-profit-lock same-regime reentry guard replay")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--fold", default="UNKNOWN")
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--arm-cost-multiple", type=float, default=3.0)
    parser.add_argument("--lock-net-bps", type=float, default=1.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = run_replay(
        _load_csv(Path(args.csv)),
        symbol=args.symbol,
        timeframe=args.timeframe,
        replay_fold_id=args.fold,
        cost_bps_per_side=args.cost_bps_per_side,
        arm_cost_multiple=args.arm_cost_multiple,
        lock_net_bps=args.lock_net_bps,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
