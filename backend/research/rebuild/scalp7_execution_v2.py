"""Causal research fills for frozen Scalp7 opportunities; no order interface."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

ExitUpdate = Callable[[dict[str, Any], Any, Any], dict[str, Any]]
TF_ALLOWED = (15, 30)


def _finite(value: Any, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("NONFINITE:" + name)
    return out


def _integer(value: Any, name: str) -> int:
    out = int(value)
    if float(value) != out:
        raise ValueError("NONINTEGER:" + name)
    return out


def validate_signal(signal: Mapping[str, Any]) -> None:
    for name in ("identity", "lane", "symbol"):
        if not isinstance(signal.get(name), str) or not signal[name]:
            raise ValueError("SIGNAL_MISSING:" + name)
    tf = _integer(signal["timeframe_min"], "timeframe_min")
    if tf not in TF_ALLOWED:
        raise ValueError("SCALP7_DECISION_TIMEFRAME_REQUIRED")
    opened = _integer(signal["signal_open_ts_ms"], "signal_open_ts_ms")
    closed = _integer(signal["signal_ts_ms"], "signal_ts_ms")
    if opened % (tf * 60_000) or closed < opened + tf * 60_000:
        raise ValueError("SIGNAL_NOT_COMPLETED_UTC_BAR")
    if _integer(signal["max_hold_bars"], "max_hold_bars") < 1:
        raise ValueError("MAX_HOLD_REQUIRED")
    for name in ("take_profit_r", "partial_take_profit_r"):
        if signal.get(name) is not None and _finite(signal[name], name) <= 0:
            raise ValueError("POSITIVE_TARGET_R_REQUIRED")
    if signal.get("legs"):
        legs = signal["legs"]
        names = [str(leg["symbol"]) for leg in legs]
        if len(names) != len(set(names)) or len(names) < 2:
            raise ValueError("PAIR_LEGS_INVALID")
        if any(leg["side"] not in (-1, 1) for leg in legs):
            raise ValueError("SIDE_INVALID")
        weights = [_finite(leg["weight"], "weight") for leg in legs]
        if min(weights) <= 0 or abs(sum(weights) - 1) > 1e-9:
            raise ValueError("GROSS_ONE_WEIGHTS_REQUIRED")
    else:
        if signal["side"] not in (-1, 1):
            raise ValueError("SIDE_INVALID")
        if _finite(signal["stop_price"], "stop_price") <= 0:
            raise ValueError("STOP_INVALID")


def default_exit(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    del history
    level = position["signal"].get("invalidation_price")
    invalid = (
        level is not None
        and position["side"] * (float(bar["close"]) - float(level)) < 0
    )
    return {"exit_next_open": invalid, "reason": "STRUCTURAL_CLOSE"}


def _frame_records(
    frame: pd.DataFrame, tf: int
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    required = (
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    )
    if any(name not in frame for name in required):
        raise ValueError("CANDLE_SCHEMA_INCOMPLETE")
    rows = frame.to_dict("records")
    previous = -1
    for row in rows:
        stamp = _integer(row["open_ts_ms"], "open_ts_ms")
        if stamp <= previous or stamp % (tf * 60_000):
            raise ValueError("CANDLE_DUPLICATE_UNSORTED_OR_UNALIGNED")
        if _integer(row["close_ts_ms"], "close_ts_ms") != stamp + tf * 60_000:
            raise ValueError("CANDLE_CLOSE_TIME_INVALID")
        if _integer(row["available_ts_ms"], "available_ts_ms") < row["close_ts_ms"]:
            raise ValueError("CANDLE_AVAILABLE_BEFORE_CLOSE")
        o, h, low, c = [_finite(row[k], k) for k in ("open", "high", "low", "close")]
        if min(o, h, low, c) <= 0 or low > min(o, c) or h < max(o, c) or low > h:
            raise ValueError("CANDLE_OHLC_INVALID")
        previous = stamp
    return rows, {int(row["open_ts_ms"]): i for i, row in enumerate(rows)}


def _can_follow(previous: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return (
        row["open_ts_ms"] == previous["close_ts_ms"]
        and row["segment_id"] == previous["segment_id"]
    )


def _cost(signal: Mapping[str, Any], costs: Mapping[str, float]) -> float:
    legs = signal.get("legs") or [{"symbol": signal["symbol"], "weight": 1}]
    for leg in legs:
        if _finite(costs[str(leg["symbol"])], "leg_cost") <= 0:
            raise ValueError("POSITIVE_AUTHORIZED_LEG_COST_REQUIRED")
    value = sum(
        float(leg["weight"]) * _finite(costs[str(leg["symbol"])], "cost")
        for leg in legs
    )
    if value <= 0:
        raise ValueError("POSITIVE_AUTHORIZED_COST_REQUIRED")
    return value


def _close_row(
    position: dict[str, Any],
    exit_prices: Mapping[str, float],
    exit_ts: int,
    available_ts: int,
    reason: str,
) -> dict[str, Any]:
    signal = position["signal"]
    legs = signal.get("legs") or [
        {"symbol": signal["symbol"], "weight": 1.0, "side": signal["side"]}
    ]
    terminal = sum(
        float(leg["weight"])
        * int(leg["side"])
        * (
            exit_prices[str(leg["symbol"])]
            / position["entry_prices"][str(leg["symbol"])]
            - 1
        )
        * 10_000
        for leg in legs
    )
    gross = position["realized_parts_bps"] + position["remaining"] * terminal
    row = {
        **{
            k: signal[k]
            for k in (
                "identity",
                "lane",
                "symbol",
                "timeframe_min",
                "signal_open_ts_ms",
                "signal_ts_ms",
            )
        },
        "side": signal.get("side", 0),
        "entry_ts_ms": position["entry_ts_ms"],
        "exit_ts_ms": exit_ts,
        "outcome_available_ts_ms": available_ts,
        "entry_prices": position["entry_prices"],
        "exit_prices": dict(exit_prices),
        "gross_bps": gross,
        "cost_bps": position["cost_bps"],
        "net_bps": gross - position["cost_bps"],
        "reason": reason,
        "hold_bars": position["hold_bars"],
        "hold_minutes": (exit_ts - position["entry_ts_ms"]) / 60_000,
        "mfe_R": position["mfe_R"],
        "mae_R": position["mae_R"],
        "mfe_mae_semantics": "AFTER_STOP_CHECK_CONSERVATIVE_NO_INTRABAR_PATH",
        "regime": signal.get("meta", {}).get("regime", "UNCLASSIFIED"),
        "signal": signal,
        "execution_profile": "UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2",
        "outcome_time_precision": "BAR_CLOSE" if available_ts > exit_ts else "OPEN",
        "order_authority": "BLOCKED",
    }
    if signal.get("legs"):
        row["legs"] = signal["legs"]
    return row


def _single(
    signal: dict[str, Any],
    frame: pd.DataFrame,
    rows: list[dict[str, Any]],
    index: dict[int, int],
    cost: float,
    callback: ExitUpdate,
    entry_update: Callable[[dict[str, Any], float], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int, str | None]:
    i = index.get(int(signal["signal_open_ts_ms"]))
    if i is None:
        return None, None, -1, "SIGNAL_BAR_MISSING"
    source = rows[i]
    if source["segment_id"] != signal["segment_id"]:
        return None, None, -1, "SIGNAL_SEGMENT_MISMATCH"
    if signal["signal_ts_ms"] < source["available_ts_ms"]:
        return None, None, -1, "SIGNAL_BEFORE_FEATURE_AVAILABILITY"
    if i + 1 >= len(rows):
        return None, None, -1, "NO_NEXT_BAR"
    entry_bar = rows[i + 1]
    if not _can_follow(source, entry_bar):
        return None, None, -1, "ENTRY_GAP"
    if signal["signal_ts_ms"] > entry_bar["open_ts_ms"]:
        return None, None, -1, "LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"
    entry = float(entry_bar["open"])
    side = int(signal["side"])
    stop = float(signal["stop_price"])
    if entry_update is not None:
        update = entry_update(signal, entry)
        if update.get("reject"):
            return None, None, -1, str(update.get("reason", update["reject"]))
        stop = _finite(update.get("stop_price", stop), "entry_stop")
    gate = signal.get("meta", {}).get("entry_cost_gate")
    if gate and float(gate["atr_price"]) / entry * 10_000 / cost < float(
        gate["min_ratio"]
    ):
        return None, None, -1, "AT_FILL_COST_GATE"
    fallback = signal.get("meta", {}).get("stop_fallback_atr_price")
    if side * (entry - stop) <= 0 and fallback is not None:
        stop = entry - side * float(fallback)
    if not math.isfinite(stop) or stop <= 0:
        return None, None, -1, "ENTRY_STOP_INVALID"
    risk = side * (entry - stop)
    if risk <= 0:
        return None, None, -1, "ENTRY_INVALIDATES_STOP"
    position: dict[str, Any] = {
        "signal": signal,
        "side": side,
        "entry_price": entry,
        "entry_prices": {signal["symbol"]: entry},
        "entry_ts_ms": int(entry_bar["open_ts_ms"]),
        "stop_price": stop,
        "initial_stop": stop,
        "initial_risk": risk,
        "hold_bars": 0,
        "mfe_R": 0.0,
        "mae_R": 0.0,
        "cost_bps": cost,
        "remaining": 1.0,
        "realized_parts_bps": 0.0,
    }
    tp_r = signal.get("take_profit_r")
    target = entry + side * risk * float(tp_r) if tp_r is not None else None
    pending: str | None = None
    previous = source
    for j in range(i + 1, len(rows)):
        bar = rows[j]
        if not _can_follow(previous, bar):
            break
        opened = int(bar["open_ts_ms"])
        if pending:
            out = _close_row(
                position,
                {signal["symbol"]: float(bar["open"])},
                opened,
                opened,
                pending,
            )
            return out, None, opened, None
        position["hold_bars"] += 1
        stop = float(position["stop_price"])
        o, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
        stop_hit = low <= stop if side == 1 else high >= stop
        if stop_hit:
            gap = side * (o - stop) < 0
            px = o if gap else stop
            out = _close_row(
                position,
                {signal["symbol"]: px},
                opened if gap else int(bar["close_ts_ms"]),
                opened if gap else int(bar["available_ts_ms"]),
                "OPEN_GAP_STOP" if gap else "STOP_FIRST",
            )
            return (
                out,
                None,
                max(int(bar["close_ts_ms"]), int(bar["available_ts_ms"])),
                None,
            )
        if target is not None and (high >= target if side == 1 else low <= target):
            # Favorable gaps conservatively receive the resting target price.
            out = _close_row(
                position,
                {signal["symbol"]: target},
                int(bar["close_ts_ms"]),
                int(bar["available_ts_ms"]),
                "TARGET",
            )
            return (
                out,
                None,
                max(int(bar["close_ts_ms"]), int(bar["available_ts_ms"])),
                None,
            )
        favorable = (high - entry) / risk if side == 1 else (entry - low) / risk
        adverse = (entry - low) / risk if side == 1 else (high - entry) / risk
        position["mfe_R"] = max(position["mfe_R"], favorable)
        position["mae_R"] = max(position["mae_R"], adverse)
        if int(bar["available_ts_ms"]) > int(bar["close_ts_ms"]):
            previous = bar
            position["unresolved_reason"] = "LATE_BAR_AVAILABILITY"
            break
        update = callback(position, bar, frame.iloc[: j + 1])
        # Partial prices may be a frozen resting limit; callbacks cannot invent
        # a favorable fill beyond the observed complete-bar range.
        fraction = float(update.get("partial_fraction", 0.0))
        if fraction:
            partial_px = _finite(update["partial_price"], "partial_price")
            declared_r = signal.get("partial_take_profit_r")
            declared_fraction = signal.get("partial_fraction")
            expected_px = entry + side * risk * float(declared_r or 0)
            if (
                declared_r is None
                or declared_fraction is None
                or position.get("partial_executed", False)
                or abs(fraction - float(declared_fraction)) > 1e-12
                or abs(partial_px - expected_px) > max(1e-10, entry * 1e-12)
                or not 0 < fraction < position["remaining"]
                or not (high >= partial_px if side == 1 else low <= partial_px)
            ):
                raise ValueError("PARTIAL_FILL_INVALID")
            position["realized_parts_bps"] += (
                fraction * side * (partial_px / entry - 1) * 10_000
            )
            position["remaining"] -= fraction
            position["partial_executed"] = True
        new_stop = update.get("next_stop")
        if new_stop is not None:
            value = _finite(new_stop, "next_stop")
            if value <= 0:
                raise ValueError("STOP_UPDATE_INVALID")
            position["stop_price"] = max(stop, value) if side == 1 else min(stop, value)
        if update.get("exit_next_open"):
            pending = str(update.get("reason", "CAUSAL_CLOSE_EXIT"))
        elif position["hold_bars"] >= int(signal["max_hold_bars"]):
            pending = "MAX_HOLD_NEXT_OPEN"
        previous = bar
    unresolved = {
        "identity": signal["identity"],
        "symbol": signal["symbol"],
        "entry_ts_ms": position["entry_ts_ms"],
        "last_observed_close_ts_ms": int(previous["close_ts_ms"]),
        "state": "UNRESOLVED_GAP_OR_END",
        "position": position,
        "exclusion": "NO_SYNTHETIC_EXIT_NO_REALIZED_PNL",
    }
    # After a gap the old position is unresolved and retains ownership forever.
    return None, unresolved, 2**63 - 1, None


def _pair(
    signal: dict[str, Any],
    frames: Mapping[str, pd.DataFrame],
    records: Mapping[str, list[dict[str, Any]]],
    indexes: Mapping[str, dict[int, int]],
    cost: float,
    callback: ExitUpdate,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int, str | None]:
    names = [str(leg["symbol"]) for leg in signal["legs"]]
    stamp = int(signal["signal_open_ts_ms"])
    offsets = {name: indexes[name].get(stamp) for name in names}
    if any(value is None for value in offsets.values()):
        return None, None, -1, "PAIR_SIGNAL_BAR_MISSING"
    starts = {name: int(value) for name, value in offsets.items() if value is not None}
    source = {name: records[name][starts[name]] for name in names}
    bindings = signal.get("meta", {}).get("pair_segment_ids")
    if bindings and any(name not in bindings for name in names):
        return None, None, -1, "PAIR_SIGNAL_SEGMENT_UNBOUND"
    if not bindings and len({str(row["segment_id"]) for row in source.values()}) != 1:
        return None, None, -1, "PAIR_SIGNAL_SEGMENT_UNBOUND"
    if bindings and any(
        str(bindings[name]) != str(source[name]["segment_id"]) for name in names
    ):
        return None, None, -1, "PAIR_SIGNAL_SEGMENT_MISMATCH"
    if not bindings and len({str(row["segment_id"]) for row in source.values()}) == 1:
        if str(signal["segment_id"]) != str(source[names[0]]["segment_id"]):
            return None, None, -1, "PAIR_SIGNAL_SEGMENT_MISMATCH"
    if signal["signal_ts_ms"] < max(row["available_ts_ms"] for row in source.values()):
        return None, None, -1, "SIGNAL_BEFORE_FEATURE_AVAILABILITY"
    if any(starts[name] + 1 >= len(records[name]) for name in names):
        return None, None, -1, "NO_NEXT_PAIR_BAR"
    entries = {name: records[name][starts[name] + 1] for name in names}
    entry_stamp = stamp + int(signal["timeframe_min"]) * 60_000
    if any(
        not _can_follow(source[name], entries[name])
        or entries[name]["open_ts_ms"] != entry_stamp
        for name in names
    ):
        return None, None, -1, "ENTRY_PAIR_GAP"
    if signal["signal_ts_ms"] > entry_stamp:
        return None, None, -1, "LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"
    position: dict[str, Any] = {
        "signal": signal,
        "entry_prices": {name: float(entries[name]["open"]) for name in names},
        "entry_ts_ms": entry_stamp,
        "hold_bars": 0,
        "mfe_R": None,
        "mae_R": None,
        "cost_bps": cost,
        "remaining": 1.0,
        "realized_parts_bps": 0.0,
    }
    pending: str | None = None
    previous = source
    for offset in range(1, min(len(records[name]) - starts[name] for name in names)):
        bar = {name: records[name][starts[name] + offset] for name in names}
        if any(not _can_follow(previous[name], bar[name]) for name in names):
            break
        if len({row["open_ts_ms"] for row in bar.values()}) != 1:
            break
        opened = int(bar[names[0]]["open_ts_ms"])
        if pending:
            out = _close_row(
                position,
                {name: float(bar[name]["open"]) for name in names},
                opened,
                opened,
                pending,
            )
            return out, None, opened, None
        position["hold_bars"] += 1
        history = {
            name: frames[name].iloc[: starts[name] + offset + 1] for name in names
        }
        if any(
            int(row["available_ts_ms"]) > int(row["close_ts_ms"])
            for row in bar.values()
        ):
            previous = bar
            position["unresolved_reason"] = "LATE_BAR_AVAILABILITY"
            break
        update = callback(position, bar, history)
        if update.get("exit_next_open"):
            pending = str(update.get("reason", "PAIR_THESIS_EXIT"))
        elif position["hold_bars"] >= int(signal["max_hold_bars"]):
            pending = "MAX_HOLD_NEXT_OPEN"
        previous = bar
    unresolved = {
        "identity": signal["identity"],
        "symbol": signal["symbol"],
        "entry_ts_ms": entry_stamp,
        "state": "UNRESOLVED_PAIR_GAP_OR_END",
        "position": position,
        "exclusion": "NO_SYNTHETIC_EXIT_NO_REALIZED_PNL",
    }
    return None, unresolved, 2**63 - 1, None


def replay(
    signals: list[dict[str, Any]],
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    *,
    exit_update: ExitUpdate = default_exit,
    identity: str | None = None,
    entry_update: Callable[[dict[str, Any], float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replay each identity independently; never pool or select competing children."""
    selected = [s for s in signals if identity is None or s["identity"] == identity]
    for signal in selected:
        validate_signal(signal)
    timeframes = {int(s["timeframe_min"]) for s in selected}
    if len(timeframes) > 1:
        raise ValueError("ONE_TIMEFRAME_PER_REPLAY")
    if timeframes:
        tf = next(iter(timeframes))
    else:
        intervals = {
            int(frame.iloc[0]["close_ts_ms"] - frame.iloc[0]["open_ts_ms"]) // 60_000
            for frame in frames.values()
            if not frame.empty
        }
        if len(intervals) > 1 or intervals - set(TF_ALLOWED):
            raise ValueError("ONE_SCALP7_FRAME_TIMEFRAME_REQUIRED")
        tf = next(iter(intervals), 30)
    prepared = {name: _frame_records(frame, tf) for name, frame in frames.items()}
    records = {name: values[0] for name, values in prepared.items()}
    indexes = {name: values[1] for name, values in prepared.items()}
    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    ownership: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, int]] = set()
    for signal in sorted(
        selected,
        key=lambda x: (x["signal_ts_ms"], x["identity"], x["symbol"], x.get("side", 0)),
    ):
        key = (
            str(signal["identity"]),
            str(signal["symbol"]),
            int(signal["signal_ts_ms"]),
        )
        if key in seen:
            rejected["DUPLICATE_SIGNAL"] += 1
            continue
        seen.add(key)
        pair = bool(signal.get("legs"))
        owner = (
            str(signal["identity"]),
            "PAIR_GLOBAL" if pair else str(signal["symbol"]),
        )
        if int(signal["signal_ts_ms"]) < ownership.get(owner, -1):
            rejected["POSITION_ALREADY_OWNED"] += 1
            continue
        cost = _cost(signal, costs)
        if pair:
            row, open_position, until, reason = _pair(
                signal, frames, records, indexes, cost, exit_update
            )
        else:
            symbol = str(signal["symbol"])
            row, open_position, until, reason = _single(
                signal,
                frames[symbol],
                records[symbol],
                indexes[symbol],
                cost,
                exit_update,
                entry_update,
            )
        if reason:
            rejected[reason] += 1
            continue
        ownership[owner] = until
        if row:
            rows.append(row)
        if open_position:
            unresolved.append(open_position)
    rows.sort(key=lambda x: (x["outcome_available_ts_ms"], x["identity"], x["symbol"]))
    return {
        "schema": "zel.scalp7.causal_execution.v2",
        "trades": rows,
        "unresolved": unresolved,
        "rejections": dict(rejected),
        "signal_count": len(selected),
        "closed_trade_count": len(rows),
        "execution_profile": "UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2",
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
