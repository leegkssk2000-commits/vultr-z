from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


ROOT = Path("/home/z/z")
DATA_DIR = ROOT / "data" / "oos_a1" / "bingx_public"
OUT = ROOT / "runtime" / "q4r3_route_a_a2_oos_replay_latest.json"

sys.path.insert(0, str(ROOT))

SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "LINKUSDT",
)

A2_MODULE = "backend.strategies.ema_ribbon_beam"
A1_MODULE = "backend.strategies.trend_ma_macd"

WINDOW_15M = 160
TIMEOUT_MIN = 240
COOLDOWN_MIN = 60
COST_PCT = 0.10

TUNING_START = pd.Timestamp("2026-06-29 19:30:00", tz="UTC")
TUNING_END = pd.Timestamp("2026-07-06 18:09:00", tz="UTC")


def load_1m(symbol: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol}_1m_30d_isolated.json"
    if not path.exists():
        raise FileNotFoundError(str(path))

    payload = json.loads(path.read_text(errors="ignore"))
    rows: List[Dict[str, Any]] = []

    for row in payload.get("rows", []):
        if not isinstance(row, list) or len(row) < 6:
            continue

        ts = int(float(row[0]))
        if abs(ts) < 100_000_000_000:
            ts *= 1000

        rows.append(
            {
                "ts": ts,
                "ts_dt": pd.to_datetime(ts, unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError(f"{symbol}:EMPTY_DATA")

    frame = (
        frame.sort_values("ts_dt")
        .drop_duplicates("ts_dt", keep="last")
        .reset_index(drop=True)
    )
    frame["raw_idx"] = range(len(frame))

    diffs = frame["ts_dt"].diff().dt.total_seconds().dropna()
    if int(frame["ts_dt"].duplicated().sum()) != 0:
        raise RuntimeError(f"{symbol}:DUPLICATE_TS")
    if int((diffs != 60).sum()) != 0:
        raise RuntimeError(f"{symbol}:ONE_MINUTE_GAPS")

    return frame


def make_15m(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["bucket"] = data["ts_dt"].dt.floor("15min")

    bars = data.groupby("bucket").agg(
        ts=("ts", "last"),
        ts_dt=("ts_dt", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        raw_start_idx=("raw_idx", "min"),
        raw_end_idx=("raw_idx", "max"),
        raw_count=("raw_idx", "count"),
        min_dt=("ts_dt", "min"),
        max_dt=("ts_dt", "max"),
    ).reset_index()

    bars["span_min"] = (
        bars["max_dt"] - bars["min_dt"]
    ).dt.total_seconds() / 60.0

    bars["complete"] = (
        (bars["raw_count"] == 15)
        & bars["span_min"].between(13.5, 14.5)
    )

    return bars.reset_index(drop=True)


def contiguous(window: pd.DataFrame) -> bool:
    if len(window) != WINDOW_15M or not bool(window["complete"].all()):
        return False

    diffs = window["bucket"].diff().dt.total_seconds().dropna()
    return bool((diffs == 900).all())


def strict_oos(window: pd.DataFrame) -> bool:
    start = window["min_dt"].iloc[0]
    end = window["max_dt"].iloc[-1]
    return end < TUNING_START or start > TUNING_END


def invoke(module: Any, frame: pd.DataFrame) -> Dict[str, Any]:
    result = module.strategy(
        frame,
        state={},
        risk_action="hold",
    )
    return result if isinstance(result, dict) else {}


def active_side(result: Dict[str, Any]) -> str:
    action = str(result.get("action", "")).lower()
    side = str(result.get("side", "")).lower()

    if action in {"", "hold", "none"}:
        return ""

    return side if side in {"long", "short"} else ""


def levels_rebased(
    result: Dict[str, Any],
    actual_entry: float,
    side: str,
) -> Optional[Dict[str, float]]:
    try:
        source_entry = float(result["entry"])
        source_sl = float(result["sl"])
        source_tp = float(result["tp"])
    except (KeyError, TypeError, ValueError):
        return None

    if min(source_entry, source_sl, source_tp, actual_entry) <= 0:
        return None

    if side == "long":
        if not source_sl < source_entry < source_tp:
            return None
        risk_pct = (source_entry - source_sl) / source_entry * 100.0
        reward_pct = (source_tp - source_entry) / source_entry * 100.0
        sl = actual_entry * (1.0 - risk_pct / 100.0)
        tp = actual_entry * (1.0 + reward_pct / 100.0)
    else:
        if not source_tp < source_entry < source_sl:
            return None
        risk_pct = (source_sl - source_entry) / source_entry * 100.0
        reward_pct = (source_entry - source_tp) / source_entry * 100.0
        sl = actual_entry * (1.0 + risk_pct / 100.0)
        tp = actual_entry * (1.0 - reward_pct / 100.0)

    if risk_pct <= 0 or reward_pct <= 0 or risk_pct > 10:
        return None

    return {
        "entry": actual_entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr": reward_pct / risk_pct,
    }


def collect_signals(
    symbol: str,
    frame_1m: pd.DataFrame,
    bars_15m: pd.DataFrame,
    a2: Any,
    a1: Any,
) -> Dict[str, Any]:
    columns = ["ts", "open", "high", "low", "close", "volume"]
    signals: List[Dict[str, Any]] = []
    counts = Counter()
    reasons = Counter()
    errors: List[Dict[str, Any]] = []

    for end_i in range(WINDOW_15M, len(bars_15m) + 1):
        window = bars_15m.iloc[end_i - WINDOW_15M : end_i]

        if not contiguous(window):
            counts["gap_reject"] += 1
            continue

        if not strict_oos(window):
            counts["tuning_overlap_reject"] += 1
            continue

        strategy_frame = window[columns].copy()

        try:
            a2_result = invoke(a2, strategy_frame)
            a1_result = invoke(a1, strategy_frame)
        except Exception as exc:
            counts["strategy_error"] += 1
            if len(errors) < 20:
                errors.append(
                    {
                        "end_i": end_i,
                        "error": repr(exc),
                    }
                )
            continue

        counts["windows"] += 1
        reason = str(a2_result.get("why", "UNKNOWN"))
        reasons[reason] += 1

        side = active_side(a2_result)
        if not side:
            counts["hold"] += 1
            continue

        counts["signals"] += 1
        counts[f"signal_{side}"] += 1

        signal_bar = window.iloc[-1]
        entry_i = int(signal_bar["raw_end_idx"]) + 1
        if entry_i >= len(frame_1m):
            counts["missing_next_open"] += 1
            continue

        entry_row = frame_1m.iloc[entry_i]
        expected = signal_bar["ts_dt"] + pd.Timedelta(minutes=1)
        if entry_row["ts_dt"] != expected:
            counts["entry_alignment_error"] += 1
            continue

        levels = levels_rebased(
            a2_result,
            float(entry_row["open"]),
            side,
        )
        if levels is None:
            counts["invalid_native_levels"] += 1
            continue

        a1_side = active_side(a1_result)
        confirmed = a1_side == side

        signals.append(
            {
                "symbol": symbol,
                "side": side,
                "signal_ts": str(signal_bar["ts_dt"]),
                "entry_i": entry_i,
                "entry_ts": str(entry_row["ts_dt"]),
                "entry_epoch": float(entry_row["ts_dt"].timestamp()),
                "entry": levels["entry"],
                "sl": levels["sl"],
                "tp": levels["tp"],
                "risk_pct": levels["risk_pct"],
                "reward_pct": levels["reward_pct"],
                "rr": levels["rr"],
                "why": reason,
                "beam": bool(a2_result.get("beam", False)),
                "a1_confirmed": confirmed,
                "a1_side": a1_side,
                "a1_why": str(a1_result.get("why", "")),
            }
        )

    return {
        "signals": signals,
        "counts": dict(counts),
        "reason_top20": reasons.most_common(20),
        "errors": errors,
    }


def simulate_one(
    frame: pd.DataFrame,
    signal: Dict[str, Any],
) -> Dict[str, Any]:
    entry_i = int(signal["entry_i"])
    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp = float(signal["tp"])
    side = str(signal["side"])
    risk_pct = float(signal["risk_pct"])

    last_i = min(
        len(frame) - 1,
        entry_i + TIMEOUT_MIN - 1,
    )

    mfe_pct = 0.0
    mae_pct = 0.0
    ambiguity = False

    for index in range(entry_i, last_i + 1):
        row = frame.iloc[index]
        high = float(row["high"])
        low = float(row["low"])

        if side == "long":
            mfe_pct = max(mfe_pct, (high / entry - 1.0) * 100.0)
            mae_pct = min(mae_pct, (low / entry - 1.0) * 100.0)
            tp_hit = high >= tp
            sl_hit = low <= sl
        else:
            mfe_pct = max(mfe_pct, (entry / low - 1.0) * 100.0)
            mae_pct = min(mae_pct, (entry / high - 1.0) * 100.0)
            tp_hit = low <= tp
            sl_hit = high >= sl

        if tp_hit and sl_hit:
            result = "BOTH_SAME_1M_BAR_SL"
            gross_pct = -risk_pct
            ambiguity = True
            exit_i = index
            break

        if sl_hit:
            result = "SL"
            gross_pct = -risk_pct
            exit_i = index
            break

        if tp_hit:
            result = "TP"
            gross_pct = float(signal["reward_pct"])
            exit_i = index
            break
    else:
        exit_i = last_i
        exit_close = float(frame.iloc[exit_i]["close"])
        if side == "long":
            gross_pct = (exit_close / entry - 1.0) * 100.0
        else:
            gross_pct = (entry / exit_close - 1.0) * 100.0
        result = "TIMEOUT"

    net_pct = gross_pct - COST_PCT

    return {
        **signal,
        "exit_ts": str(frame.iloc[exit_i]["ts_dt"]),
        "result": result,
        "gross_pct": round(gross_pct, 8),
        "net_pct": round(net_pct, 8),
        "net_R": round(net_pct / risk_pct, 8),
        "mfe_pct": round(mfe_pct, 8),
        "mae_pct": round(mae_pct, 8),
        "bars_1m": exit_i - entry_i + 1,
        "same_1m_bar_ambiguity": ambiguity,
    }


def simulate_variant(
    frames: Dict[str, pd.DataFrame],
    signals: Iterable[Dict[str, Any]],
    *,
    require_a1: bool,
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        if require_a1 and not bool(signal["a1_confirmed"]):
            continue
        grouped[str(signal["symbol"])].append(signal)

    trades: List[Dict[str, Any]] = []

    for symbol, symbol_signals in grouped.items():
        next_allowed = 0

        for signal in sorted(
            symbol_signals,
            key=lambda row: int(row["entry_i"]),
        ):
            if int(signal["entry_i"]) < next_allowed:
                continue

            trade = simulate_one(frames[symbol], signal)
            trades.append(trade)
            next_allowed = int(signal["entry_i"]) + max(
                COOLDOWN_MIN,
                int(trade["bars_1m"]),
            )

    return sorted(trades, key=lambda row: float(row["entry_epoch"]))


def max_drawdown_r(trades: Iterable[Dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0

    for trade in trades:
        equity += float(trade["net_R"])
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)

    return maximum


def summarize(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {
            "events": 0,
            "avg_net_R": 0.0,
            "net_sum_R": 0.0,
            "positive_rate_pct": 0.0,
            "tp_rate_pct": 0.0,
            "sl_rate_pct": 0.0,
            "timeout_rate_pct": 0.0,
            "profit_factor_R": 0.0,
            "max_drawdown_R": 0.0,
            "ambiguity_count": 0,
        }

    values = [float(trade["net_R"]) for trade in trades]
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    count = len(trades)

    return {
        "events": count,
        "avg_net_R": round(sum(values) / count, 8),
        "median_net_R": round(statistics.median(values), 8),
        "net_sum_R": round(sum(values), 8),
        "positive_rate_pct": round(
            sum(value > 0 for value in values) / count * 100.0,
            3,
        ),
        "tp_rate_pct": round(
            sum(trade["result"] == "TP" for trade in trades)
            / count
            * 100.0,
            3,
        ),
        "sl_rate_pct": round(
            sum(
                trade["result"] in {"SL", "BOTH_SAME_1M_BAR_SL"}
                for trade in trades
            )
            / count
            * 100.0,
            3,
        ),
        "timeout_rate_pct": round(
            sum(trade["result"] == "TIMEOUT" for trade in trades)
            / count
            * 100.0,
            3,
        ),
        "profit_factor_R": (
            round(gains / losses, 6)
            if losses > 0
            else 999.0
        ),
        "max_drawdown_R": round(max_drawdown_r(trades), 8),
        "ambiguity_count": sum(
            bool(trade["same_1m_bar_ambiguity"])
            for trade in trades
        ),
    }


def by_symbol(
    trades: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade["symbol"])].append(trade)

    return {
        symbol: summarize(grouped.get(symbol, []))
        for symbol in SYMBOLS
    }


def main() -> None:
    a2 = importlib.import_module(A2_MODULE)
    a1 = importlib.import_module(A1_MODULE)

    frames: Dict[str, pd.DataFrame] = {}
    reports: Dict[str, Any] = {}
    all_signals: List[Dict[str, Any]] = []
    hard_fail: List[str] = []

    for symbol in SYMBOLS:
        try:
            frame = load_1m(symbol)
            bars = make_15m(frame)
            pack = collect_signals(symbol, frame, bars, a2, a1)
        except Exception as exc:
            hard_fail.append(f"{symbol}:{repr(exc)}")
            continue

        frames[symbol] = frame
        reports[symbol] = {
            "rows_1m": len(frame),
            "counts": pack["counts"],
            "reason_top20": pack["reason_top20"],
            "errors": pack["errors"],
        }
        all_signals.extend(pack["signals"])

        if pack["errors"]:
            hard_fail.append(f"{symbol}:STRATEGY_RUNTIME_ERROR")

    standalone = simulate_variant(
        frames,
        all_signals,
        require_a1=False,
    )
    confirmed = simulate_variant(
        frames,
        all_signals,
        require_a1=True,
    )

    standalone_summary = summarize(standalone)
    confirmed_summary = summarize(confirmed)

    if standalone_summary["ambiguity_count"]:
        hard_fail.append("A2_STANDALONE_1M_AMBIGUITY")

    if confirmed_summary["ambiguity_count"]:
        hard_fail.append("A2_A1_1M_AMBIGUITY")

    if hard_fail:
        verdict = "HOLD_TECHNICAL_FAIL"
    elif standalone_summary["events"] < 15:
        verdict = "HOLD_A2_SAMPLE_TOO_LOW"
    elif standalone_summary["avg_net_R"] <= 0:
        verdict = "A2_STANDALONE_NEGATIVE"
    elif (
        confirmed_summary["events"] >= 10
        and confirmed_summary["avg_net_R"]
        > standalone_summary["avg_net_R"]
    ):
        verdict = "A2_POSITIVE_A1_CONFIRMATION_ADDS_EDGE"
    else:
        verdict = "A2_POSITIVE_A1_CONFIRMATION_NOT_PROVEN"

    a2_source = inspect.getsource(a2)
    a1_source = inspect.getsource(a1)

    payload = {
        "status": (
            "PASS_Q4R3_ROUTE_A_A2_OOS_REPLAY"
            if not hard_fail
            else "HOLD_Q4R3_ROUTE_A_A2_OOS_REPLAY"
        ),
        "verdict": verdict,
        "hard_fail": sorted(set(hard_fail)),
        "scope": (
            "EMA Ribbon/Beam 5-symbol 30d strict OOS; "
            "A2 standalone vs strict same-side A1 confirmation"
        ),
        "contracts": {
            "timeframe": "15m",
            "window_bars": WINDOW_15M,
            "entry": "next_1m_open",
            "exit": "strategy_native_levels_rebased",
            "timeout_min": TIMEOUT_MIN,
            "cooldown_min": COOLDOWN_MIN,
            "cost_pct": COST_PCT,
            "tuning_window_excluded": {
                "start": str(TUNING_START),
                "end": str(TUNING_END),
            },
        },
        "source": {
            "a2_module": A2_MODULE,
            "a2_sha256": hashlib.sha256(
                a2_source.encode()
            ).hexdigest(),
            "a1_module": A1_MODULE,
            "a1_sha256": hashlib.sha256(
                a1_source.encode()
            ).hexdigest(),
        },
        "signals_before_cooldown": len(all_signals),
        "a1_confirmed_signals": sum(
            bool(signal["a1_confirmed"])
            for signal in all_signals
        ),
        "a2_standalone": {
            "summary": standalone_summary,
            "by_symbol": by_symbol(standalone),
        },
        "a2_plus_a1_strict_confirmation": {
            "summary": confirmed_summary,
            "by_symbol": by_symbol(confirmed),
        },
        "per_symbol_signal_audit": reports,
        "review_trades": {
            "standalone_best": sorted(
                standalone,
                key=lambda row: float(row["net_R"]),
                reverse=True,
            )[:3],
            "standalone_worst": sorted(
                standalone,
                key=lambda row: float(row["net_R"]),
            )[:3],
            "confirmed_best": sorted(
                confirmed,
                key=lambda row: float(row["net_R"]),
                reverse=True,
            )[:3],
            "confirmed_worst": sorted(
                confirmed,
                key=lambda row: float(row["net_R"]),
            )[:3],
        },
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": payload["status"],
                "verdict": verdict,
                "hard_fail": payload["hard_fail"],
                "signals_before_cooldown": len(all_signals),
                "a1_confirmed_signals": payload["a1_confirmed_signals"],
                "a2_standalone": standalone_summary,
                "a2_plus_a1_strict_confirmation": confirmed_summary,
                "out": str(OUT),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
