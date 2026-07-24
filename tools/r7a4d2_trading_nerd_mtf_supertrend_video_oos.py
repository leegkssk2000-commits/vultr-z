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
TIMEFRAME_PAIRS = ((5, 15), (5, 60), (15, 60), (15, 240))
COSTS_BPS = (0.0, 4.0)


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
                value = item.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, Mapping):
                    queue.append(value)
            queue.extend(value for value in item.values() if isinstance(value, (list, Mapping)))
    raise AuditError("MARKET_ROWS_NOT_FOUND")


def row_record(row: Any) -> Dict[str, Any]:
    if isinstance(row, Mapping):
        ts_value = next((row[key] for key in ("time", "timestamp", "ts", "open_time", "openTime", "start", "startTime", "t") if key in row), None)
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
    frame.index = pd.to_datetime(frame["ts_ms"], unit="ms", utc=True)
    frame.index.name = "bar_open_time"
    return frame


def select_files(root: Path) -> Dict[str, Path]:
    preferred = root / "runtime" / "r7a4d2_ma5_oos_market_source_coverage_expansion" / "market_data"
    candidates = list(preferred.glob("bingx_*_1m_oos_*.json")) if preferred.exists() else []
    candidates += [path for path in (root / "runtime").glob("**/market_data/bingx_*_1m_oos_*.json") if path not in candidates]
    selected: Dict[str, Path] = {}
    for symbol in SYMBOLS:
        matches = [path for path in candidates if normalize_symbol(symbol).lower() in normalize_symbol(path.name).lower()]
        if not matches:
            raise AuditError(f"MARKET_FILE_MISSING:{symbol}")
        matches.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
        selected[symbol] = matches[-1]
    return selected


def aggregate(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    grouped = frame.resample(f"{minutes}min", label="left", closed="left")
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_count=("open", "count"),
    )
    result = result.loc[result["source_count"] == minutes].copy()
    result["ts_ms"] = (result.index.astype("int64") // 1_000_000).astype("int64")
    result["bar_close_ts"] = result["ts_ms"] + minutes * 60_000
    if len(result) < 100:
        raise AuditError(f"AGGREGATED_ROWS_INSUFFICIENT:{minutes}")
    return result


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


@dataclass
class Position:
    side: int
    entry_index: int
    entry_ts_ms: int
    entry_price: float
    stop_price: float
    entry_fee: float


@dataclass
class Trade:
    side: str
    entry_ts_ms: int
    exit_ts_ms: int
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_return: float
    net_return: float
    gross_r: float
    net_r: float
    hold_bars: int
    mfe_r: float
    mae_r: float


def profit_factor(values: Sequence[float]) -> float:
    wins = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return wins / losses if losses else (float("inf") if wins else 0.0)


def max_drawdown(path: Sequence[float]) -> float:
    peak = path[0] if path else 1.0
    worst = 0.0
    for value in path:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst)


def replay(frame: pd.DataFrame, signals: pd.DataFrame, cost_bps: float) -> Dict[str, Any]:
    cost = float(cost_bps) / 10_000.0
    equity = 1.0
    equity_path = [equity]
    position: Optional[Position] = None
    pending_side = 0
    pending_stop = float("nan")
    trades: List[Trade] = []
    long_entries = 0
    short_entries = 0

    for i in range(len(frame)):
        bar = frame.iloc[i]
        open_price = float(bar["open"])
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        ts_ms = int(bar["ts_ms"])

        if pending_side:
            fee = equity * cost
            equity -= fee
            position = Position(
                side=pending_side,
                entry_index=i,
                entry_ts_ms=ts_ms,
                entry_price=open_price,
                stop_price=pending_stop,
                entry_fee=fee,
            )
            long_entries += int(pending_side == 1)
            short_entries += int(pending_side == -1)
            pending_side = 0
            pending_stop = float("nan")

        if position is not None and math.isfinite(position.stop_price):
            exit_price: Optional[float] = None
            reason = ""
            if position.side == 1:
                if open_price <= position.stop_price:
                    exit_price, reason = open_price, "TRAIL_GAP_OPEN"
                elif low <= position.stop_price:
                    exit_price, reason = position.stop_price, "TRAIL_INTRABAR"
            else:
                if open_price >= position.stop_price:
                    exit_price, reason = open_price, "TRAIL_GAP_OPEN"
                elif high >= position.stop_price:
                    exit_price, reason = position.stop_price, "TRAIL_INTRABAR"
            if exit_price is not None:
                gross_return = position.side * (exit_price - position.entry_price) / position.entry_price
                exit_fee = equity * cost
                equity *= 1.0 + gross_return
                equity -= exit_fee
                window = frame.iloc[position.entry_index : i + 1]
                if position.side == 1:
                    mfe = float(window["high"].max()) / position.entry_price - 1.0
                    mae = float(window["low"].min()) / position.entry_price - 1.0
                else:
                    mfe = 1.0 - float(window["low"].min()) / position.entry_price
                    mae = 1.0 - float(window["high"].max()) / position.entry_price
                net_return = gross_return - cost - cost
                initial_risk = abs(position.entry_price - position.stop_price) / position.entry_price
                denominator = initial_risk if initial_risk > 1e-12 else 1.0
                trades.append(
                    Trade(
                        side="long" if position.side == 1 else "short",
                        entry_ts_ms=position.entry_ts_ms,
                        exit_ts_ms=ts_ms,
                        entry_price=position.entry_price,
                        exit_price=exit_price,
                        exit_reason=reason,
                        gross_return=gross_return,
                        net_return=net_return,
                        gross_r=gross_return / denominator,
                        net_r=net_return / denominator,
                        hold_bars=i - position.entry_index + 1,
                        mfe_r=mfe / denominator,
                        mae_r=mae / denominator,
                    )
                )
                position = None

        if position is not None:
            candidate_stop = float(signals["trailing_stop"].iloc[i])
            if math.isfinite(candidate_stop):
                if position.side == 1 and candidate_stop < close:
                    position.stop_price = max(position.stop_price, candidate_stop)
                elif position.side == -1 and candidate_stop > close:
                    position.stop_price = min(position.stop_price, candidate_stop)

        if position is None and i < len(frame) - 1:
            long_signal = bool(signals["entry_long"].iloc[i])
            short_signal = bool(signals["entry_short"].iloc[i])
            stop = float(signals["trailing_stop"].iloc[i])
            if long_signal and short_signal:
                raise AuditError(f"SIMULTANEOUS_SIGNAL:{i}")
            if long_signal and math.isfinite(stop) and stop < close:
                pending_side = 1
                pending_stop = stop
            elif short_signal and math.isfinite(stop) and stop > close:
                pending_side = -1
                pending_stop = stop

        marked = equity
        if position is not None:
            marked *= 1.0 + position.side * (close - position.entry_price) / position.entry_price
        equity_path.append(marked)

    gross_values = [trade.gross_return for trade in trades]
    net_values = [trade.net_return for trade in trades]
    net_r_values = [trade.net_r for trade in trades]
    wins = [trade for trade in trades if trade.net_return > 0]
    losses = [trade for trade in trades if trade.net_return < 0]
    terminal_side = "flat" if position is None else ("long" if position.side == 1 else "short")
    return {
        "cost_bps_per_fill": cost_bps,
        "trade_count": len(trades),
        "long_entry_count": long_entries,
        "short_entry_count": short_entries,
        "win_rate_pct": 100.0 * len(wins) / len(trades) if trades else 0.0,
        "gross_profit_factor": profit_factor(gross_values),
        "net_profit_factor": profit_factor(net_values),
        "gross_return_sum_pct": sum(gross_values) * 100.0,
        "net_return_sum_pct": sum(net_values) * 100.0,
        "expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "average_win_r": statistics.fmean([trade.net_r for trade in wins]) if wins else 0.0,
        "average_loss_r": statistics.fmean([trade.net_r for trade in losses]) if losses else 0.0,
        "max_drawdown_pct": max_drawdown(equity_path) * 100.0,
        "terminal_position": terminal_side,
        "trade_rows": [asdict(trade) for trade in trades],
    }


def aggregate_pair(symbol_results: Mapping[str, Mapping[str, Any]], profile: str) -> Dict[str, Any]:
    rows = [result[profile] for result in symbol_results.values()]
    trades = [trade for row in rows for trade in row["trade_rows"]]
    net_values = [float(trade["net_return"]) for trade in trades]
    net_r_values = [float(trade["net_r"]) for trade in trades]
    returns = [float(row["net_return_sum_pct"]) for row in rows]
    return {
        "symbol_count": len(rows),
        "positive_symbol_count": sum(value > 0 for value in returns),
        "mean_symbol_net_return_pct": statistics.fmean(returns),
        "worst_symbol_net_return_pct": min(returns),
        "pooled_trade_count": len(trades),
        "pooled_long_entry_count": sum(int(row["long_entry_count"]) for row in rows),
        "pooled_short_entry_count": sum(int(row["short_entry_count"]) for row in rows),
        "pooled_net_profit_factor": profit_factor(net_values),
        "pooled_expectancy_r": statistics.fmean(net_r_values) if net_r_values else 0.0,
        "maximum_symbol_drawdown_pct": max(float(row["max_drawdown_pct"]) for row in rows),
    }


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
    contract_path = code_root / "research" / "trading_nerd_mtf_supertrend_video_contract_v1.json"
    if not contract_path.is_file():
        raise AuditError("VIDEO_CONTRACT_MISSING")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    child, child_path = load_module(
        code_root,
        "backend/strategies/authentic/trading_nerd_mtf_supertrend_video.py",
        "trading_nerd_mtf_supertrend_video_runtime",
    )
    if child.STRATEGY_ID != contract["strategy_id"]:
        raise AuditError("VIDEO_CONTRACT_STRATEGY_ID_MISMATCH")

    files = select_files(data_root)
    summary: Dict[str, Any] = {
        "schema": "r7a4d2_trading_nerd_mtf_supertrend_video_oos_v1",
        "state": "PASS_TRADING_NERD_MTF_SUPERTREND_VIDEO_OOS_EXECUTION",
        "target_sha": args.target_sha,
        "strategy_id": child.STRATEGY_ID,
        "youtube_video_id": child.YOUTUBE_VIDEO_ID,
        "tradingview_script_id": child.TRADINGVIEW_SCRIPT_ID,
        "contract_sha256": sha256_file(contract_path),
        "child_sha256": sha256_file(child_path),
        "pairs": {},
        "blockers": [],
        "mutation_count": 0,
    }

    for lower_min, higher_min in TIMEFRAME_PAIRS:
        pair_id = f"{lower_min}m_to_{higher_min}m"
        symbol_results: Dict[str, Any] = {}
        for symbol, source_path in files.items():
            one_minute = load_market(source_path)
            lower = aggregate(one_minute, lower_min)
            higher = aggregate(one_minute, higher_min)
            cfg = child.TradingNerdMTFSupertrendConfig(
                atr_length=10,
                factor=3.0,
                lower_timeframe_min=lower_min,
                higher_timeframe_min=higher_min,
                trade_direction="Both",
                trade_higher_timeframe_flip=False,
                use_adx_filter=False,
            )
            signals = child.compute_video_contract_signals(lower, higher, cfg)
            profiles = {str(cost): replay(lower, signals, cost) for cost in COSTS_BPS}
            symbol_results[symbol] = {
                "source_path": str(source_path),
                "source_sha256": sha256_file(source_path),
                "lower_bars": len(lower),
                "higher_bars": len(higher),
                "long_signal_count": int(signals["entry_long"].sum()),
                "short_signal_count": int(signals["entry_short"].sum()),
                "0.0": profiles["0.0"],
                "4.0": profiles["4.0"],
            }
            print(
                "VIDEO_REPLAY_RESULT="
                f"{symbol}|PAIR={pair_id}|LONG_SIGNALS={int(signals['entry_long'].sum())}"
                f"|SHORT_SIGNALS={int(signals['entry_short'].sum())}"
                f"|TRADES={profiles['0.0']['trade_count']}"
                f"|GROSS_SUM_PCT={profiles['0.0']['net_return_sum_pct']:.6f}"
                f"|GROSS_PF={profiles['0.0']['net_profit_factor']:.6f}"
                f"|GROSS_EXP_R={profiles['0.0']['expectancy_r']:.6f}"
                f"|NET4BPS_SUM_PCT={profiles['4.0']['net_return_sum_pct']:.6f}"
                f"|NET4BPS_PF={profiles['4.0']['net_profit_factor']:.6f}"
                f"|NET4BPS_EXP_R={profiles['4.0']['expectancy_r']:.6f}"
                f"|DD_PCT={profiles['4.0']['max_drawdown_pct']:.6f}"
            )
        gross = aggregate_pair(symbol_results, "0.0")
        cost4 = aggregate_pair(symbol_results, "4.0")
        gate = (
            gross["pooled_net_profit_factor"] > 1.0
            and cost4["pooled_net_profit_factor"] > 1.0
            and cost4["pooled_expectancy_r"] > 0.0
            and cost4["positive_symbol_count"] >= 3
            and cost4["pooled_long_entry_count"] >= 10
            and cost4["pooled_short_entry_count"] >= 10
            and cost4["maximum_symbol_drawdown_pct"] <= 25.0
        )
        classification = "PROMOTION_CANDIDATE" if gate else "ECONOMIC_FAIL_OR_FRAGILE"
        summary["pairs"][pair_id] = {
            "symbols": symbol_results,
            "gross_aggregate": gross,
            "cost4bps_aggregate": cost4,
            "classification": classification,
        }
        print(
            "VIDEO_PAIR_RESULT="
            f"{pair_id}|CLASS={classification}"
            f"|GROSS_PF={gross['pooled_net_profit_factor']:.6f}"
            f"|GROSS_EXP_R={gross['pooled_expectancy_r']:.6f}"
            f"|GROSS_POS_SYMBOLS={gross['positive_symbol_count']}/5"
            f"|NET4BPS_PF={cost4['pooled_net_profit_factor']:.6f}"
            f"|NET4BPS_EXP_R={cost4['pooled_expectancy_r']:.6f}"
            f"|NET4BPS_POS_SYMBOLS={cost4['positive_symbol_count']}/5"
            f"|LONG_ENTRIES={cost4['pooled_long_entry_count']}"
            f"|SHORT_ENTRIES={cost4['pooled_short_entry_count']}"
            f"|MAX_DD_PCT={cost4['maximum_symbol_drawdown_pct']:.6f}"
        )

    candidates = [pair for pair, result in summary["pairs"].items() if result["classification"] == "PROMOTION_CANDIDATE"]
    summary["promotion_candidate_pairs"] = candidates
    summary["promotion_allowed"] = len(candidates) == 1
    summary["next_stage"] = (
        "R7.A4D2_TRADING_NERD_MTF_SUPERTREND_VIDEO_INDEPENDENT_REPLAY_CONFIRMATION"
        if candidates
        else "R7.A4D2_TRADING_NERD_MTF_SUPERTREND_VIDEO_LOSS_ANATOMY"
    )
    output_path = output_dir / "trading_nerd_mtf_supertrend_video_oos_summary_v1.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=True) + "\n", encoding="utf-8")
    print(f"STATE={summary['state']}")
    print(f"PROMOTION_CANDIDATE_COUNT={len(candidates)}")
    print(f"PROMOTION_CANDIDATES={json.dumps(candidates, separators=(',', ':'))}")
    print(f"PROMOTION_ALLOWED={str(summary['promotion_allowed']).lower()}")
    print(f"SUMMARY_JSON={output_path}")
    print("MUTATION_COUNT=0")
    print(f"NEXT_STAGE={summary['next_stage']}")
    print("BLOCKERS=[]")
    print("RC=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print("STATE=HOLD_TRADING_NERD_MTF_SUPERTREND_VIDEO_OOS_INPUT")
        print(f"BLOCKERS=[\"{str(exc)}\"]")
        print("RC=2")
        raise SystemExit(2)
