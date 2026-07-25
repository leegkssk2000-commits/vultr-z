from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from backend.strategy25.indicator_contract_repair_adapter_v1 import REPAIR_SPECS
from backend.strategy25.indicator_contract_repair_loader_v1 import load_repaired_strategy


INTERVAL = "15m"
INTERVAL_MS = 900_000
REQUEST_LIMIT = 1000
ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v3/quote/klines",
    "https://open-api.bingx.com/openApi/swap/v2/quote/klines",
)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
STRATEGIES = tuple(REPAIR_SPECS)
FIXED_END_ISO = "2026-07-24T00:00:00Z"
WINDOW_BARS = 1200
WARMUP_BARS = 220
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0
OUTPUT_DIR = "artifacts/strategy_indicator_repair_real_oos_v1"


@dataclass
class Position:
    qty: float
    avg_entry: float
    sl: float
    tp: float
    opened_at: str
    realized_pct: float = 0.0
    cost_pct: float = 0.0
    add_count: int = 0


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_json(url: str) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "ZEL-Strategy25-OOS/1.0"},
            )
            with urllib.request.urlopen(request, timeout=25) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("RESPONSE_NOT_OBJECT")
            return value
        except Exception as exc:
            error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{type(error).__name__}:{error}")


def _payload_rows(payload: Mapping[str, Any]) -> list[Any]:
    data: Any = payload.get("data")
    if isinstance(data, dict):
        data = next(
            (
                data[key]
                for key in ("data", "rows", "klines", "list")
                if isinstance(data.get(key), list)
            ),
            [],
        )
    return data if isinstance(data, list) else []


def _parse_row(row: Any) -> tuple[int, float, float, float, float, float] | None:
    if isinstance(row, dict):
        raw = (
            row.get("time", row.get("timestamp", row.get("openTime"))),
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume", row.get("vol")),
        )
    elif isinstance(row, (list, tuple)) and len(row) >= 6:
        raw = tuple(row[:6])
    else:
        return None
    try:
        timestamp = int(float(raw[0]))
        if timestamp < 10_000_000_000:
            timestamp *= 1000
        elif timestamp > 10_000_000_000_000:
            timestamp //= 1000
        open_, high, low, close, volume = map(float, raw[1:6])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (open_, high, low, close, volume)):
        return None
    if open_ <= 0 or close <= 0 or volume < 0:
        return None
    if high < max(open_, close) or low > min(open_, close) or high < low:
        return None
    return timestamp, open_, high, low, close, volume


def _fetch_exact(symbol: str, *, start_ms: int, end_ms: int, expected_rows: int) -> tuple[pd.DataFrame, str, int]:
    errors: list[str] = []
    request_start = start_ms - INTERVAL_MS
    request_end = end_ms + INTERVAL_MS
    max_requests = max(8, math.ceil((expected_rows + 2) / (REQUEST_LIMIT - 1)) + 5)

    for endpoint in ENDPOINTS:
        try:
            found: dict[int, tuple[int, float, float, float, float, float]] = {}
            cursor = request_start
            request_count = 0
            while cursor <= request_end and request_count < max_requests:
                window_end = min(request_end, cursor + (REQUEST_LIMIT - 1) * INTERVAL_MS)
                query = urllib.parse.urlencode(
                    {
                        "symbol": symbol[:-4] + "-USDT",
                        "interval": INTERVAL,
                        "limit": REQUEST_LIMIT,
                        "startTime": cursor,
                        "endTime": window_end,
                    }
                )
                payload = _request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
                page = [
                    item
                    for item in (_parse_row(row) for row in _payload_rows(payload))
                    if item is not None
                ]
                request_count += 1
                if not page:
                    raise ValueError(f"EMPTY_PAGE:{cursor}:{window_end}")
                for item in page:
                    if start_ms <= item[0] <= end_ms:
                        found[item[0]] = item
                if len(found) >= expected_rows and min(found) == start_ms and max(found) == end_ms:
                    break
                max_seen = max(item[0] for item in page)
                next_cursor = max_seen + INTERVAL_MS
                if next_cursor <= cursor:
                    raise ValueError(f"PAGINATION_STALLED:{cursor}:{max_seen}")
                cursor = next_cursor

            frame = pd.DataFrame(
                [found[key] for key in sorted(found)],
                columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
            )
            if len(frame) != expected_rows:
                raise ValueError(f"ROWS:{len(frame)}!={expected_rows}")
            timestamps = frame["timestamp_ms"].astype("int64")
            if timestamps.duplicated().any():
                raise ValueError("DUPLICATE_TIMESTAMP")
            if not bool((timestamps.diff().dropna() == INTERVAL_MS).all()):
                raise ValueError("TIMESTAMP_GAP_OR_WRONG_INTERVAL")
            if int(timestamps.iloc[0]) != start_ms or int(timestamps.iloc[-1]) != end_ms:
                raise ValueError("WINDOW_BOUNDARY_MISMATCH")
            frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
            frame["ts"] = frame["timestamp_ms"]
            return frame, endpoint, request_count
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("BINGX_EXACT_WINDOW_FAILED:" + "|".join(errors))


def _load_registry(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = [row for row in payload.get("entries", []) if isinstance(row, dict)]
    result = {str(row.get("strategy_id")): row for row in entries}
    if len(result) != 25 or payload.get("fail_closed") is not True:
        raise RuntimeError("CANONICAL_REGISTRY_INVALID")
    return result


def _load_canonical_strategy(root: Path, strategy_id: str, row: Mapping[str, Any]) -> Callable[..., dict[str, Any]]:
    engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
    repo_path = str(engine.get("implementation_path") or "")
    expected_sha = str(engine.get("source_sha256") or "")
    path = root / repo_path
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"SOURCE_INVALID:{strategy_id}:{repo_path}")
    actual_sha = _sha256(path)
    if actual_sha != expected_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{strategy_id}")

    module_name = f"strategy25_oos_canonical_{strategy_id}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{strategy_id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    strategy = getattr(module, "strategy", None)
    if not callable(strategy):
        raise RuntimeError(f"RAW_STRATEGY_CALLABLE_MISSING:{strategy_id}")
    return strategy


def _stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    gross_gain = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    average_win = sum(wins) / len(wins) if wins else None
    average_loss = abs(sum(losses) / len(losses)) if losses else None
    return {
        "trade_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else None,
        "net_return_pct_sum": sum(returns),
        "net_profit_factor": (gross_gain / gross_loss) if gross_loss > 0.0 else (999.0 if gross_gain > 0.0 else None),
        "payoff_ratio": (average_win / average_loss) if average_win is not None and average_loss not in (None, 0.0) else None,
        "average_win_pct": average_win,
        "average_loss_pct_abs": average_loss,
        "max_drawdown_pct": max_drawdown,
    }


def _close_position(
    position: Position,
    *,
    exit_price: float,
    timestamp: str,
    reason: str,
    cost_rate: float,
) -> dict[str, Any]:
    gross = position.qty * ((exit_price / position.avg_entry) - 1.0) * 100.0
    exit_cost = position.qty * cost_rate * 100.0
    net = position.realized_pct + gross - position.cost_pct - exit_cost
    return {
        "entry_ts": position.opened_at,
        "exit_ts": timestamp,
        "entry_price": position.avg_entry,
        "exit_price": exit_price,
        "qty": position.qty,
        "net_return_pct": net,
        "exit_reason": reason,
        "add_count": position.add_count,
    }


def _replay(
    frame: pd.DataFrame,
    strategy: Callable[..., dict[str, Any]],
    *,
    warmup_bars: int,
    history_bars: int,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    position: Position | None = None
    pending: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    signal_count = 0
    short_signal_count = 0
    rejected_entry_count = 0
    add_count = 0
    reduce_count = 0
    call_count = 0

    for index in range(warmup_bars, len(frame)):
        row = frame.iloc[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()

        if pending is not None:
            action = str(pending.get("action") or "hold").lower()
            side = str(pending.get("side") or "").lower()
            size = float(pending.get("size") or 0.0) if _finite(pending.get("size")) else 0.0
            signal_entry = float(pending.get("entry") or 0.0) if _finite(pending.get("entry")) else 0.0
            signal_sl = float(pending.get("sl") or 0.0) if _finite(pending.get("sl")) else 0.0
            signal_tp = float(pending.get("tp") or 0.0) if _finite(pending.get("tp")) else 0.0

            if side == "short" and action in {"enter", "add", "reduce"}:
                short_signal_count += 1
            elif side == "long" and action == "enter" and position is None:
                risk = signal_entry - signal_sl
                reward = signal_tp - signal_entry
                if size > 0.0 and risk > 0.0 and reward > 0.0:
                    position = Position(
                        qty=size,
                        avg_entry=open_,
                        sl=open_ - risk,
                        tp=open_ + reward,
                        opened_at=timestamp,
                        cost_pct=size * cost_rate * 100.0,
                    )
                else:
                    rejected_entry_count += 1
            elif side == "long" and action == "add" and position is not None and size > 0.0:
                new_qty = position.qty + size
                position.avg_entry = ((position.avg_entry * position.qty) + (open_ * size)) / new_qty
                position.qty = new_qty
                position.cost_pct += size * cost_rate * 100.0
                position.add_count += 1
                add_count += 1
            elif side == "long" and action == "reduce" and position is not None and size > 0.0:
                reduce_qty = min(size, position.qty)
                position.realized_pct += reduce_qty * ((open_ / position.avg_entry) - 1.0) * 100.0
                position.cost_pct += reduce_qty * cost_rate * 100.0
                position.qty -= reduce_qty
                reduce_count += 1
                if position.qty <= 1e-9:
                    trades.append(
                        {
                            "entry_ts": position.opened_at,
                            "exit_ts": timestamp,
                            "entry_price": position.avg_entry,
                            "exit_price": open_,
                            "qty": 0.0,
                            "net_return_pct": position.realized_pct - position.cost_pct,
                            "exit_reason": "REDUCE_TO_ZERO",
                            "add_count": position.add_count,
                        }
                    )
                    position = None
            pending = None

        if position is not None:
            hit_sl = low <= position.sl
            hit_tp = high >= position.tp
            if hit_sl or hit_tp:
                exit_price = position.sl if hit_sl else position.tp
                reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
                trades.append(
                    _close_position(
                        position,
                        exit_price=exit_price,
                        timestamp=timestamp,
                        reason=reason,
                        cost_rate=cost_rate,
                    )
                )
                position = None

        if index >= len(frame) - 1:
            break

        history = frame.iloc[max(0, index - history_bars + 1) : index + 1].copy()
        state = {
            "position_side": "long" if position is not None else "",
            "position_qty": position.qty if position is not None else 0.0,
            "avg_entry": position.avg_entry if position is not None else 0.0,
            "add_count": position.add_count if position is not None else 0,
            "last_add_price": position.avg_entry if position is not None else 0.0,
        }
        result = strategy(history, state=state, risk_action="hold")
        call_count += 1
        if not isinstance(result, dict):
            raise RuntimeError("STRATEGY_RESULT_NOT_DICT")
        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "").lower()
        if action in {"enter", "add", "reduce"}:
            signal_count += 1
            pending = dict(result)
        elif side == "short":
            short_signal_count += 1

    if position is not None:
        last = frame.iloc[-1]
        trades.append(
            _close_position(
                position,
                exit_price=float(last["close"]),
                timestamp=pd.Timestamp(last["timestamp"]).isoformat(),
                reason="WINDOW_END",
                cost_rate=cost_rate,
            )
        )

    return {
        "stats": _stats(trades),
        "trades": trades,
        "call_count": call_count,
        "signal_count": signal_count,
        "short_signal_count": short_signal_count,
        "rejected_entry_count": rejected_entry_count,
        "add_count": add_count,
        "reduce_count": reduce_count,
        "completed_bar_only": True,
        "next_bar_open_execution": True,
        "same_bar_sl_tp_policy": "SL_FIRST_CONSERVATIVE",
        "long_only_runtime_alignment": True,
    }


def _aggregate(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [
        trade
        for item in items
        for trade in item.get("trades", [])
        if isinstance(trade, dict)
    ]
    return _stats(trades)


def _metric(value: Any, default: float) -> float:
    return float(value) if _finite(value) else default


def _economic_pass(candidate: Mapping[str, Any], baseline: Mapping[str, Any], positive_symbols: int) -> bool:
    candidate_net = _metric(candidate.get("net_return_pct_sum"), -math.inf)
    baseline_net = _metric(baseline.get("net_return_pct_sum"), 0.0)
    candidate_pf = _metric(candidate.get("net_profit_factor"), 0.0)
    baseline_pf = _metric(baseline.get("net_profit_factor"), 0.0)
    candidate_payoff = _metric(candidate.get("payoff_ratio"), 0.0)
    baseline_payoff = _metric(baseline.get("payoff_ratio"), 0.0)
    payoff_ok = baseline_payoff <= 0.0 or candidate_payoff >= baseline_payoff * 0.95
    return bool(
        int(candidate.get("trade_count") or 0) >= 5
        and candidate_net > 0.0
        and candidate_net > baseline_net
        and candidate_pf > 1.0
        and candidate_pf >= baseline_pf
        and payoff_ok
        and positive_symbols >= 3
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fixed-end", default=FIXED_END_ISO)
    parser.add_argument("--window-bars", type=int, default=WINDOW_BARS)
    parser.add_argument("--warmup-bars", type=int, default=WARMUP_BARS)
    parser.add_argument("--history-bars", type=int, default=HISTORY_BARS)
    parser.add_argument("--cost-bps-per-side", type=float, default=COST_BPS_PER_SIDE)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / OUTPUT_DIR
    total_bars = args.window_bars * 2
    end_ms = int(pd.Timestamp(args.fixed_end).timestamp() * 1000)
    end_ms = (end_ms // INTERVAL_MS) * INTERVAL_MS
    start_ms = end_ms - (total_bars - 1) * INTERVAL_MS
    if args.warmup_bars < 100 or args.warmup_bars >= args.window_bars:
        raise ValueError("WARMUP_CONTRACT_INVALID")
    if args.history_bars < 100:
        raise ValueError("HISTORY_CONTRACT_INVALID")

    registry = _load_registry(root)
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    blockers: list[str] = []

    for symbol in SYMBOLS:
        try:
            frame, endpoint, requests = _fetch_exact(
                symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                expected_rows=total_bars,
            )
            frames[symbol] = frame
            fetch_results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "rows": len(frame),
                    "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                    "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                    "endpoint": endpoint,
                    "request_count": requests,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    results: list[dict[str, Any]] = []
    economic_survivors: list[str] = []

    if not blockers:
        for strategy_id in STRATEGIES:
            try:
                canonical = _load_canonical_strategy(root, strategy_id, registry[strategy_id])
                repaired = load_repaired_strategy(root, strategy_id)
                window_results: list[dict[str, Any]] = []

                for window_index in range(2):
                    baseline_runs: list[dict[str, Any]] = []
                    candidate_runs: list[dict[str, Any]] = []
                    symbol_rows: list[dict[str, Any]] = []
                    start = window_index * args.window_bars
                    end = start + args.window_bars

                    for symbol in SYMBOLS:
                        window = frames[symbol].iloc[start:end].reset_index(drop=True)
                        baseline = _replay(
                            window,
                            canonical,
                            warmup_bars=args.warmup_bars,
                            history_bars=args.history_bars,
                            cost_bps_per_side=args.cost_bps_per_side,
                        )
                        candidate = _replay(
                            window,
                            repaired,
                            warmup_bars=args.warmup_bars,
                            history_bars=args.history_bars,
                            cost_bps_per_side=args.cost_bps_per_side,
                        )
                        baseline_runs.append(baseline)
                        candidate_runs.append(candidate)
                        symbol_rows.append(
                            {
                                "symbol": symbol,
                                "baseline": baseline["stats"],
                                "candidate": candidate["stats"],
                                "baseline_signal_count": baseline["signal_count"],
                                "candidate_signal_count": candidate["signal_count"],
                                "candidate_minus_baseline_net_pct": (
                                    float(candidate["stats"]["net_return_pct_sum"])
                                    - float(baseline["stats"]["net_return_pct_sum"])
                                ),
                            }
                        )

                    baseline_stats = _aggregate(baseline_runs)
                    candidate_stats = _aggregate(candidate_runs)
                    positive_symbols = sum(
                        float(row["candidate"]["net_return_pct_sum"]) > 0.0
                        for row in symbol_rows
                    )
                    window_pass = _economic_pass(candidate_stats, baseline_stats, positive_symbols)
                    window_results.append(
                        {
                            "window_id": f"W{window_index + 1}",
                            "start": pd.Timestamp(frames[SYMBOLS[0]]["timestamp"].iloc[start]).isoformat(),
                            "end": pd.Timestamp(frames[SYMBOLS[0]]["timestamp"].iloc[end - 1]).isoformat(),
                            "baseline": baseline_stats,
                            "candidate": candidate_stats,
                            "positive_symbols": positive_symbols,
                            "economic_pass": window_pass,
                            "symbols": symbol_rows,
                        }
                    )

                confirmed = all(window["economic_pass"] for window in window_results)
                if confirmed:
                    economic_survivors.append(strategy_id)
                results.append(
                    {
                        "strategy_id": strategy_id,
                        "status": "PASS",
                        "two_window_economic_survivor": confirmed,
                        "windows": window_results,
                    }
                )
            except Exception as exc:
                error = f"{strategy_id}:{type(exc).__name__}:{exc}"
                blockers.append(error)
                results.append({"strategy_id": strategy_id, "status": "HOLD", "error": error})

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_RESEARCH_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "fixed_end": pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
        "interval": INTERVAL,
        "symbols": list(SYMBOLS),
        "strategies": list(STRATEGIES),
        "window_bars": args.window_bars,
        "warmup_bars": args.warmup_bars,
        "evaluation_bars_per_window": args.window_bars - args.warmup_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "fetch_results": fetch_results,
        "results": results,
        "economic_survivors": economic_survivors,
        "economic_survivor_count": len(economic_survivors),
        "blockers": blockers,
        "canonical_sources_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": (
            "VALIDATE_SURVIVORS_ON_THIRD_NONOVERLAP_WINDOW"
            if economic_survivors and not blockers
            else "KEEP_REPAIRS_CHILD_ONLY_AND_REDESIGN_FAILED_CANDIDATES"
        ),
    }
    _atomic_json(output_dir / "summary.json", report)
    print(
        json.dumps(
            {
                "STATE": report["state"],
                "BLOCKERS": len(blockers),
                "SURVIVORS": economic_survivors,
                "SURVIVOR_COUNT": len(economic_survivors),
                "NEXT": report["next"],
            },
            sort_keys=True,
        )
    )
    for item in results:
        if item.get("status") != "PASS":
            print(f"HOLD={item}")
            continue
        print(
            f"STRATEGY={item['strategy_id']}|"
            f"TWO_WINDOW={item['two_window_economic_survivor']}|"
            + "|".join(
                f"{window['window_id']}:base_net={window['baseline']['net_return_pct_sum']:.6f},"
                f"cand_net={window['candidate']['net_return_pct_sum']:.6f},"
                f"base_pf={window['baseline']['net_profit_factor']},"
                f"cand_pf={window['candidate']['net_profit_factor']},"
                f"wr={window['candidate']['win_rate_pct']},"
                f"pos={window['positive_symbols']}/5"
                for window in item["windows"]
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
