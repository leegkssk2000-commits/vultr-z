#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SYMBOLS = ("XRPUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = (5, 15)
COSTS_BPS = (0.0, 2.0, 4.0, 6.0, 8.0, 10.0)
STRATEGY_TYPE = "Pullback"
QTY_PCT = 1.0
STOP_PCT = 1.0
TAKE_PCT = 1.0


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_symbol(value: str) -> str:
    return "".join(char for char in str(value).upper() if char.isalnum())


def timestamp_ms(value: Any) -> int:
    if isinstance(value, str):
        text = value.strip()
        try:
            numeric = float(text)
        except ValueError:
            parsed = pd.Timestamp(text)
            parsed = parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")
            return int(parsed.timestamp() * 1000)
    else:
        numeric = float(value)
    if not math.isfinite(numeric):
        raise AuditError("TIMESTAMP_NONFINITE")
    if abs(numeric) < 10_000_000_000:
        numeric *= 1000.0
    return int(round(numeric))


def find_rows(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    queue: List[Any] = [payload]
    seen: set[int] = set()
    while queue:
        item = queue.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, list):
            return item
        if isinstance(item, Mapping):
            for key in ("data", "rows", "candles", "klines", "list", "result"):
                if key not in item:
                    continue
                value = item[key]
                if isinstance(value, list):
                    return value
                if isinstance(value, Mapping):
                    queue.append(value)
            queue.extend(value for value in item.values() if isinstance(value, (list, Mapping)))
    raise AuditError("MARKET_ROWS_NOT_FOUND")


def row_record(row: Any) -> Dict[str, Any]:
    if isinstance(row, Mapping):
        ts_value = next(
            (
                row[key]
                for key in ("time", "timestamp", "ts", "open_time", "openTime", "start", "startTime", "t")
                if key in row
            ),
            None,
        )
        if ts_value is None:
            raise AuditError("ROW_TIMESTAMP_MISSING")

        def pick(*keys: str) -> Any:
            for key in keys:
                if key in row:
                    return row[key]
            raise AuditError(f"ROW_FIELD_MISSING:{keys[0]}")

        return {
            "ts_ms": timestamp_ms(ts_value),
            "open": float(pick("open", "o")),
            "high": float(pick("high", "h")),
            "low": float(pick("low", "l")),
            "close": float(pick("close", "c")),
            "volume": float(row.get("volume", row.get("v", 0.0)) or 0.0),
        }
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) and len(row) >= 5:
        return {
            "ts_ms": timestamp_ms(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]) if len(row) > 5 and row[5] not in (None, "") else 0.0,
        }
    raise AuditError("ROW_UNSUPPORTED")


def load_market(path: Path) -> pd.DataFrame:
    rows = find_rows(json.loads(path.read_text(encoding="utf-8")))
    frame = pd.DataFrame.from_records([row_record(row) for row in rows])
    frame = frame.drop_duplicates("ts_ms", keep="last").sort_values("ts_ms").reset_index(drop=True)
    if frame.empty:
        raise AuditError(f"MARKET_EMPTY:{path}")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if not np.isfinite(frame[["open", "high", "low", "close"]].to_numpy(float)).all():
        raise AuditError(f"MARKET_NONFINITE:{path}")
    if (frame["high"] < frame["low"]).any():
        raise AuditError(f"HIGH_BELOW_LOW:{path}")
    if ((frame["open"] < frame["low"]) | (frame["open"] > frame["high"])).any():
        raise AuditError(f"OPEN_OUTSIDE_RANGE:{path}")
    if ((frame["close"] < frame["low"]) | (frame["close"] > frame["high"])).any():
        raise AuditError(f"CLOSE_OUTSIDE_RANGE:{path}")
    frame.index = pd.to_datetime(frame["ts_ms"], unit="ms", utc=True)
    frame.index.name = "bar_open_time"
    return frame


def select_files(root: Path) -> Dict[str, Path]:
    preferred = root / "runtime" / "r7a4d2_ma5_oos_market_source_coverage_expansion" / "market_data"
    candidates = list(preferred.glob("bingx_*_1m_oos_*.json")) if preferred.exists() else []
    candidates += [
        path
        for path in (root / "runtime").glob("**/market_data/bingx_*_1m_oos_*.json")
        if path not in candidates
    ]
    selected: Dict[str, Path] = {}
    for symbol in SYMBOLS:
        matches = [
            path
            for path in candidates
            if normalize_symbol(symbol).lower() in normalize_symbol(path.name).lower()
        ]
        if not matches:
            raise AuditError(f"MARKET_FILE_MISSING:{symbol}")
        matches.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
        selected[symbol] = matches[-1]
    return selected


def source_quality(frame: pd.DataFrame) -> Dict[str, Any]:
    timestamps = frame["ts_ms"].to_numpy(np.int64)
    deltas = np.diff(timestamps)
    return {
        "rows": int(len(frame)),
        "start_ms": int(timestamps[0]),
        "end_ms": int(timestamps[-1]),
        "duplicate_count": int(frame["ts_ms"].duplicated().sum()),
        "non_1m_delta_count": int(np.sum(deltas != 60_000)),
        "largest_gap_ms": int(deltas.max()) if len(deltas) else 0,
    }


def aggregate(frame: pd.DataFrame, minutes: int) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    grouped = frame.resample(f"{minutes}min", label="left", closed="left")
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_count=("open", "count"),
    )
    total = len(result)
    incomplete = result["source_count"] != minutes
    dropped = int(incomplete.sum())
    result = result.loc[~incomplete].copy()
    result["ts_ms"] = (result.index.astype("int64") // 1_000_000).astype("int64")
    result["bar_close_ts"] = result["ts_ms"] + minutes * 60_000
    if len(result) < 220:
        raise AuditError(f"AGGREGATED_ROWS_INSUFFICIENT:{minutes}")
    return result, {
        "timeframe_min": minutes,
        "total_buckets": int(total),
        "complete_buckets": int(len(result)),
        "dropped_incomplete_buckets": dropped,
    }


def load_module(code_root: Path, relative_path: str, module_name: str) -> Tuple[Any, Path]:
    path = code_root / relative_path
    if not path.is_file():
        raise AuditError(f"MODULE_MISSING:{relative_path}")
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AuditError(f"MODULE_SPEC_FAILED:{relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, path


def normalized_source_text(text: str) -> str:
    return "".join(text.replace("\u00a0", " ").split()).lower()


def source_contract_check(code_root: Path, child: Any) -> Dict[str, Any]:
    snapshot_path = code_root / "research" / "external_sources" / "js_techtrading_supertrend_strategy_basic_v5.pine"
    contract_path = code_root / "research" / "js_techtrading_supertrend_pullback_authentic_contract_v1.json"
    if not snapshot_path.is_file():
        raise AuditError("SOURCE_SNAPSHOT_MISSING")
    if not contract_path.is_file():
        raise AuditError("SOURCE_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    normalized = normalized_source_text(snapshot_path.read_text(encoding="utf-8"))
    required_fragments = (
        "option_ch=input.string('pullback',title=\"typeofstrategy\",options=['pullback','simple'])",
        "atrperiod=input(10,\"atrlength\"",
        "factor=input.float(3.0,\"factor\"",
        "[supertrend,direction]=ta.supertrend(factor,atrperiod)",
        "fin_pullbuy=(ta.crossunder(low[1],long)andlongandhigh>high[1])",
        "fin_pullsell=(ta.crossover(high[1],short)andshortandlow<low[1])",
        "ma_len=input.int(200",
        "rsilength=input(title='rsilength',defval=14",
        "rsioverbought=input(title='rsibuylevel',defval=50",
        "rsioversold=input(title='rsiselllevel',defval=50",
        "strategy.position_size==0",
        "stopper=input.float(1.0",
        "takeper=input.float(1.0",
        "strategy.exit(id='closelong',stop=longstop,limit=longtake)",
        "strategy.exit(id='closeshort',stop=shortstop,limit=shorttake)",
    )
    missing = [fragment for fragment in required_fragments if fragment not in normalized]
    defaults = child.JSTechTradingSupertrendPullbackConfig()
    expected_defaults = contract["default_inputs"]
    default_checks = {
        "strategy_type": defaults.strategy_type == expected_defaults["strategy_type"],
        "atr_length": defaults.atr_length == expected_defaults["atr_length"],
        "factor": float(defaults.factor) == float(expected_defaults["supertrend_factor"]),
        "ema_enabled": defaults.ema_enabled == expected_defaults["ema_enabled"],
        "ema_length": defaults.ema_length == expected_defaults["ema_length"],
        "rsi_enabled": defaults.rsi_enabled == expected_defaults["rsi_enabled"],
        "rsi_length": defaults.rsi_length == expected_defaults["rsi_length"],
        "rsi_buy_level": float(defaults.rsi_buy_level) == float(expected_defaults["rsi_buy_level"]),
        "rsi_sell_level": float(defaults.rsi_sell_level) == float(expected_defaults["rsi_sell_level"]),
        "trade_direction": defaults.trade_direction == expected_defaults["trade_direction"],
        "stop_loss_pct": float(defaults.stop_loss_pct) == float(expected_defaults["stop_loss_pct"]),
        "take_profit_pct": float(defaults.take_profit_pct) == float(expected_defaults["take_profit_pct"]),
        "equity_qty_pct": float(defaults.equity_qty_pct)
        == float(contract["strategy_declaration"]["default_qty_value_pct"]),
    }
    constant_checks = {
        "strategy_id": child.STRATEGY_ID == contract["strategy_id"],
        "source_commit": child.SOURCE_COMMIT == contract["source"]["source_commit"],
        "source_blob_sha": child.SOURCE_BLOB_SHA == contract["source"]["source_blob_sha"],
    }
    passed = not missing and all(default_checks.values()) and all(constant_checks.values())
    return {
        "pass": passed,
        "missing_source_fragments": missing,
        "default_checks": default_checks,
        "constant_checks": constant_checks,
        "snapshot_path": str(snapshot_path.relative_to(code_root)),
        "snapshot_sha256": sha256_file(snapshot_path),
        "contract_path": str(contract_path.relative_to(code_root)),
        "contract_sha256": sha256_file(contract_path),
    }


def independent_signal_oracle(frame: pd.DataFrame, child: Any) -> pd.DataFrame:
    cfg = child.JSTechTradingSupertrendPullbackConfig()
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)

    st_module = sys.modules.get("backend.strategies.authentic.supertrend_flip_authentic")
    if st_module is None:
        from backend.strategies.authentic import supertrend_flip_authentic as st_module

    st = st_module.compute_supertrend(
        frame,
        st_module.SupertrendFlipAuthenticConfig(
            atr_length=cfg.atr_length,
            factor=cfg.factor,
            control_notional=1.0,
        ),
    )
    uptrend = st["direction"] == 1
    downtrend = st["direction"] == -1
    long_line = st["supertrend_line"].where(uptrend)
    short_line = st["supertrend_line"].where(downtrend)

    left_long = low.shift(1)
    crossunder = (left_long < long_line) & (left_long.shift(1) >= long_line.shift(1))
    left_short = high.shift(1)
    crossover = (left_short > short_line) & (left_short.shift(1) <= short_line.shift(1))
    pullback_long = crossunder.fillna(False) & (high > high.shift(1)).fillna(False) & uptrend
    pullback_short = crossover.fillna(False) & (low < low.shift(1)).fillna(False) & downtrend

    alpha = 2.0 / 201.0
    ema = pd.Series(np.nan, index=frame.index, dtype="float64")
    previous: Optional[float] = None
    for position, value in enumerate(close.to_numpy(float)):
        previous = float(value) if previous is None else alpha * float(value) + (1.0 - alpha) * previous
        ema.iloc[position] = previous

    delta = close.diff()
    gain = delta.where(delta >= 0.0, 0.0)
    loss = (-delta).where(delta < 0.0, 0.0)
    gain.iloc[0] = np.nan
    loss.iloc[0] = np.nan

    def rma(series: pd.Series, length: int) -> pd.Series:
        result = pd.Series(np.nan, index=series.index, dtype="float64")
        finite_positions = [i for i, value in enumerate(series.to_numpy(float)) if math.isfinite(value)]
        if len(finite_positions) < length:
            return result
        seed_positions = finite_positions[:length]
        seed_position = seed_positions[-1]
        prev = float(series.iloc[seed_positions].mean())
        result.iloc[seed_position] = prev
        a = 1.0 / float(length)
        for position in range(seed_position + 1, len(series)):
            value = float(series.iloc[position])
            if math.isfinite(value):
                prev = a * value + (1.0 - a) * prev
            result.iloc[position] = prev
        return result

    avg_gain = rma(gain, 14)
    avg_loss = rma(loss, 14)
    rsi = pd.Series(np.nan, index=frame.index, dtype="float64")
    valid = avg_gain.notna() & avg_loss.notna()
    both_zero = valid & (avg_gain == 0.0) & (avg_loss == 0.0)
    loss_zero = valid & (avg_loss == 0.0) & (avg_gain > 0.0)
    gain_zero = valid & (avg_gain == 0.0) & (avg_loss > 0.0)
    ordinary = valid & ~(both_zero | loss_zero | gain_zero)
    rsi.loc[both_zero] = 100.0
    rsi.loc[loss_zero] = 100.0
    rsi.loc[gain_zero] = 0.0
    ratio = avg_gain.loc[ordinary] / avg_loss.loc[ordinary]
    rsi.loc[ordinary] = 100.0 - 100.0 / (1.0 + ratio)

    return pd.DataFrame(
        {
            "ema": ema,
            "rsi": rsi,
            "pullback_long": pullback_long.fillna(False),
            "pullback_short": pullback_short.fillna(False),
            "entry_long": (pullback_long & (close > ema) & (rsi >= 50.0)).fillna(False),
            "entry_short": (pullback_short & (close < ema) & (rsi <= 50.0)).fillna(False),
        },
        index=frame.index,
    )


def compare_signals(actual: pd.DataFrame, expected: pd.DataFrame) -> Dict[str, Any]:
    numeric: Dict[str, Any] = {}
    passed = True
    for field in ("ema", "rsi"):
        left = actual[field].to_numpy(float)
        right = expected[field].to_numpy(float)
        nan_mismatch = int((np.isnan(left) ^ np.isnan(right)).sum())
        mask = np.isfinite(left) & np.isfinite(right)
        diff = np.abs(left[mask] - right[mask])
        scale = np.maximum(1.0, np.abs(right[mask]))
        mismatch = int((diff > (1e-12 + 1e-10 * scale)).sum())
        numeric[field] = {
            "nan_mismatch_count": nan_mismatch,
            "finite_mismatch_count": mismatch,
            "maximum_abs_error": float(diff.max()) if len(diff) else 0.0,
        }
        passed = passed and nan_mismatch == 0 and mismatch == 0
    boolean: Dict[str, int] = {}
    for field in ("pullback_long", "pullback_short", "entry_long", "entry_short"):
        mismatch = int(
            (
                actual[field].fillna(False).astype(bool)
                != expected[field].fillna(False).astype(bool)
            ).sum()
        )
        boolean[field] = mismatch
        passed = passed and mismatch == 0
    return {"pass": passed, "numeric": numeric, "boolean_mismatch_count": boolean}


@dataclass
class Position:
    side: int
    entry_index: int
    entry_ts_ms: int
    entry_price: float
    qty: float
    entry_notional: float
    entry_fee: float
    stop_price: float
    take_price: float
    protection_active: bool = False


@dataclass
class Trade:
    side: str
    entry_index: int
    exit_index: int
    entry_ts_ms: int
    exit_ts_ms: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_return: float
    net_return_on_entry_notional: float
    gross_r: float
    net_r: float
    hold_bars: int
    mfe_return: float
    mae_return: float
    entry_fee_equity: float
    exit_fee_equity: float
    pnl_equity: float


def intrabar_exit(bar: pd.Series, position: Position) -> Optional[Tuple[float, str]]:
    open_price = float(bar["open"])
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    stop = position.stop_price
    take = position.take_price

    if position.side == 1:
        if open_price <= stop:
            return open_price, "STOP_GAP_OPEN"
        if open_price >= take:
            return open_price, "TAKE_GAP_OPEN"
    else:
        if open_price >= stop:
            return open_price, "STOP_GAP_OPEN"
        if open_price <= take:
            return open_price, "TAKE_GAP_OPEN"

    if abs(open_price - high) < abs(open_price - low):
        path = (open_price, high, low, close)
    else:
        path = (open_price, low, high, close)

    levels = ((stop, "STOP_INTRABAR"), (take, "TAKE_INTRABAR"))
    for start, end in zip(path, path[1:]):
        if end == start:
            continue
        candidates: List[Tuple[float, str, float]] = []
        lower, upper = sorted((start, end))
        for level, reason in levels:
            if lower <= level <= upper:
                candidates.append((level, reason, abs(level - start)))
        if candidates:
            level, reason, _ = min(candidates, key=lambda item: item[2])
            return float(level), reason
    return None


def trade_excursions(frame: pd.DataFrame, position: Position, exit_index: int) -> Tuple[float, float]:
    window = frame.iloc[position.entry_index : exit_index + 1]
    if window.empty:
        return 0.0, 0.0
    high = float(window["high"].max())
    low = float(window["low"].min())
    if position.side == 1:
        return high / position.entry_price - 1.0, low / position.entry_price - 1.0
    return 1.0 - low / position.entry_price, 1.0 - high / position.entry_price


def profit_factor(values: Sequence[float]) -> float:
    winners = sum(value for value in values if value > 0.0)
    losers = abs(sum(value for value in values if value < 0.0))
    return winners / losers if losers else (float("inf") if winners else 0.0)


def maximum_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 1.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst)


def replay_exact(frame: pd.DataFrame, signals: pd.DataFrame, cost_bps: float) -> Dict[str, Any]:
    cost_rate = float(cost_bps) / 10_000.0
    realized_equity = 1.0
    marked_path = [1.0]
    position: Optional[Position] = None
    pending_side = 0
    pending_signal_index: Optional[int] = None
    trades: List[Trade] = []
    fill_count = 0
    ignored_signal_count = 0
    simultaneous_signal_count = 0
    entry_long_signal_count = int(signals["entry_long"].sum())
    entry_short_signal_count = int(signals["entry_short"].sum())
    long_entry_count = 0
    short_entry_count = 0

    for index in range(len(frame)):
        bar = frame.iloc[index]
        ts_ms = int(bar["ts_ms"])
        open_price = float(bar["open"])

        if pending_side:
            entry_notional = realized_equity * (QTY_PCT / 100.0)
            qty = entry_notional / open_price
            entry_fee = entry_notional * cost_rate
            realized_equity -= entry_fee
            stop_price = open_price * (1.0 - STOP_PCT / 100.0) if pending_side == 1 else open_price * (1.0 + STOP_PCT / 100.0)
            take_price = open_price * (1.0 + TAKE_PCT / 100.0) if pending_side == 1 else open_price * (1.0 - TAKE_PCT / 100.0)
            position = Position(
                side=pending_side,
                entry_index=index,
                entry_ts_ms=ts_ms,
                entry_price=open_price,
                qty=qty,
                entry_notional=entry_notional,
                entry_fee=entry_fee,
                stop_price=stop_price,
                take_price=take_price,
                protection_active=False,
            )
            fill_count += 1
            long_entry_count += int(pending_side == 1)
            short_entry_count += int(pending_side == -1)
            pending_side = 0
            pending_signal_index = None

        if position is not None and position.protection_active:
            exit_fill = intrabar_exit(bar, position)
            if exit_fill is not None:
                exit_price, exit_reason = exit_fill
                gross_return = position.side * (exit_price - position.entry_price) / position.entry_price
                exit_notional = position.qty * exit_price
                exit_fee = exit_notional * cost_rate
                pnl_equity = position.qty * position.side * (exit_price - position.entry_price)
                realized_equity += pnl_equity - exit_fee
                fill_count += 1
                net_return = gross_return - position.entry_fee / position.entry_notional - exit_fee / position.entry_notional
                mfe, mae = trade_excursions(frame, position, index)
                trades.append(
                    Trade(
                        side="long" if position.side == 1 else "short",
                        entry_index=position.entry_index,
                        exit_index=index,
                        entry_ts_ms=position.entry_ts_ms,
                        exit_ts_ms=ts_ms,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        gross_return=gross_return,
                        net_return_on_entry_notional=net_return,
                        gross_r=gross_return / (STOP_PCT / 100.0),
                        net_r=net_return / (STOP_PCT / 100.0),
                        hold_bars=index - position.entry_index + 1,
                        mfe_return=mfe,
                        mae_return=mae,
                        entry_fee_equity=position.entry_fee,
                        exit_fee_equity=exit_fee,
                        pnl_equity=pnl_equity,
                    )
                )
                position = None

        long_signal = bool(signals["entry_long"].iloc[index])
        short_signal = bool(signals["entry_short"].iloc[index])
        if long_signal and short_signal:
            simultaneous_signal_count += 1
            raise AuditError(f"SIMULTANEOUS_LONG_SHORT_SIGNAL:{index}")
        if position is None and pending_side == 0 and index < len(frame) - 1:
            if long_signal:
                pending_side = 1
                pending_signal_index = index
            elif short_signal:
                pending_side = -1
                pending_signal_index = index
        elif position is not None and (long_signal or short_signal):
            ignored_signal_count += 1

        if position is not None:
            position.protection_active = True
            close_price = float(bar["close"])
            marked_equity = realized_equity + position.qty * position.side * (close_price - position.entry_price)
        else:
            marked_equity = realized_equity
        marked_path.append(float(marked_equity))

    terminal_unrealized = 0.0
    terminal_side = "flat"
    terminal_entry_price = None
    if position is not None:
        final_close = float(frame["close"].iloc[-1])
        terminal_unrealized = position.qty * position.side * (final_close - position.entry_price)
        terminal_side = "long" if position.side == 1 else "short"
        terminal_entry_price = position.entry_price

    full_net_returns = [trade.net_return_on_entry_notional for trade in trades]
    full_gross_returns = [trade.gross_return for trade in trades]
    net_r_values = [trade.net_r for trade in trades]
    winners = [trade for trade in trades if trade.net_return_on_entry_notional > 0.0]
    losers = [trade for trade in trades if trade.net_return_on_entry_notional < 0.0]
    marked_terminal_equity = realized_equity + terminal_unrealized

    return {
        "cost_bps_per_fill": float(cost_bps),
        "closed_trade_count": len(trades),
        "fill_count": fill_count,
        "entry_long_signal_count": entry_long_signal_count,
        "entry_short_signal_count": entry_short_signal_count,
        "long_entry_count": long_entry_count,
        "short_entry_count": short_entry_count,
        "ignored_signal_while_open_count": ignored_signal_count,
        "simultaneous_signal_count": simultaneous_signal_count,
        "win_rate_pct": 100.0 * len(winners) / len(trades) if trades else 0.0,
        "normalized_gross_profit_factor": profit_factor(full_gross_returns),
        "normalized_net_profit_factor": profit_factor(full_net_returns),
        "strategy_realized_return_pct": (realized_equity - 1.0) * 100.0,
        "strategy_marked_return_pct": (marked_terminal_equity - 1.0) * 100.0,
        "normalized_gross_return_sum_pct": sum(full_gross_returns) * 100.0,
        "normalized_net_return_sum_pct": sum(full_net_returns) * 100.0,
        "expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "average_win_r": statistics.fmean([trade.net_r for trade in winners]) if winners else 0.0,
        "average_loss_r": statistics.fmean([trade.net_r for trade in losers]) if losers else 0.0,
        "median_hold_bars": statistics.median([trade.hold_bars for trade in trades]) if trades else 0.0,
        "median_mfe_r": statistics.median([trade.mfe_return / 0.01 for trade in trades]) if trades else 0.0,
        "median_mae_r": statistics.median([trade.mae_return / 0.01 for trade in trades]) if trades else 0.0,
        "max_drawdown_pct": maximum_drawdown(marked_path) * 100.0,
        "terminal_position": terminal_side,
        "terminal_entry_price": terminal_entry_price,
        "terminal_unrealized_equity_pct": terminal_unrealized * 100.0,
        "pending_terminal_order_side": pending_side,
        "pending_terminal_signal_index": pending_signal_index,
        "trade_rows": [asdict(trade) for trade in trades],
    }


def aggregate_profile(symbol_results: Mapping[str, Mapping[str, Any]], cost_key: str) -> Dict[str, Any]:
    profiles = [value["cost_profiles"][cost_key] for value in symbol_results.values()]
    realized_returns = [float(profile["strategy_realized_return_pct"]) for profile in profiles]
    marked_returns = [float(profile["strategy_marked_return_pct"]) for profile in profiles]
    all_trade_returns = [
        float(trade["net_return_on_entry_notional"])
        for profile in profiles
        for trade in profile["trade_rows"]
    ]
    positive_realized = sum(value > 0.0 for value in realized_returns)
    all_r = [float(trade["net_r"]) for profile in profiles for trade in profile["trade_rows"]]
    return {
        "cost_bps_per_fill": float(cost_key),
        "symbol_count": len(profiles),
        "positive_symbol_count": int(positive_realized),
        "portfolio_mean_realized_return_pct": float(statistics.fmean(realized_returns)),
        "portfolio_median_realized_return_pct": float(statistics.median(realized_returns)),
        "portfolio_mean_marked_return_pct": float(statistics.fmean(marked_returns)),
        "worst_symbol_realized_return_pct": float(min(realized_returns)),
        "best_symbol_realized_return_pct": float(max(realized_returns)),
        "maximum_symbol_drawdown_pct": float(max(float(profile["max_drawdown_pct"]) for profile in profiles)),
        "pooled_closed_trade_count": int(sum(int(profile["closed_trade_count"]) for profile in profiles)),
        "pooled_normalized_net_profit_factor": float(profit_factor(all_trade_returns)),
        "pooled_expectancy_r": float(statistics.fmean(all_r)) if all_r else 0.0,
    }


def classify(gross: Mapping[str, Any], cost4: Mapping[str, Any]) -> str:
    if gross["portfolio_mean_realized_return_pct"] <= 0.0 or gross["pooled_normalized_net_profit_factor"] <= 1.0:
        return "GROSS_EDGE_FAIL"
    if (
        cost4["portfolio_mean_realized_return_pct"] > 0.0
        and cost4["pooled_normalized_net_profit_factor"] > 1.0
        and cost4["positive_symbol_count"] >= 3
    ):
        return "COST_4BPS_BROAD_SURVIVOR"
    if cost4["portfolio_mean_realized_return_pct"] > 0.0 and cost4["pooled_normalized_net_profit_factor"] > 1.0:
        return "COST_4BPS_CONCENTRATED_SURVIVOR"
    return "GROSS_POSITIVE_COST_FRAGILE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--code-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    code_root = Path(args.code_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    child, child_path = load_module(
        code_root,
        "backend/strategies/authentic/js_techtrading_supertrend_pullback_authentic.py",
        "js_techtrading_supertrend_pullback_authentic_runtime",
    )
    contract_check = source_contract_check(code_root, child)
    blockers: List[Any] = []
    if not contract_check["pass"]:
        blockers.append({"code": "SOURCE_CONTRACT_MISMATCH", "details": contract_check})

    market_files = select_files(data_root)
    summary: Dict[str, Any] = {
        "schema": "r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay_v1",
        "target_sha": args.target_sha,
        "strategy_id": child.STRATEGY_ID,
        "source_commit": child.SOURCE_COMMIT,
        "source_blob_sha": child.SOURCE_BLOB_SHA,
        "source_contract_check": contract_check,
        "child_path": str(child_path.relative_to(code_root)),
        "child_sha256": sha256_file(child_path),
        "execution_contract": {
            "strategy_type": STRATEGY_TYPE,
            "qty_pct_of_equity": QTY_PCT,
            "signal_calculation": "confirmed_bar_close",
            "market_entry_fill": "next_bar_open",
            "entry_bar_protection": False,
            "stop_loss_pct": STOP_PCT,
            "take_profit_pct": TAKE_PCT,
            "same_bar_collision": "TRADINGVIEW_DEFAULT_BROKER_EMULATOR_OHLC_PATH",
            "gap_fill": "CURRENT_BAR_OPEN",
            "position_reversal": False,
            "terminal_force_close": False,
            "cost_profiles_bps_per_fill": list(COSTS_BPS),
        },
        "symbols": {},
        "timeframe_aggregate": {},
        "blockers": blockers,
    }

    signal_parity_failures: List[str] = []
    for symbol, source_path in market_files.items():
        frame_1m = load_market(source_path)
        symbol_result: Dict[str, Any] = {
            "source_path": str(source_path),
            "source_sha256": sha256_file(source_path),
            "source_quality": source_quality(frame_1m),
            "timeframes": {},
        }
        for minutes in TIMEFRAMES:
            frame, aggregation_info = aggregate(frame_1m, minutes)
            cfg = child.JSTechTradingSupertrendPullbackConfig()
            actual = child.compute_source_locked_signals(frame, cfg)
            expected = independent_signal_oracle(frame, child)
            parity = compare_signals(actual, expected)
            if not parity["pass"]:
                signal_parity_failures.append(f"{symbol}:{minutes}m")
            cost_profiles = {str(cost): replay_exact(frame, actual, cost) for cost in COSTS_BPS}
            symbol_result["timeframes"][f"{minutes}m"] = {
                "aggregation": aggregation_info,
                "signal_parity": parity,
                "raw_entry_long_signal_count": int(actual["entry_long"].sum()),
                "raw_entry_short_signal_count": int(actual["entry_short"].sum()),
                "cost_profiles": cost_profiles,
            }
        summary["symbols"][symbol] = symbol_result

    if signal_parity_failures:
        summary["blockers"].append({"code": "SOURCE_SIGNAL_PARITY_FAILED", "items": signal_parity_failures})

    for minutes in TIMEFRAMES:
        symbol_results = {
            symbol: summary["symbols"][symbol]["timeframes"][f"{minutes}m"]
            for symbol in SYMBOLS
        }
        profiles = {str(cost): aggregate_profile(symbol_results, str(cost)) for cost in COSTS_BPS}
        summary["timeframe_aggregate"][f"{minutes}m"] = {
            "profiles": profiles,
            "economic_classification": classify(profiles["0.0"], profiles["4.0"]),
        }

    summary["source_contract_pass"] = contract_check["pass"]
    summary["signal_parity_pass"] = not signal_parity_failures
    summary["economic_test_executed"] = not summary["blockers"]
    summary["input_mutation_count"] = 0
    summary["strategy_mutation_count"] = 0
    summary["registry_mutation_count"] = 0
    summary["paper_live_order_allowed"] = False
    summary["next_stage"] = "R7.A4D2_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_RESULT_REVIEW_GATE"
    rc = 0 if not summary["blockers"] else 2
    summary["state"] = (
        "PASS_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_REPLAY"
        if rc == 0
        else "HOLD_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_REPLAY"
    )
    summary["rc"] = rc

    output_path = output_dir / "js_techtrading_supertrend_pullback_exact_oos_summary_v1.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=True) + "\n", encoding="utf-8")

    print(f"STATE={summary['state']}")
    print(f"BLOCKER_COUNT={len(summary['blockers'])}")
    print(f"SOURCE_CONTRACT_PASS={str(summary['source_contract_pass']).lower()}")
    print(f"SIGNAL_PARITY_PASS={str(summary['signal_parity_pass']).lower()}")
    print(f"SOURCE_COMMIT={summary['source_commit']}")
    print(f"SOURCE_BLOB_SHA={summary['source_blob_sha']}")
    for symbol in SYMBOLS:
        for minutes in TIMEFRAMES:
            timeframe = summary["symbols"][symbol]["timeframes"][f"{minutes}m"]
            gross = timeframe["cost_profiles"]["0.0"]
            cost4 = timeframe["cost_profiles"]["4.0"]
            print(
                "REPLAY_RESULT="
                f"{symbol}|{minutes}m|BARS={timeframe['aggregation']['complete_buckets']}"
                f"|LONG_SIGNALS={timeframe['raw_entry_long_signal_count']}"
                f"|SHORT_SIGNALS={timeframe['raw_entry_short_signal_count']}"
                f"|TRADES={gross['closed_trade_count']}"
                f"|GROSS_EQ_PCT={gross['strategy_realized_return_pct']:.6f}"
                f"|GROSS_MARKED_PCT={gross['strategy_marked_return_pct']:.6f}"
                f"|GROSS_PF={gross['normalized_net_profit_factor']:.6f}"
                f"|GROSS_DD_PCT={gross['max_drawdown_pct']:.6f}"
                f"|GROSS_EXP_R={gross['expectancy_r']:.6f}"
                f"|NET4BPS_EQ_PCT={cost4['strategy_realized_return_pct']:.6f}"
                f"|NET4BPS_PF={cost4['normalized_net_profit_factor']:.6f}"
                f"|NET4BPS_EXP_R={cost4['expectancy_r']:.6f}"
                f"|LONG_ENTRIES={gross['long_entry_count']}|SHORT_ENTRIES={gross['short_entry_count']}"
                f"|TERMINAL={gross['terminal_position']}"
            )
    for minutes in TIMEFRAMES:
        result = summary["timeframe_aggregate"][f"{minutes}m"]
        gross = result["profiles"]["0.0"]
        cost4 = result["profiles"]["4.0"]
        print(
            "TIMEFRAME_RESULT="
            f"{minutes}m|CLASS={result['economic_classification']}"
            f"|GROSS_MEAN_EQ_PCT={gross['portfolio_mean_realized_return_pct']:.6f}"
            f"|GROSS_PF={gross['pooled_normalized_net_profit_factor']:.6f}"
            f"|GROSS_EXP_R={gross['pooled_expectancy_r']:.6f}"
            f"|GROSS_POS_SYMBOLS={gross['positive_symbol_count']}/{gross['symbol_count']}"
            f"|NET4BPS_MEAN_EQ_PCT={cost4['portfolio_mean_realized_return_pct']:.6f}"
            f"|NET4BPS_PF={cost4['pooled_normalized_net_profit_factor']:.6f}"
            f"|NET4BPS_EXP_R={cost4['pooled_expectancy_r']:.6f}"
            f"|NET4BPS_POS_SYMBOLS={cost4['positive_symbol_count']}/{cost4['symbol_count']}"
            f"|WORST4BPS_EQ_PCT={cost4['worst_symbol_realized_return_pct']:.6f}"
        )
    print(f"SUMMARY_JSON={output_path}")
    print("INPUT_MUTATION_COUNT=0")
    print("STRATEGY_MUTATION_COUNT=0")
    print(f"NEXT_STAGE={summary['next_stage']}")
    print(f"BLOCKERS={json.dumps(summary['blockers'], separators=(',', ':'))}")
    print(f"RC={rc}")
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_REPLAY")
        print("BLOCKER_COUNT=1")
        print(f"BLOCKERS=[\"{str(exc)}\"]")
        print("RC=2")
        raise SystemExit(2)
