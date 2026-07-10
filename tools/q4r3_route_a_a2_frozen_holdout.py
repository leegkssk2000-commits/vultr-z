from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd


ROOT = Path("/home/z/z")
SOURCE_30D_DIR = ROOT / "data" / "oos_a1" / "bingx_public"
HOLDOUT_DIR = ROOT / "data" / "oos_a2" / "frozen_pre30d"
OUT = ROOT / "runtime" / "q4r3_route_a_a2_frozen_holdout_latest.json"

sys.path.insert(0, str(ROOT))

SYMBOLS = {
    "BTCUSDT": "BTC-USDT",
    "ETHUSDT": "ETH-USDT",
    "SOLUSDT": "SOL-USDT",
    "XRPUSDT": "XRP-USDT",
    "LINKUSDT": "LINK-USDT",
}

API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
A2_MODULE = "backend.strategies.ema_ribbon_beam"
A2_FILE_ENV = "Q4R3_A2_FILE"

MINUTE_MS = 60_000
WINDOW_15M = 160
TIMEOUT_MIN = 240
COOLDOWN_MIN = 60
DEFAULT_HOLDOUT_DAYS = 90
REQUEST_LIMIT = 200
REQUEST_SLEEP = 0.70
COST_LEVELS = (0.10, 0.15, 0.20)

FROZEN_VOTE_MIN = 2
ORDERED_ER_MIN = 0.25
ORDERED_PERSISTENCE_MIN = 0.625
ORDERED_EXPANSION_MIN = 1.10

PROGRESS_CHECKPOINT_MIN = {
    "beam": 30,
    "reclaim": 60,
}
PROGRESS_MFE_MIN_R = {
    "beam": 0.25,
    "reclaim": 0.20,
}
PROGRESS_REDUCE_FRACTION = 0.50


def _load_module() -> Any:
    override = os.environ.get(A2_FILE_ENV)
    if not override:
        return importlib.import_module(A2_MODULE)

    path = Path(override)
    if not path.exists():
        raise FileNotFoundError(str(path))

    spec = importlib.util.spec_from_file_location(
        "q4r3_frozen_ema_ribbon_beam",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("A2_OVERRIDE_IMPORT_SPEC_FAILED")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows_from_payload(payload: Dict[str, Any]) -> List[List[float]]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []
    return rows


def _timestamp_ms(value: Any) -> int:
    stamp = int(float(value))
    return stamp * 1000 if abs(stamp) < 100_000_000_000 else stamp


def holdout_window(days: int) -> Tuple[int, int, int]:
    source = SOURCE_30D_DIR / "BTCUSDT_1m_30d_isolated.json"
    if not source.exists():
        raise FileNotFoundError(str(source))

    payload = json.loads(source.read_text(errors="ignore"))
    stamps = sorted(
        _timestamp_ms(row[0])
        for row in _rows_from_payload(payload)
        if isinstance(row, list) and len(row) >= 6
    )
    if not stamps:
        raise RuntimeError("BTC_30D_SOURCE_EMPTY")

    rows_required = int(days) * 24 * 60
    end_ms = stamps[0] - MINUTE_MS
    start_ms = end_ms - (rows_required - 1) * MINUTE_MS
    return start_ms, end_ms, rows_required


def _normalize_api_rows(payload: Dict[str, Any]) -> List[Dict[str, float]]:
    data = payload.get("data", [])
    if isinstance(data, dict):
        for key in ("data", "rows", "items", "klines", "candles"):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    if not isinstance(data, list):
        return []

    output: List[Dict[str, float]] = []

    for row in data:
        if isinstance(row, list) and len(row) >= 6:
            raw_ts, raw_open, raw_high, raw_low, raw_close, raw_volume = row[:6]
        elif isinstance(row, dict):
            raw_ts = row.get(
                "time",
                row.get(
                    "openTime",
                    row.get("timestamp", row.get("ts", row.get("t"))),
                ),
            )
            raw_open = row.get("open", row.get("o"))
            raw_high = row.get("high", row.get("h"))
            raw_low = row.get("low", row.get("l"))
            raw_close = row.get("close", row.get("c"))
            raw_volume = row.get("volume", row.get("vol", row.get("v", 0.0)))
        else:
            continue

        try:
            stamp = _timestamp_ms(raw_ts)
            open_ = float(raw_open)
            high = float(raw_high)
            low = float(raw_low)
            close = float(raw_close)
            volume = float(raw_volume or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue

        if min(open_, high, low, close) <= 0 or high < low:
            continue

        output.append(
            {
                "ts": stamp,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    return output


def _fetch_page(api_symbol: str, end_ms: int) -> List[Dict[str, float]]:
    query = urllib.parse.urlencode(
        {
            "symbol": api_symbol,
            "interval": "1m",
            "limit": REQUEST_LIMIT,
            "endTime": int(end_ms),
        }
    )
    request = urllib.request.Request(
        API + "?" + query,
        headers={
            "Accept": "application/json",
            "User-Agent": "ZEL-Q4R3-A2-FROZEN-HOLDOUT/1.0",
        },
    )

    last_error = "UNKNOWN"

    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(
                    response.read().decode("utf-8", errors="replace")
                )

            if payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(
                    f"BINGX_CODE={payload.get('code')}:"
                    f"{payload.get('msg', payload.get('message'))}"
                )

            rows = _normalize_api_rows(payload)
            if not rows:
                raise RuntimeError("EMPTY_PAGE")
            return rows
        except Exception as exc:
            last_error = repr(exc)
            time.sleep(min(2 ** attempt, 20))

    raise RuntimeError(f"FETCH_FAILED:{last_error}")


def _validate_holdout_file(
    path: Path,
    start_ms: int,
    end_ms: int,
    rows_required: int,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    if not path.exists():
        return False, None, "MISSING"

    try:
        payload = json.loads(path.read_text(errors="ignore"))
    except Exception as exc:
        return False, None, f"JSON_ERROR:{repr(exc)}"

    stamps = sorted(
        {
            _timestamp_ms(row[0])
            for row in _rows_from_payload(payload)
            if isinstance(row, list) and len(row) >= 6
        }
    )

    if len(stamps) != rows_required:
        return False, payload, f"COUNT={len(stamps)}"
    if stamps[0] != start_ms:
        return False, payload, "START_MISMATCH"
    if stamps[-1] != end_ms:
        return False, payload, "END_MISMATCH"
    if any(
        stamps[index] - stamps[index - 1] != MINUTE_MS
        for index in range(1, len(stamps))
    ):
        return False, payload, "GAP"

    return True, payload, "PASS"


def collect_symbol(
    symbol: str,
    api_symbol: str,
    start_ms: int,
    end_ms: int,
    rows_required: int,
) -> Tuple[Path, Dict[str, Any], int]:
    days = rows_required // (24 * 60)
    path = HOLDOUT_DIR / f"{symbol}_1m_{days}d_pre30d.json"
    valid, payload, _ = _validate_holdout_file(
        path,
        start_ms,
        end_ms,
        rows_required,
    )
    if valid and payload is not None:
        print(f"REUSE {symbol} rows={rows_required}", flush=True)
        return path, payload, 0

    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    candles: Dict[int, Dict[str, float]] = {}
    cursor = end_ms
    pages = 0
    max_pages = math.ceil(rows_required / REQUEST_LIMIT) + 20

    for page in range(1, max_pages + 1):
        api_rows = _fetch_page(api_symbol, cursor)
        pages = page

        for row in api_rows:
            stamp = int(row["ts"])
            if start_ms <= stamp <= end_ms:
                candles[stamp] = row

        oldest = min(int(row["ts"]) for row in api_rows)
        if page % 100 == 0:
            print(
                f"COLLECT {symbol} page={page} unique={len(candles)}",
                flush=True,
            )

        if oldest <= start_ms:
            break

        cursor = oldest - MINUTE_MS
        time.sleep(REQUEST_SLEEP)

    ordered = [candles[stamp] for stamp in sorted(candles)]
    stamps = [int(row["ts"]) for row in ordered]
    failures: List[str] = []

    if len(ordered) != rows_required:
        failures.append(f"COUNT={len(ordered)}")
    if stamps and stamps[0] != start_ms:
        failures.append("START_MISMATCH")
    if stamps and stamps[-1] != end_ms:
        failures.append("END_MISMATCH")
    gaps = sum(
        stamps[index] - stamps[index - 1] != MINUTE_MS
        for index in range(1, len(stamps))
    )
    if gaps:
        failures.append(f"GAPS={gaps}")

    if failures:
        raise RuntimeError(f"{symbol}:{','.join(failures)}")

    payload = {
        "symbol": symbol,
        "source": "bingx_public",
        "timeframe": "1m",
        "window_relation": "strictly_before_existing_30d_sample",
        "start_ms": start_ms,
        "end_ms": end_ms,
        "rows_count": len(ordered),
        "rows": [
            [
                int(row["ts"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            ]
            for row in ordered
        ],
    }

    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)
    print(f"PASS COLLECT {symbol} rows={len(ordered)}", flush=True)
    return path, payload, pages


def frame_from_payload(payload: Dict[str, Any]) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []

    for row in _rows_from_payload(payload):
        if not isinstance(row, list) or len(row) < 6:
            continue

        stamp = _timestamp_ms(row[0])
        records.append(
            {
                "ts": stamp,
                "ts_dt": pd.to_datetime(stamp, unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )

    frame = pd.DataFrame(records)
    if frame.empty:
        raise RuntimeError("EMPTY_FRAME")

    frame = (
        frame.sort_values("ts_dt")
        .drop_duplicates("ts_dt", keep="last")
        .reset_index(drop=True)
    )
    frame["raw_idx"] = range(len(frame))

    diffs = frame["ts_dt"].diff().dt.total_seconds().dropna()
    if int(frame["ts_dt"].duplicated().sum()) != 0:
        raise RuntimeError("DUPLICATE_TS")
    if int((diffs != 60).sum()) != 0:
        raise RuntimeError("ONE_MINUTE_GAPS")

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


def efficiency_ratio(close: pd.Series, lookback: int = 20) -> float:
    if len(close) < lookback + 1:
        return 0.0
    segment = close.iloc[-(lookback + 1) :].astype(float)
    direction = abs(float(segment.iloc[-1] - segment.iloc[0]))
    volatility = float(segment.diff().abs().sum())
    return direction / volatility if volatility > 0 else 0.0


def directional_persistence(
    close: pd.Series,
    side: str,
    lookback: int = 8,
) -> float:
    if len(close) < lookback + 1:
        return 0.0
    delta = close.astype(float).diff().iloc[-lookback:]
    if side == "long":
        return float((delta > 0).mean())
    return float((delta < 0).mean())


def ensemble_votes(close: pd.Series, side: str) -> int:
    votes = 0
    for fast, mid, slow in ((5, 13, 34), (8, 21, 55), (13, 34, 89)):
        if len(close) < slow + 5:
            continue
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_mid = close.ewm(span=mid, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()

        fast_now = float(ema_fast.iloc[-1])
        mid_now = float(ema_mid.iloc[-1])
        slow_now = float(ema_slow.iloc[-1])
        fast_then = float(ema_fast.iloc[-4])
        mid_then = float(ema_mid.iloc[-4])

        if side == "long":
            aligned = (
                fast_now > mid_now > slow_now
                and fast_now > fast_then
                and mid_now > mid_then
            )
        else:
            aligned = (
                fast_now < mid_now < slow_now
                and fast_now < fast_then
                and mid_now < mid_then
            )
        votes += int(aligned)
    return votes


def transition_regime(
    window: pd.DataFrame,
    side: str,
    votes: int,
    expansion_ratio: float,
) -> Dict[str, Any]:
    close = window["close"].astype(float)
    er = efficiency_ratio(close)
    persistence = directional_persistence(close, side)

    if votes < FROZEN_VOTE_MIN:
        label = "REVERSAL_RISK"
    elif (
        er >= ORDERED_ER_MIN
        and persistence >= ORDERED_PERSISTENCE_MIN
        and expansion_ratio >= ORDERED_EXPANSION_MIN
    ):
        label = "ORDERED_EXPANSION"
    else:
        label = "DISORDERED_EXPANSION"

    return {
        "regime": label,
        "efficiency_ratio": er,
        "directional_persistence": persistence,
        "ensemble_votes": votes,
        "expansion_ratio": expansion_ratio,
    }


def collect_signals(
    symbol: str,
    frame_1m: pd.DataFrame,
    bars_15m: pd.DataFrame,
    module: Any,
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

        strategy_frame = window[columns].copy()

        try:
            result = module.strategy(
                strategy_frame,
                state={},
                risk_action="hold",
            )
        except Exception as exc:
            counts["strategy_error"] += 1
            if len(errors) < 20:
                errors.append({"end_i": end_i, "error": repr(exc)})
            continue

        counts["windows"] += 1
        reason = str(result.get("why", "UNKNOWN"))
        reasons[reason] += 1

        side = active_side(result)
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

        levels = levels_rebased(result, float(entry_row["open"]), side)
        if levels is None:
            counts["invalid_native_levels"] += 1
            continue

        votes = ensemble_votes(window["close"], side)
        expansion_ratio = float(result.get("expansion_ratio", 0.0) or 0.0)
        regime = transition_regime(window, side, votes, expansion_ratio)
        trigger = "beam" if bool(result.get("beam", False)) else "reclaim"

        signals.append(
            {
                "symbol": symbol,
                "side": side,
                "trigger": trigger,
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
                **regime,
            }
        )

    return {
        "signals": signals,
        "counts": dict(counts),
        "reason_top20": reasons.most_common(20),
        "errors": errors,
    }


def _mark_to_market_r(
    side: str,
    entry: float,
    price: float,
    risk_pct: float,
) -> float:
    if side == "long":
        gross_pct = (price / entry - 1.0) * 100.0
    else:
        gross_pct = (entry / price - 1.0) * 100.0
    return gross_pct / risk_pct


def simulate_one(
    frame: pd.DataFrame,
    signal: Dict[str, Any],
    *,
    cost_pct: float,
    progress_reduce: bool,
) -> Dict[str, Any]:
    entry_i = int(signal["entry_i"])
    entry = float(signal["entry"])
    sl = float(signal["sl"])
    tp = float(signal["tp"])
    side = str(signal["side"])
    trigger = str(signal["trigger"])
    risk_pct = float(signal["risk_pct"])

    last_i = min(len(frame) - 1, entry_i + TIMEOUT_MIN - 1)
    checkpoint = PROGRESS_CHECKPOINT_MIN[trigger]
    checkpoint_i = min(last_i, entry_i + checkpoint - 1)

    mfe_r = 0.0
    mae_r = 0.0
    partial_taken = False
    partial_r = 0.0
    remaining_fraction = 1.0
    ambiguity = False

    for index in range(entry_i, last_i + 1):
        row = frame.iloc[index]
        high = float(row["high"])
        low = float(row["low"])

        if side == "long":
            favourable_r = ((high / entry - 1.0) * 100.0) / risk_pct
            adverse_r = ((low / entry - 1.0) * 100.0) / risk_pct
            tp_hit = high >= tp
            sl_hit = low <= sl
        else:
            favourable_r = ((entry / low - 1.0) * 100.0) / risk_pct
            adverse_r = ((entry / high - 1.0) * 100.0) / risk_pct
            tp_hit = low <= tp
            sl_hit = high >= sl

        mfe_r = max(mfe_r, favourable_r)
        mae_r = min(mae_r, adverse_r)

        if tp_hit and sl_hit:
            result = "BOTH_SAME_1M_BAR_SL"
            exit_r = -1.0
            ambiguity = True
            exit_i = index
            break

        if sl_hit:
            result = "SL"
            exit_r = -1.0
            exit_i = index
            break

        if tp_hit:
            result = "TP"
            exit_r = float(signal["rr"])
            exit_i = index
            break

        if (
            progress_reduce
            and not partial_taken
            and index == checkpoint_i
        ):
            close_price = float(row["close"])
            current_r = _mark_to_market_r(side, entry, close_price, risk_pct)
            if (
                mfe_r < PROGRESS_MFE_MIN_R[trigger]
                and current_r < 0.0
            ):
                partial_taken = True
                partial_r = current_r * PROGRESS_REDUCE_FRACTION
                remaining_fraction = 1.0 - PROGRESS_REDUCE_FRACTION
    else:
        exit_i = last_i
        close_price = float(frame.iloc[exit_i]["close"])
        exit_r = _mark_to_market_r(side, entry, close_price, risk_pct)
        result = "TIMEOUT"

    gross_r = partial_r + remaining_fraction * exit_r
    round_trips = 2 if partial_taken else 1
    net_r = gross_r - (cost_pct / risk_pct) * round_trips

    return {
        **signal,
        "exit_ts": str(frame.iloc[exit_i]["ts_dt"]),
        "result": result,
        "gross_R": round(gross_r, 8),
        "net_R": round(net_r, 8),
        "mfe_R": round(mfe_r, 8),
        "mae_R": round(mae_r, 8),
        "bars_1m": exit_i - entry_i + 1,
        "partial_taken": partial_taken,
        "same_1m_bar_ambiguity": ambiguity,
    }


def simulate_variant(
    frames: Dict[str, pd.DataFrame],
    signals: Iterable[Dict[str, Any]],
    *,
    votes_min: Optional[int],
    cost_pct: float,
    progress_reduce: bool,
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for signal in signals:
        if votes_min is not None and int(signal["ensemble_votes"]) < votes_min:
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

            trade = simulate_one(
                frames[symbol],
                signal,
                cost_pct=cost_pct,
                progress_reduce=progress_reduce,
            )
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
            "median_net_R": 0.0,
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
            round(gains / losses, 6) if losses > 0 else 999.0
        ),
        "max_drawdown_R": round(max_drawdown_r(trades), 8),
        "ambiguity_count": sum(
            bool(trade["same_1m_bar_ambiguity"])
            for trade in trades
        ),
    }


def grouped_summary(
    trades: List[Dict[str, Any]],
    field: str,
) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade[field])].append(trade)
    return {
        key: summarize(rows)
        for key, rows in sorted(grouped.items())
    }


def monthly_summary(
    trades: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = pd.Timestamp(trade["entry_ts"]).strftime("%Y-%m")
        grouped[key].append(trade)
    return {
        key: summarize(rows)
        for key, rows in sorted(grouped.items())
    }


def positive_month_ratio(
    monthly: Dict[str, Dict[str, Any]],
) -> float:
    if not monthly:
        return 0.0
    positive = sum(
        summary["events"] > 0 and summary["net_sum_R"] > 0
        for summary in monthly.values()
    )
    return positive / len(monthly)


def assess(
    summary: Dict[str, Any],
    by_symbol: Dict[str, Dict[str, Any]],
    monthly: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    positive_symbols = sum(
        row["events"] > 0 and row["net_sum_R"] > 0
        for row in by_symbol.values()
    )
    month_ratio = positive_month_ratio(monthly)

    gates = {
        "events_ge_100": summary["events"] >= 100,
        "avg_R_ge_0_15": summary["avg_net_R"] >= 0.15,
        "pf_ge_1_2": summary["profit_factor_R"] >= 1.20,
        "mdd_le_8R": summary["max_drawdown_R"] <= 8.0,
        "positive_symbols_ge_3": positive_symbols >= 3,
        "positive_month_ratio_ge_60pct": month_ratio >= 0.60,
        "ambiguity_zero": summary["ambiguity_count"] == 0,
    }

    return {
        "gates": gates,
        "positive_symbols": positive_symbols,
        "positive_month_ratio_pct": round(month_ratio * 100.0, 3),
        "hard_gate_pass": all(gates.values()),
    }


def main() -> None:
    days = int(os.environ.get("Q4R3_HOLDOUT_DAYS", DEFAULT_HOLDOUT_DAYS))
    if days not in {60, 90, 120, 180}:
        raise SystemExit("Q4R3_HOLDOUT_DAYS_MUST_BE_60_90_120_OR_180")

    start_ms, end_ms, rows_required = holdout_window(days)
    module = _load_module()
    module_source = inspect.getsource(module)

    frames: Dict[str, pd.DataFrame] = {}
    reports: Dict[str, Any] = {}
    collection_pages: Dict[str, int] = {}
    all_signals: List[Dict[str, Any]] = []
    hard_fail: List[str] = []

    for symbol, api_symbol in SYMBOLS.items():
        try:
            path, payload, pages = collect_symbol(
                symbol,
                api_symbol,
                start_ms,
                end_ms,
                rows_required,
            )
            frame = frame_from_payload(payload)
            bars = make_15m(frame)
            pack = collect_signals(symbol, frame, bars, module)
        except Exception as exc:
            hard_fail.append(f"{symbol}:{repr(exc)}")
            continue

        frames[symbol] = frame
        collection_pages[symbol] = pages
        reports[symbol] = {
            "path": str(path),
            "rows_1m": len(frame),
            "counts": pack["counts"],
            "reason_top20": pack["reason_top20"],
            "errors": pack["errors"],
        }
        all_signals.extend(pack["signals"])

        if pack["errors"]:
            hard_fail.append(f"{symbol}:STRATEGY_RUNTIME_ERROR")

    baseline = simulate_variant(
        frames,
        all_signals,
        votes_min=None,
        cost_pct=0.10,
        progress_reduce=False,
    )
    frozen = simulate_variant(
        frames,
        all_signals,
        votes_min=FROZEN_VOTE_MIN,
        cost_pct=0.10,
        progress_reduce=False,
    )
    progress = simulate_variant(
        frames,
        all_signals,
        votes_min=FROZEN_VOTE_MIN,
        cost_pct=0.10,
        progress_reduce=True,
    )

    baseline_summary = summarize(baseline)
    frozen_summary = summarize(frozen)
    progress_summary = summarize(progress)

    if baseline_summary["ambiguity_count"]:
        hard_fail.append("BASELINE_1M_AMBIGUITY")
    if frozen_summary["ambiguity_count"]:
        hard_fail.append("FROZEN_1M_AMBIGUITY")
    if progress_summary["ambiguity_count"]:
        hard_fail.append("PROGRESS_1M_AMBIGUITY")

    frozen_by_symbol = grouped_summary(frozen, "symbol")
    frozen_monthly = monthly_summary(frozen)
    frozen_assessment = assess(
        frozen_summary,
        frozen_by_symbol,
        frozen_monthly,
    )

    cost_stress: Dict[str, Dict[str, Any]] = {}
    for cost in COST_LEVELS:
        trades = simulate_variant(
            frames,
            all_signals,
            votes_min=FROZEN_VOTE_MIN,
            cost_pct=cost,
            progress_reduce=False,
        )
        cost_stress[f"cost_{cost:.2f}"] = summarize(trades)

    if hard_fail:
        verdict = "HOLD_TECHNICAL_FAIL"
    elif frozen_assessment["hard_gate_pass"]:
        verdict = "A2_FROZEN_VOTES_GE_2_HOLDOUT_PASS"
    elif (
        frozen_summary["events"] >= 50
        and frozen_summary["avg_net_R"] > 0
        and frozen_summary["profit_factor_R"] > 1.0
    ):
        verdict = "A2_FROZEN_POSITIVE_BUT_BELOW_PROMOTION_GATE"
    else:
        verdict = "A2_FROZEN_HOLDOUT_WEAK_OR_NEGATIVE"

    payload = {
        "status": (
            "PASS_Q4R3_ROUTE_A_A2_FROZEN_HOLDOUT"
            if not hard_fail
            else "HOLD_Q4R3_ROUTE_A_A2_FROZEN_HOLDOUT"
        ),
        "verdict": verdict,
        "hard_fail": sorted(set(hard_fail)),
        "scope": (
            f"A2 frozen candidate {days}d holdout strictly before the "
            "existing 30d research sample"
        ),
        "holdout": {
            "days": days,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start": str(pd.to_datetime(start_ms, unit="ms", utc=True)),
            "end": str(pd.to_datetime(end_ms, unit="ms", utc=True)),
            "rows_per_symbol": rows_required,
            "non_overlap_rule": (
                "holdout_end = earliest timestamp in existing BTC 30d "
                "sample minus one minute"
            ),
        },
        "frozen_contract": {
            "strategy": "ema_ribbon_beam",
            "timeframe": "15m",
            "window_bars": WINDOW_15M,
            "entry": "next_1m_open",
            "exit": "strategy_native_levels_rebased",
            "timeout_min": TIMEOUT_MIN,
            "cooldown_min": COOLDOWN_MIN,
            "cost_pct": 0.10,
            "ensemble_vote_min": FROZEN_VOTE_MIN,
            "ema_sets": [
                [5, 13, 34],
                [8, 21, 55],
                [13, 34, 89],
            ],
            "trial_count": 1,
            "selection_origin": (
                "predeclared from prior 30d forensic result; no threshold "
                "search on this holdout"
            ),
        },
        "source": {
            "a2_module": A2_MODULE,
            "a2_file_override": os.environ.get(A2_FILE_ENV),
            "a2_sha256": hashlib.sha256(
                module_source.encode()
            ).hexdigest(),
        },
        "collection_pages_new": collection_pages,
        "signals_before_cooldown": len(all_signals),
        "baseline_unfiltered": {
            "summary": baseline_summary,
            "by_symbol": grouped_summary(baseline, "symbol"),
        },
        "frozen_votes_ge_2": {
            "summary": frozen_summary,
            "assessment": frozen_assessment,
            "by_symbol": frozen_by_symbol,
            "by_side": grouped_summary(frozen, "side"),
            "by_trigger": grouped_summary(frozen, "trigger"),
            "by_regime": grouped_summary(frozen, "regime"),
            "by_month": frozen_monthly,
            "cost_stress": cost_stress,
        },
        "causal_exit_observer": {
            "contract": {
                "type": "reduce_50pct_only",
                "beam_checkpoint_min": PROGRESS_CHECKPOINT_MIN["beam"],
                "reclaim_checkpoint_min": PROGRESS_CHECKPOINT_MIN["reclaim"],
                "beam_mfe_min_R": PROGRESS_MFE_MIN_R["beam"],
                "reclaim_mfe_min_R": PROGRESS_MFE_MIN_R["reclaim"],
                "requires_current_R_lt_0": True,
                "promotion_allowed_from_this_run": False,
            },
            "summary": progress_summary,
            "by_symbol": grouped_summary(progress, "symbol"),
        },
        "transition_regime_observer": {
            "ordered_expansion": {
                "ensemble_votes_min": FROZEN_VOTE_MIN,
                "efficiency_ratio_min": ORDERED_ER_MIN,
                "directional_persistence_min": ORDERED_PERSISTENCE_MIN,
                "expansion_ratio_min": ORDERED_EXPANSION_MIN,
            },
            "labels": [
                "ORDERED_EXPANSION",
                "DISORDERED_EXPANSION",
                "REVERSAL_RISK",
            ],
            "promotion_allowed_from_this_run": False,
        },
        "per_symbol_signal_audit": reports,
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "paper_request_written": False,
        "live_execution_allowed": False,
        "next": (
            "If the frozen candidate passes, repeat on the remaining "
            "non-overlapping history or walk-forward paper. If it is only "
            "weakly positive, preserve it as observer-only. If negative, "
            "close Route A and move to Route B."
        ),
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
                "holdout": payload["holdout"],
                "baseline": baseline_summary,
                "frozen_votes_ge_2": frozen_summary,
                "frozen_assessment": frozen_assessment,
                "cost_stress": cost_stress,
                "causal_exit_observer": progress_summary,
                "out": str(OUT),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
