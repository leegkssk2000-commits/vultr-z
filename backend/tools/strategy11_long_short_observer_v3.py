from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

VERSION = "STRATEGY11_LONG_SHORT_OBSERVER_V3_2"
LOSS_EPSILON = 1e-12


@dataclass
class Position:
    side: str
    entry: float
    sl: float
    tp: float
    qty: float
    opened_at: str
    entry_cost_pct: float


def metric(value: Any, default: float = 0.0) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return default
    return output if math.isfinite(output) else default


def timestamp_iso(row: pd.Series) -> str:
    if "timestamp" in row and pd.notna(row.get("timestamp")):
        return pd.Timestamp(row.get("timestamp")).isoformat()
    return pd.Timestamp(row.get("timestamp_ms"), unit="ms", tz="UTC").isoformat()


def close_trade(position: Position, price: float, timestamp: str, reason: str, cost_rate: float) -> dict[str, Any]:
    direction = 1.0 if position.side == "long" else -1.0
    gross = position.qty * direction * ((price / position.entry) - 1.0) * 100.0
    return {"side": position.side, "entry_ts": position.opened_at, "exit_ts": timestamp, "entry_price": position.entry, "exit_price": price, "net_return_pct": gross - position.entry_cost_pct - position.qty * cost_rate * 100.0, "exit_reason": reason}


def chronological(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(trades, key=lambda row: (str(row.get("window_id") or ""), str(row.get("entry_ts") or ""), str(row.get("exit_ts") or ""), str(row.get("symbol") or ""), str(row.get("side") or "")))


def stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = chronological(trades)
    values = [metric(row.get("net_return_pct")) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    gross_loss = abs(sum(losses))
    profit_factor = sum(wins) / gross_loss if gross_loss > LOSS_EPSILON else (999.0 if wins else 0.0)
    return {"trade_count": len(values), "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0, "net_return_pct_sum": sum(values), "net_profit_factor": profit_factor, "max_drawdown_pct": drawdown}


def replay(frame: pd.DataFrame, strategy: Callable[..., dict[str, Any]], *, warmup_bars: int, history_bars: int, cost_bps_per_side: float) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    position: Position | None = None
    pending: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    ignored_add_reduce = 0
    for index in range(warmup_bars, len(frame)):
        row = frame.iloc[index]
        timestamp = timestamp_iso(row)
        open_, high, low, close = (metric(row[key]) for key in ("open", "high", "low", "close"))
        if pending is not None and position is None:
            side = str(pending.get("side") or "").lower()
            signal_entry, signal_sl, signal_tp = (metric(pending.get(key)) for key in ("entry", "sl", "tp"))
            qty = metric(pending.get("size"))
            risk = (signal_entry - signal_sl) if side == "long" else (signal_sl - signal_entry)
            reward = (signal_tp - signal_entry) if side == "long" else (signal_entry - signal_tp)
            if side in {"long", "short"} and risk > 0 and reward > 0 and qty > 0:
                sl = open_ - risk if side == "long" else open_ + risk
                tp = open_ + reward if side == "long" else open_ - reward
                position = Position(side, open_, sl, tp, qty, timestamp, qty * cost_rate * 100.0)
            pending = None
        if position is not None:
            hit_sl = low <= position.sl if position.side == "long" else high >= position.sl
            hit_tp = high >= position.tp if position.side == "long" else low <= position.tp
            if hit_sl or hit_tp:
                price = position.sl if hit_sl else position.tp
                reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
                trades.append(close_trade(position, price, timestamp, reason, cost_rate))
                position = None
        if index >= len(frame) - 1:
            break
        history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
        state = {"position_side": position.side if position else "", "position_qty": position.qty if position else 0.0, "avg_entry": position.entry if position else 0.0, "add_count": 0, "last_add_price": position.entry if position else 0.0}
        result = strategy(history, state=state, risk_action="hold")
        action = str(result.get("action") or "hold").lower()
        if action in {"add", "reduce"}:
            ignored_add_reduce += 1
        elif position is None and action == "enter" and str(result.get("side") or "").lower() in {"long", "short"}:
            pending = dict(result)
    if position is not None:
        last = frame.iloc[-1]
        timestamp = timestamp_iso(last)
        trades.append(close_trade(position, metric(last["close"]), timestamp, "WINDOW_END", cost_rate))
    ordered = chronological(trades)
    long_rows = [row for row in ordered if row["side"] == "long"]
    short_rows = [row for row in ordered if row["side"] == "short"]
    return {"state": "PASS_OBSERVER_ONLY", "combined": stats(ordered), "long": stats(long_rows), "short": stats(short_rows), "trades": ordered, "ignored_add_reduce": ignored_add_reduce, "promotion_authority": False, "execution_allowed": False, "order_authority": "BLOCKED"}
