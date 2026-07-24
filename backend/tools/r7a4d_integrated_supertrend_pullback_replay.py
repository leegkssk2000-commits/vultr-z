from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from strategies.authentic.integrated_supertrend_pullback_v1 import (  # noqa: E402
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

REPLAY_PROFILE_ID = "integrated_supertrend_pullback_replay_v1"
ANATOMY_SCHEMA_VERSION = 1


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _timestamp(frame: pd.DataFrame, position: int) -> Any:
    row = frame.iloc[position]
    for key in ("bar_open_ts", "open_ts", "timestamp", "ts", "time"):
        if key in frame.columns and pd.notna(row[key]):
            value = row[key]
            return value.item() if hasattr(value, "item") else value
    value = frame.index[position]
    return value.item() if hasattr(value, "item") else value


def _profit_factor(returns: List[float]) -> Optional[float]:
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _max_drawdown_pct(returns: List[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in returns:
        equity *= 1.0 + (value / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    return max_dd


def _bool_at(frame: pd.DataFrame, column: str, position: int) -> bool:
    return bool(frame[column].iloc[position]) if column in frame.columns else False


def _float_at(frame: pd.DataFrame, column: str, position: int) -> Optional[float]:
    if column not in frame.columns:
        return None
    value = frame[column].iloc[position]
    return float(value) if _finite(value) else None


def _signal_context(
    validated: pd.DataFrame,
    features: pd.DataFrame,
    position: int,
    side: str,
) -> Dict[str, Any]:
    feature = features.iloc[position]
    close = float(validated["close"].iloc[position])
    dema = float(feature["dema200"]) if _finite(feature["dema200"]) else None
    atr = _float_at(validated, "atr14_geometry", position)

    if side == LONG:
        confirmation_names = (
            ("bullish_engulfing", bool(feature["bullish_engulfing"])),
            ("hammer", bool(feature["hammer"])),
            ("rsi_cross_up", bool(feature["rsi_cross_up"])),
            ("counter_trend_break_up", _bool_at(validated, "counter_trend_break_up", position)),
        )
        trigger_names = [
            name
            for name, active in (
                ("supertrend_flip", bool(feature["supertrend_flip_up"])),
                (
                    "dema_cross",
                    position > 0
                    and _finite(features["dema200"].iloc[position - 1])
                    and close > float(feature["dema200"])
                    and float(validated["close"].iloc[position - 1])
                    <= float(features["dema200"].iloc[position - 1]),
                ),
                (
                    "confirmation_edge",
                    bool(feature["long_confirmation"])
                    and (position == 0 or not bool(features["long_confirmation"].iloc[position - 1])),
                ),
            )
            if active
        ]
        structure = _bool_at(validated, "structure_long", position)
    else:
        confirmation_names = (
            ("bearish_engulfing", bool(feature["bearish_engulfing"])),
            ("rsi_cross_down", bool(feature["rsi_cross_down"])),
            ("counter_trend_break_down", _bool_at(validated, "counter_trend_break_down", position)),
        )
        trigger_names = [
            name
            for name, active in (
                ("supertrend_flip", bool(feature["supertrend_flip_down"])),
                (
                    "dema_cross",
                    position > 0
                    and _finite(features["dema200"].iloc[position - 1])
                    and close < float(feature["dema200"])
                    and float(validated["close"].iloc[position - 1])
                    >= float(features["dema200"].iloc[position - 1]),
                ),
                (
                    "confirmation_edge",
                    bool(feature["short_confirmation"])
                    and (position == 0 or not bool(features["short_confirmation"].iloc[position - 1])),
                ),
            )
            if active
        ]
        structure = _bool_at(validated, "structure_short", position)

    confluence = [
        name
        for name in ("sr_touch", "trendline_touch", "ma50_touch")
        if _bool_at(validated, name, position)
    ]
    confirmations = [name for name, active in confirmation_names if active]
    dema_distance_pct = ((close - dema) / dema * 100.0) if dema not in (None, 0.0) else None
    dema_distance_atr = ((close - dema) / atr) if dema is not None and atr not in (None, 0.0) else None

    return {
        "signal_bar": position,
        "signal_ts": _timestamp(validated, position),
        "signal_close": close,
        "side": side,
        "trigger_components": trigger_names,
        "trigger_signature": "+".join(trigger_names) if trigger_names else "UNRESOLVED",
        "confirmation_components": confirmations,
        "confirmation_signature": "+".join(confirmations) if confirmations else "UNRESOLVED",
        "confluence_components": confluence,
        "confluence_signature": "+".join(confluence) if confluence else "NONE",
        "confluence_count": int(feature["confluence_count"]),
        "structure_valid": structure,
        "dema200": dema,
        "dema_distance_pct": dema_distance_pct,
        "dema_distance_atr": dema_distance_atr,
        "rsi14": float(feature["rsi14"]) if _finite(feature["rsi14"]) else None,
        "supertrend_line": float(feature["supertrend_line"]),
        "supertrend_direction": int(feature["supertrend_direction"]),
        "atr14_geometry": atr,
    }


def run_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "15m",
    replay_fold_id: str = "UNKNOWN",
    cost_bps_per_side: float = 0.0,
    config: Optional[IntegratedSupertrendPullbackConfig] = None,
) -> Dict[str, Any]:
    cfg = config or IntegratedSupertrendPullbackConfig()
    cfg.validate()
    if timeframe != cfg.timeframe:
        raise ValueError("TIMEFRAME_NOT_15M")
    if not _finite(cost_bps_per_side) or float(cost_bps_per_side) < 0:
        raise ValueError("COST_BPS_INVALID")

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
    max_favorable_pct = 0.0
    max_adverse_pct = 0.0
    pending: Optional[Dict[str, Any]] = None
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
        nonlocal entry_context, active_stop, initial_stop, max_favorable_pct, max_adverse_pct
        if position_side == FLAT or entry_price is None or entry_bar is None:
            raise RuntimeError("CLOSE_WITHOUT_OPEN_POSITION")
        if position_side == LONG:
            gross_pct = (price - entry_price) / entry_price * 100.0
        else:
            gross_pct = (entry_price - price) / entry_price * 100.0
        round_trip_cost_pct = (2.0 * float(cost_bps_per_side)) / 100.0
        net_pct = gross_pct - round_trip_cost_pct
        context = dict(entry_context or {})
        stop_distance_pct = None
        invalid_initial_stop = None
        if initial_stop is not None:
            if position_side == LONG:
                stop_distance_pct = (entry_price - initial_stop) / entry_price * 100.0
                invalid_initial_stop = initial_stop >= entry_price
            else:
                stop_distance_pct = (initial_stop - entry_price) / entry_price * 100.0
                invalid_initial_stop = initial_stop <= entry_price
        giveback_from_mfe_pct = max_favorable_pct - gross_pct
        trades.append(
            {
                "strategy_id": STRATEGY_ID,
                "symbol": symbol,
                "timeframe": timeframe,
                "replay_fold_id": replay_fold_id,
                "side": position_side,
                "entry_ts": entry_ts,
                "exit_ts": _timestamp(validated, position),
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
                "giveback_from_mfe_pct": giveback_from_mfe_pct,
                "intrabar_path_unknown": bool(intrabar_path_unknown),
                "entry_context": context,
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
        max_favorable_pct = 0.0
        max_adverse_pct = 0.0

    for i in range(len(validated)):
        row = validated.iloc[i]
        feature = features.iloc[i]
        open_price = float(row["open"])

        if pending is not None:
            action = pending["action"]
            if action == ENTER_LONG and position_side == FLAT:
                position_side = LONG
                entry_price = open_price
                entry_ts = _timestamp(validated, i)
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
                entry_ts = _timestamp(validated, i)
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
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP", intrabar_path_unknown=True)
            events.append({"bar": i, "event": EXIT_LONG, "fill_price": stop_fill, "reason": "SUPERTREND_TRAILING_STOP"})
        elif position_side == SHORT and active_stop is not None and float(row["high"]) >= active_stop:
            stop_fill = max(open_price, active_stop)
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP", intrabar_path_unknown=True)
            events.append({"bar": i, "event": EXIT_SHORT, "fill_price": stop_fill, "reason": "SUPERTREND_TRAILING_STOP"})

        if _finite(feature["supertrend_line"]):
            line = float(feature["supertrend_line"])
            direction = int(feature["supertrend_direction"]) if _finite(feature["supertrend_direction"]) else 0
            if position_side == LONG and direction == 1:
                active_stop = line if active_stop is None else max(active_stop, line)
            elif position_side == SHORT and direction == -1:
                active_stop = line if active_stop is None else min(active_stop, line)

        if i >= len(validated) - 1 or pending is not None:
            continue

        if position_side == LONG and bool(feature["supertrend_flip_down"]):
            pending = {"action": EXIT_LONG, "signal_bar": i}
        elif position_side == SHORT and bool(feature["supertrend_flip_up"]):
            pending = {"action": EXIT_SHORT, "signal_bar": i}
        elif position_side == FLAT and bool(feature["long_entry_signal"]):
            pending = {
                "action": ENTER_LONG,
                "signal_bar": i,
                "stop": float(feature["supertrend_line"]),
                "context": _signal_context(validated, features, i, LONG),
            }
        elif position_side == FLAT and bool(feature["short_entry_signal"]):
            pending = {
                "action": ENTER_SHORT,
                "signal_bar": i,
                "stop": float(feature["supertrend_line"]),
                "context": _signal_context(validated, features, i, SHORT),
            }

    gross_returns = [float(trade["gross_return_pct"]) for trade in trades]
    net_returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = sum(value > 0 for value in net_returns)
    return {
        "strategy_id": STRATEGY_ID,
        "canonical_strategy_count": 1,
        "replay_profile_id": REPLAY_PROFILE_ID,
        "anatomy_schema_version": ANATOMY_SCHEMA_VERSION,
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
    parser = argparse.ArgumentParser(description="Research-only integrated Supertrend pullback replay")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--fold", default="UNKNOWN")
    parser.add_argument("--cost-bps-per-side", type=float, default=0.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    result = run_replay(
        _load_csv(Path(args.csv)),
        symbol=args.symbol,
        timeframe=args.timeframe,
        replay_fold_id=args.fold,
        cost_bps_per_side=args.cost_bps_per_side,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
