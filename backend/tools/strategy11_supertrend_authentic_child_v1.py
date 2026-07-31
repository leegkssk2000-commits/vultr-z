from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

VERSION = "STRATEGY11_SUPERTREND_AUTHENTIC_CHILD_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def wilder_rma_atr(frame: pd.DataFrame, length: int) -> pd.Series:
    if length < 2:
        raise ValueError("ATR_LENGTH_MIN_2")
    high = pd.to_numeric(frame["high"], errors="raise").astype(float)
    low = pd.to_numeric(frame["low"], errors="raise").astype(float)
    close = pd.to_numeric(frame["close"], errors="raise").astype(float)
    previous_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    atr = pd.Series(float("nan"), index=frame.index, dtype="float64")
    if len(frame) < length:
        return atr
    first = length - 1
    atr.iloc[first] = float(tr.iloc[:length].mean())
    for index in range(first + 1, len(frame)):
        atr.iloc[index] = ((atr.iloc[index - 1] * (length - 1)) + tr.iloc[index]) / length
    return atr


def authentic_supertrend(frame: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    if multiplier <= 0:
        raise ValueError("MULTIPLIER_POSITIVE_REQUIRED")
    high = pd.to_numeric(frame["high"], errors="raise").astype(float)
    low = pd.to_numeric(frame["low"], errors="raise").astype(float)
    close = pd.to_numeric(frame["close"], errors="raise").astype(float)
    atr = wilder_rma_atr(frame, length)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr
    final_upper = pd.Series(float("nan"), index=frame.index, dtype="float64")
    final_lower = pd.Series(float("nan"), index=frame.index, dtype="float64")
    direction = pd.Series(float("nan"), index=frame.index, dtype="float64")
    supertrend = pd.Series(float("nan"), index=frame.index, dtype="float64")
    valid = [index for index, value in enumerate(atr.notna().tolist()) if value]
    if not valid:
        return pd.DataFrame({
            "atr": atr,
            "final_upper": final_upper,
            "final_lower": final_lower,
            "direction": direction,
            "supertrend": supertrend,
        })
    start = valid[0]
    final_upper.iloc[start] = basic_upper.iloc[start]
    final_lower.iloc[start] = basic_lower.iloc[start]
    direction.iloc[start] = 1.0
    supertrend.iloc[start] = final_lower.iloc[start]
    for index in range(start + 1, len(frame)):
        previous_upper = final_upper.iloc[index - 1]
        previous_lower = final_lower.iloc[index - 1]
        upper = basic_upper.iloc[index]
        lower = basic_lower.iloc[index]
        if any(pd.isna(value) for value in (previous_upper, previous_lower, upper, lower)):
            raise RuntimeError(f"SUPERTREND_RECURSION_NAN:{index}")
        final_upper.iloc[index] = upper if (upper < previous_upper or close.iloc[index - 1] > previous_upper) else previous_upper
        final_lower.iloc[index] = lower if (lower > previous_lower or close.iloc[index - 1] < previous_lower) else previous_lower
        if supertrend.iloc[index - 1] == previous_upper:
            if close.iloc[index] <= final_upper.iloc[index]:
                direction.iloc[index] = -1.0
                supertrend.iloc[index] = final_upper.iloc[index]
            else:
                direction.iloc[index] = 1.0
                supertrend.iloc[index] = final_lower.iloc[index]
        else:
            if close.iloc[index] >= final_lower.iloc[index]:
                direction.iloc[index] = 1.0
                supertrend.iloc[index] = final_lower.iloc[index]
            else:
                direction.iloc[index] = -1.0
                supertrend.iloc[index] = final_upper.iloc[index]
    return pd.DataFrame({
        "atr": atr,
        "final_upper": final_upper,
        "final_lower": final_lower,
        "direction": direction,
        "supertrend": supertrend,
    })


def _close_trade(position: dict[str, Any], *, exit_price: float, exit_ts: str, reason: str, cost_rate: float) -> dict[str, Any]:
    side = str(position["side"])
    entry = float(position["entry_price"])
    gross = ((exit_price / entry) - 1.0) * 100.0 if side == "long" else ((entry - exit_price) / entry) * 100.0
    entry_cost = cost_rate * 100.0
    exit_cost = cost_rate * 100.0
    return {
        "window_id": position["window_id"],
        "symbol": position["symbol"],
        "side": side,
        "signal_ts": position["signal_ts"],
        "entry_ts": position["entry_ts"],
        "exit_ts": exit_ts,
        "entry_price": entry,
        "exit_price": float(exit_price),
        "gross_return_pct": gross,
        "entry_cost_pct": entry_cost,
        "exit_cost_pct": exit_cost,
        "net_return_pct": gross - entry_cost - exit_cost,
        "exit_reason": reason,
        "bars_held": int(position["bars_held"]),
    }


def replay_window(
    frame: pd.DataFrame,
    *,
    window_id: str,
    symbol: str,
    warmup_bars: int,
    length: int,
    multiplier: float,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    if len(frame) <= warmup_bars + 2:
        raise RuntimeError(f"FRAME_TOO_SHORT:{window_id}:{symbol}")
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp_ms"], unit="ms", utc=True)
    st = authentic_supertrend(data, length=length, multiplier=multiplier)
    direction = st["direction"]
    cost_rate = cost_bps_per_side / 10_000.0
    pending_side: str | None = None
    pending_signal_ts: str | None = None
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    flip_count = 0
    long_flip_count = 0
    short_flip_count = 0
    for index in range(warmup_bars, len(data)):
        row = data.iloc[index]
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()
        open_price = float(row["open"])
        if pending_side is not None:
            if position is not None and position["side"] != pending_side:
                trades.append(_close_trade(
                    position,
                    exit_price=open_price,
                    exit_ts=timestamp,
                    reason="OPPOSITE_CONFIRMED_FLIP",
                    cost_rate=cost_rate,
                ))
                position = None
            if position is None:
                position = {
                    "window_id": window_id,
                    "symbol": symbol,
                    "side": pending_side,
                    "signal_ts": pending_signal_ts,
                    "entry_ts": timestamp,
                    "entry_price": open_price,
                    "bars_held": 0,
                }
            pending_side = None
            pending_signal_ts = None
        if position is not None:
            position["bars_held"] += 1
        if index >= len(data) - 1:
            break
        current = direction.iloc[index]
        previous = direction.iloc[index - 1]
        if pd.isna(current) or pd.isna(previous) or current == previous:
            continue
        flip_count += 1
        pending_side = "long" if int(current) == 1 else "short"
        pending_signal_ts = timestamp
        if pending_side == "long":
            long_flip_count += 1
        else:
            short_flip_count += 1
    if position is not None:
        last = data.iloc[-1]
        trades.append(_close_trade(
            position,
            exit_price=float(last["close"]),
            exit_ts=pd.Timestamp(last["timestamp"]).isoformat(),
            reason="WINDOW_END",
            cost_rate=cost_rate,
        ))
    return {
        "window_id": window_id,
        "symbol": symbol,
        "flip_count": flip_count,
        "long_flip_count": long_flip_count,
        "short_flip_count": short_flip_count,
        "first_valid_atr_index": next((index for index, value in enumerate(st["atr"].notna().tolist()) if value), None),
        "post_seed_nan_count": int(st["supertrend"].iloc[length - 1:].isna().sum()),
        "trades": trades,
    }


def stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        trades,
        key=lambda row: (
            str(row["window_id"]),
            int(pd.Timestamp(row["entry_ts"]).value),
            str(row["symbol"]),
            str(row["side"]),
        ),
    )
    values = [float(row["net_return_pct"]) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = peak = max_dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    gross_loss = abs(sum(losses))
    average_win = sum(wins) / len(wins) if wins else None
    average_loss = abs(sum(losses) / len(losses)) if losses else None
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else None,
        "net_return_pct_sum": sum(values),
        "net_profit_factor": sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else None),
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss not in (None, 0.0) else None,
        "max_drawdown_pct": max_dd,
    }


def run(args: argparse.Namespace) -> int:
    archive_root = Path(args.archive_root).resolve()
    manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "PASS_EXPANDED_ARCHIVE" or manifest.get("evaluation_periods_non_overlapping") is not True:
        raise RuntimeError("ARCHIVE_AUTHORITY_INVALID")
    rows: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    for item in manifest["rows"]:
        frame = pd.read_csv(archive_root / item["path"])
        kwargs = {
            "window_id": str(item["window_id"]),
            "symbol": str(item["symbol"]),
            "warmup_bars": int(manifest["warmup_bars"]),
            "length": args.length,
            "multiplier": args.multiplier,
            "cost_bps_per_side": args.cost_bps_per_side,
        }
        first = replay_window(frame, **kwargs)
        second = replay_window(frame, **kwargs)
        if stable_sha(first) != stable_sha(second):
            raise RuntimeError(f"AB_PARITY_FAIL:{item['window_id']}:{item['symbol']}")
        rows.append({key: value for key, value in first.items() if key != "trades"})
        all_trades.extend(first["trades"])
    keys = [
        (row["window_id"], row["symbol"], row["side"], row["entry_ts"], row["exit_ts"])
        for row in all_trades
    ]
    duplicate_count = len(keys) - len(set(keys))
    if duplicate_count:
        raise RuntimeError(f"DUPLICATE_TRADES:{duplicate_count}")
    combined = stats(all_trades)
    long_stats = stats([row for row in all_trades if row["side"] == "long"])
    short_stats = stats([row for row in all_trades if row["side"] == "short"])
    window_stats = {
        window: stats([row for row in all_trades if row["window_id"] == window])
        for window in sorted({row["window_id"] for row in all_trades})
    }
    symbol_stats = {
        symbol: stats([row for row in all_trades if row["symbol"] == symbol])
        for symbol in sorted({row["symbol"] for row in all_trades})
    }
    positive_windows = sum(float(value["net_return_pct_sum"]) > 0 for value in window_stats.values())
    positive_symbols = sum(float(value["net_return_pct_sum"]) > 0 for value in symbol_stats.values())
    result = {
        "schema_version": "strategy11.supertrend_authentic_child.v1",
        "version": VERSION,
        "state": "PASS_AUTHENTIC_BIDIRECTIONAL_REPLAY_COMPLETE",
        "strategy_id": "supertrend_flip_authentic",
        "contract": {
            "true_range": "MAX(H-L,ABS(H-PREV_CLOSE),ABS(L-PREV_CLOSE))",
            "atr": "WILDER_RMA",
            "atr_length": args.length,
            "source": "HL2",
            "multiplier": args.multiplier,
            "band_recurrence": True,
            "confirmed_close_flip": True,
            "entry_timing": "NEXT_BAR_OPEN",
            "long_rule": "DIRECTION_-1_TO_+1",
            "short_rule": "DIRECTION_+1_TO_-1",
            "exit_rule": "OPPOSITE_FLIP_REVERSE",
            "fixed_tp": False,
            "fixed_sl": False,
            "ema_gate": False,
            "pullback_gate": False,
            "reclaim_gate": False,
            "beam_gate": False,
            "add_scale_in": False,
            "segment_forced_exit": False,
        },
        "archive": {
            "archive_sha256": manifest["archive_sha256"],
            "window_count": manifest["window_count"],
            "symbol_count": manifest["symbol_count"],
            "total_symbol_bars": manifest["total_symbol_bars"],
            "evaluation_symbol_bars": manifest["evaluation_symbol_bars"],
            "warmup_bars": manifest["warmup_bars"],
        },
        "cost_bps_per_side": args.cost_bps_per_side,
        "row_count": len(rows),
        "flip_count": sum(row["flip_count"] for row in rows),
        "long_flip_count": sum(row["long_flip_count"] for row in rows),
        "short_flip_count": sum(row["short_flip_count"] for row in rows),
        "post_seed_nan_count": sum(row["post_seed_nan_count"] for row in rows),
        "duplicate_trade_count": duplicate_count,
        "ab_parity": "PASS",
        "combined": combined,
        "long_only": long_stats,
        "short_only": short_stats,
        "positive_window_count": positive_windows,
        "positive_symbol_count": positive_symbols,
        "window_stats": window_stats,
        "symbol_stats": symbol_stats,
        "rows": rows,
        "trades": sorted(
            all_trades,
            key=lambda row: (
                str(row["window_id"]),
                int(pd.Timestamp(row["entry_ts"]).value),
                str(row["symbol"]),
                str(row["side"]),
            ),
        ),
        "economic_state": (
            "POSITIVE_DISCOVERY_UNCONFIRMED"
            if combined["net_return_pct_sum"] > 0 and (combined["net_profit_factor"] or 0) > 1
            else "NEGATIVE_OR_NO_EDGE_DISCOVERY"
        ),
        "fresh_confirmation_required": True,
        "w1_w2_w3_new_sealed_required": True,
        "legacy_parent_modified": False,
        **SAFETY,
    }
    result["result_sha256"] = stable_sha(result)
    out = Path(args.out).resolve()
    write_json(out / "final.json", result)
    write_json(out / "contract.json", {
        "strategy_id": result["strategy_id"],
        "contract": result["contract"],
        **SAFETY,
    })
    pd.DataFrame(result["trades"]).to_csv(out / "trades.csv", index=False)
    print(json.dumps({
        "state": result["state"],
        "trades": combined["trade_count"],
        "net": combined["net_return_pct_sum"],
        "pf": combined["net_profit_factor"],
        "dd": combined["max_drawdown_pct"],
        "positive_windows": positive_windows,
        "positive_symbols": positive_symbols,
        "sha": result["result_sha256"],
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--length", type=int, default=10)
    parser.add_argument("--multiplier", type=float, default=3.0)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
