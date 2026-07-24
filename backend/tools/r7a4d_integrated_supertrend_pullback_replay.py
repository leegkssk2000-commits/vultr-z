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
    active_stop: Optional[float] = None
    pending: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    def close_trade(position: int, price: float, reason: str) -> None:
        nonlocal position_side, entry_price, entry_ts, active_stop
        if position_side == FLAT or entry_price is None:
            raise RuntimeError("CLOSE_WITHOUT_OPEN_POSITION")
        if position_side == LONG:
            gross_pct = (price - entry_price) / entry_price * 100.0
        else:
            gross_pct = (entry_price - price) / entry_price * 100.0
        round_trip_cost_pct = (2.0 * float(cost_bps_per_side)) / 100.0
        net_pct = gross_pct - round_trip_cost_pct
        trades.append(
            {
                "strategy_id": STRATEGY_ID,
                "symbol": symbol,
                "timeframe": timeframe,
                "replay_fold_id": replay_fold_id,
                "side": position_side,
                "entry_ts": entry_ts,
                "exit_ts": _timestamp(validated, position),
                "entry_price": entry_price,
                "exit_price": float(price),
                "exit_reason": reason,
                "gross_return_pct": gross_pct,
                "net_return_pct": net_pct,
                "cost_bps_per_side": float(cost_bps_per_side),
            }
        )
        position_side = FLAT
        entry_price = None
        entry_ts = None
        active_stop = None

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
                active_stop = float(pending["stop"])
                events.append({"bar": i, "event": ENTER_LONG, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == ENTER_SHORT and position_side == FLAT:
                position_side = SHORT
                entry_price = open_price
                entry_ts = _timestamp(validated, i)
                active_stop = float(pending["stop"])
                events.append({"bar": i, "event": ENTER_SHORT, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == EXIT_LONG and position_side == LONG:
                close_trade(i, open_price, "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN")
                events.append({"bar": i, "event": EXIT_LONG, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            elif action == EXIT_SHORT and position_side == SHORT:
                close_trade(i, open_price, "OPPOSITE_SUPERTREND_FLIP_NEXT_OPEN")
                events.append({"bar": i, "event": EXIT_SHORT, "fill_price": open_price, "signal_bar": pending["signal_bar"]})
            pending = None

        if position_side == LONG and active_stop is not None and float(row["low"]) <= active_stop:
            stop_fill = min(open_price, active_stop)
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP")
            events.append({"bar": i, "event": EXIT_LONG, "fill_price": stop_fill, "reason": "SUPERTREND_TRAILING_STOP"})
        elif position_side == SHORT and active_stop is not None and float(row["high"]) >= active_stop:
            stop_fill = max(open_price, active_stop)
            close_trade(i, stop_fill, "SUPERTREND_TRAILING_STOP")
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
            pending = {"action": ENTER_LONG, "signal_bar": i, "stop": float(feature["supertrend_line"])}
        elif position_side == FLAT and bool(feature["short_entry_signal"]):
            pending = {"action": ENTER_SHORT, "signal_bar": i, "stop": float(feature["supertrend_line"])}

    gross_returns = [float(trade["gross_return_pct"]) for trade in trades]
    net_returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = sum(value > 0 for value in net_returns)
    return {
        "strategy_id": STRATEGY_ID,
        "canonical_strategy_count": 1,
        "replay_profile_id": REPLAY_PROFILE_ID,
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
            "active_stop": active_stop,
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
