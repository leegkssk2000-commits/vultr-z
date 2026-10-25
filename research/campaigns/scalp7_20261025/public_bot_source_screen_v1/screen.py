"""One frozen costed replay of published Freqtrade signals, NOT Freqtrade engine parity."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
HOUR = 3_600_000
MINUTE = 60_000


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def to_ms(t: str) -> int:
    d = dt.datetime.fromisoformat(t)
    return int(d.timestamp() * 1000)


def check_source(pin: dict[str, Any]) -> dict[str, pd.DataFrame]:
    start = to_ms(pin["start_utc"])
    end = to_ms(pin["end_exclusive_utc"])
    if (end - start) // (24 * HOUR) != 60:
        raise RuntimeError("SAMPLE_DAYS_DRIFT")
    manifest_path = Path(pin["manifest_path"])
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        manifest.get("source")
        != "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
    ):
        raise RuntimeError("UNEXPECTED_SOURCE_ORIGIN")
    if manifest.get("state") != "HOLD_SOURCE_INTEGRITY":
        raise RuntimeError("EXPECTED_ARCHIVE_HOLD_STATE_CHANGED")
    census = {
        "source_manifest_sha256": sha(manifest_bytes),
        "source_manifest_status": manifest["state"],
        "requested_calendar_days": 60,
        "days_by_symbol": {},
        "raw_source_daily_sha256": {},
        "missing_dates_by_symbol": {},
        "integrity_failure_days": {},
        "availability_actual_http_received_at": "UNKNOWN_ARCHIVED_ORIGINAL_1M",
        "source_future_fill_imputed": False,
        "synthetic_minutes_inserted": 0,
    }
    result = {}
    for symbol in pin["symbols"]:
        whole = []
        digests = {}
        complete = 0
        failed = []
        absent = []
        folder = Path(pin["source_base"]) / symbol
        for day in range(start, end, 24 * HOUR):
            name = f"{day}_{day+24*HOUR}.csv.gz"
            path = folder / name
            if not path.is_file():
                absent.append(name)
                continue
            raw = path.read_bytes()
            digests[name] = sha(raw)
            try:
                df = pd.read_csv(path, compression="gzip")
                if list(df.columns) != [
                    "timestamp_ms",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ]:
                    raise ValueError("UNEXPECTED_SOURCE_COLS")
                stamps = df["timestamp_ms"].to_numpy(np.int64)
                if (
                    len(df) != 1440
                    or stamps[0] != day
                    or stamps[-1] != day + 1439 * MINUTE
                    or not np.all(np.diff(stamps) == MINUTE)
                ):
                    raise ValueError("DENSE_1440_MINUTES_NOT_MATCHED")
                z = df[["open", "high", "low", "close", "volume"]].to_numpy(np.float64)
                if (
                    not np.isfinite(z).all()
                    or (z[:, :4] <= 0).any()
                    or (z[:, 4] < 0).any()
                ):
                    raise ValueError("NAN_NEGATIVE_OHLC_VOLUME")
                if (z[:, 1] < z[:, [0, 2, 3]].max(axis=1)).any() or (
                    z[:, 2] > z[:, [0, 1, 3]].min(axis=1)
                ).any():
                    raise ValueError("OHLC_OUT_OF_BOUNDS")
            except (ValueError, KeyError, TypeError) as e:
                failed.append({"name": name, "reason": str(e)[:90]})
                continue
            whole.append(df)
            complete += 1
        if not whole:
            raise RuntimeError("ALL_DAYS_INVALID_" + symbol)
        result[symbol] = pd.concat(whole, ignore_index=True)
        census["days_by_symbol"][symbol] = complete
        census["raw_source_daily_sha256"][symbol] = digests
        census["missing_dates_by_symbol"][symbol] = absent
        census["integrity_failure_days"][symbol] = failed
        print(
            "CANONICAL_SOURCE",
            symbol,
            "VALID_DAYS",
            complete,
            "BAD",
            len(failed),
            "ABSENT",
            len(absent),
            "1M",
            len(result[symbol]),
            flush=True,
        )
    raw = (
        json.dumps(census, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    (BASE / "SOURCE_CENSUS.json").write_bytes(raw)
    print("SOURCE_CENSUS_SHA", sha(raw), flush=True)
    return result


def aggregate(frame: pd.DataFrame, interval: int) -> pd.DataFrame:
    d = frame.copy()
    d["_bucket"] = d["timestamp_ms"] // (interval * MINUTE) * (interval * MINUTE)
    gp = d.groupby("_bucket", sort=True)
    x = gp.agg(
        timestamp_ms=("timestamp_ms", "min"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n=("timestamp_ms", "count"),
        last_ts=("timestamp_ms", "max"),
    ).reset_index(drop=True)
    x = (
        x[
            (x["n"] == interval)
            & (x["timestamp_ms"] % (interval * MINUTE) == 0)
            & (x["last_ts"] == x["timestamp_ms"] + (interval - 1) * MINUTE)
        ]
        .copy()
        .reset_index(drop=True)
    )
    return x.drop(columns=["n", "last_ts"])


def ema_talib(close: pd.Series, length: int) -> pd.Series:
    a = close.to_numpy(float)
    out = np.full(len(a), np.nan)
    if len(a) < length:
        return pd.Series(out, index=close.index)
    out[length - 1] = float(np.mean(a[:length]))
    alpha = 2.0 / (length + 1)
    for i in range(length, len(a)):
        out[i] = alpha * a[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=close.index)


def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    v = close.to_numpy(float)
    out = np.full(len(v), np.nan)
    if len(v) <= n:
        return pd.Series(out, index=close.index)
    delta = np.diff(v)
    gains = np.maximum(delta, 0)
    losses = np.maximum(-delta, 0)
    up = np.mean(gains[:n])
    down = np.mean(losses[:n])
    for i in range(n, len(v)):
        if i > n:
            up = (up * (n - 1) + gains[i - 1]) / n
            down = (down * (n - 1) + losses[i - 1]) / n
        out[i] = 100 * up / (up + down) if up + down else 50
    return pd.Series(out, index=close.index)


def signals(frame: pd.DataFrame, name: str) -> tuple[np.ndarray, np.ndarray]:
    c = frame["close"].astype(float)
    enter = np.zeros(len(c), dtype=bool)
    exit = np.zeros(len(c), dtype=bool)
    if name == "BbandRsi":
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        middle = typical.rolling(20, min_periods=20).mean()
        std = typical.rolling(20, min_periods=20).std(ddof=0)
        rsi = rsi_wilder(c)
        enter = ((rsi < 30) & (c < (middle - 2 * std))).fillna(False).to_numpy(bool)
        exit = (rsi > 70).fillna(False).to_numpy(bool)
    elif name == "ClucMay72018":
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        middle = typical.rolling(20, min_periods=20).mean()
        std = typical.rolling(20, min_periods=20).std(ddof=0)
        prevvol = frame["volume"].rolling(30, min_periods=30).mean().shift(1)
        ema50 = ema_talib(c, 50)
        enter = (
            (
                (c < ema50)
                & (c < 0.985 * (middle - 2 * std))
                & (frame["volume"] < prevvol * 20)
            )
            .fillna(False)
            .to_numpy(bool)
        )
        exit = (c > middle).fillna(False).to_numpy(bool)
    elif name == "MACDStrategy_crossed":
        emafast = ema_talib(c, 12)
        emaslow = ema_talib(c, 26)
        macd = emafast - emaslow
        # Signal line only after slow EMA available; first signal at valid tail.
        first = macd.first_valid_index()
        if first is None:
            return enter, exit
        tail = macd.loc[first:]
        signal = ema_talib(tail, 9).reindex(macd.index)
        crossup = (macd > signal) & (macd.shift(1) <= signal.shift(1))
        crossdn = (macd < signal) & (macd.shift(1) >= signal.shift(1))
        tp = (frame["high"] + frame["low"] + c) / 3
        tpsma = tp.rolling(14, min_periods=14).mean()
        mad = tp.rolling(14, min_periods=14).apply(
            lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
        )
        cci = (tp - tpsma) / (0.015 * mad.replace(0, np.nan))
        enter = (crossup & (cci <= -50.0)).fillna(False).to_numpy(bool)
        exit = (crossdn & (cci >= 100.0)).fillna(False).to_numpy(bool)
    else:
        raise ValueError("UNEXPECTED_STRATEGY")
    # All published source indicators require some warm-up. Ignore first
    # 200 valid native candles, avoiding TA-Lib EMA seed variations.
    enter = np.array(enter, dtype=bool, copy=True)
    exit = np.array(exit, dtype=bool, copy=True)
    enter[:200] = False
    exit[:200] = False
    return enter, exit


def simulate(
    frame: pd.DataFrame, symbol: str, strategy: str, cfg: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enter, exit = signals(frame, strategy)
    t = frame["timestamp_ms"].to_numpy(np.int64)
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    low_prices = frame["low"].to_numpy(float)
    fee = cfg["stoploss"]
    roi = {int(k): float(v) for k, v in cfg["roi_schedule_minutes"].items()}
    step = 5 if cfg["timeframe"] == "5m" else 60
    trades = []
    active = None
    candidates = int(np.sum(enter))
    for i in range(201, len(frame)):
        # Ensure the next bar is contiguous, don't carry positions through
        # unknown gaps or missing intervals, and don't grant phantom entry.
        if t[i] - t[i - 1] != step * MINUTE:
            active = None
            continue
        if active is None and enter[i - 1] and not exit[i - 1]:
            entry = float(o[i])
            active = {
                "entry_ts": int(t[i]),
                "signal_ts": int(t[i - 1]),
                "entry": entry,
                "index": i,
            }
        if active is None:
            continue
        entry = float(active["entry"])
        minutes = (i - int(active["index"])) * step
        applicable = max((k for k in roi if k <= minutes), default=0)
        tp = entry * (1 + roi[applicable])
        stop = entry * (1 + fee)
        reason = None
        px = None
        if int(active["index"]) != i and exit[i - 1]:
            reason = "EXIT_SIGNAL_NEXT_OPEN"
            px = float(o[i])
        elif float(o[i]) <= stop:
            reason = "STOP_GAP_OPEN"
            px = float(o[i])
        elif float(low_prices[i]) <= stop:
            reason = "STOP_INTRABAR_FIRST"
            px = stop
        elif float(o[i]) >= tp:
            reason = "ROI_GAP_OPEN"
            px = float(o[i])
        elif float(h[i]) >= tp:
            reason = "ROI_INTRABAR"
            px = tp
        if reason is not None and px is not None:
            gross = (px / entry - 1) * 10000
            trades.append(
                {
                    "strategy": strategy,
                    "symbol": symbol,
                    "entry_ts": active["entry_ts"],
                    "signal_ts": active["signal_ts"],
                    "exit_ts": int(t[i]),
                    "entry": entry,
                    "exit": px,
                    "gross_bps": gross,
                    "net20_bps": gross - 20,
                    "net40_bps": gross - 40,
                    "reason": reason,
                    "holding_candles": i - int(active["index"]) + 1,
                }
            )
            active = None
    return trades, {
        "signal_count_closed_bars": candidates,
        "unresolved_at_end": int(active is not None),
        "candles": len(frame),
    }


def stats(trades: list[dict[str, Any]], bps: int) -> dict[str, Any]:
    rows = sorted(trades, key=lambda x: (x["exit_ts"], x["symbol"], x["entry_ts"]))
    vals = [x[f"net{bps}_bps"] for x in rows]
    profit = sum(v for v in vals if v > 0)
    loss = -sum(v for v in vals if v < 0)
    cum = peak = dd = 0.0
    streak = mx = 0
    for v in vals:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        streak = streak + 1 if v < 0 else 0
        mx = max(mx, streak)
    return {
        "T": len(vals),
        "Net_trade_bps_sum": sum(vals),
        "Net_per_trade_bps": sum(vals) / len(vals) if vals else None,
        "PF": profit / loss if loss else None,
        "WR_pct": 100 * sum(v > 0 for v in vals) / len(vals) if vals else None,
        "DD_realized_trade_bps": dd,
        "max_loss_streak": mx,
        "largest_win_trade_bps": max(vals) if vals else None,
        "worst_loss_trade_bps": min(vals) if vals else None,
        "Net_without_best_2_trade_bps": sum(vals)
        - sum(sorted((v for v in vals if v > 0), reverse=True)[:2]),
    }


def run() -> dict[str, Any]:
    freeze_raw = (BASE / "FREEZE.json").read_bytes()
    freeze = json.loads(freeze_raw)
    assert freeze["schema"] == "zel.publicbot.source_precise_cheap_screen.v1"
    import zipfile

    archive = BASE / "UPSTREAM_GPL3_ORIGINALS.zip"
    with zipfile.ZipFile(archive) as originals:
        for name, pin in freeze["original_source_pins"].items():
            if sha(originals.read(name)) != pin["sha256"]:
                raise RuntimeError("PUBLIC_ORIGINAL_SOURCE_PIN_MISMATCH")
        if sha(originals.read("LICENSE")) != freeze["license_sha256"]:
            raise RuntimeError("GPL_LICENSE_PROVENANCE_CHANGED")
    source = check_source(freeze)
    evidence = {
        "schema": "zel.publicbot.cheap_costed_screen.actual.v1",
        "freeze_sha256": sha(freeze_raw),
        "source_census_sha256": sha((BASE / "SOURCE_CENSUS.json").read_bytes()),
        "public_commit": freeze["upstream_commit"],
        "timeframe_results": {},
        "results": {},
        "orders": 0,
        "new_API_calls_during_economics": 0,
        "not_native_freqtrade_engine": "INDICATOR_AND_EXECUTION_COMPATIBILITY_APPROXIMATION_NOT_FULL_ENGINE_PARITY",
        "data_origin_manifest": "HOLD_SOURCE_INTEGRITY",
        "not_unseen_OOS": True,
        "actual_historical_received_at": False,
        "funding_actual": False,
        "account_NAV_return": False,
    }
    trades = {}
    for name, cfg in freeze["strategies"].items():
        rows = []
        by_symbol = {}
        for symbol in freeze["symbols"]:
            interval = 5 if cfg["timeframe"] == "5m" else 60
            bars = aggregate(source[symbol], interval)
            got, detail = simulate(bars, symbol, name, cfg)
            rows.extend(got)
            by_symbol[symbol] = {
                "T": len(got),
                "signals": detail["signal_count_closed_bars"],
                "n_bars": detail["candles"],
                "unresolved": detail["unresolved_at_end"],
            }
        trades[name] = rows
        evidence["timeframe_results"][name] = by_symbol
        evidence["results"][name] = {
            "cost20": stats(rows, 20),
            "cost40": stats(rows, 40),
            "original_timeframe": cfg["timeframe"],
            "source_exact_SHA_pinned": True,
            "trade_samples": rows[:4],
            "close_reason_counts": dict(
                __import__("collections").Counter(x["reason"] for x in rows)
            ),
        }
        print(
            "ECON_SCREEN",
            name,
            "T",
            len(rows),
            "net20",
            round(evidence["results"][name]["cost20"]["Net_trade_bps_sum"], 2),
            "net40",
            round(evidence["results"][name]["cost40"]["Net_trade_bps_sum"], 2),
            "PF40",
            evidence["results"][name]["cost40"]["PF"],
            "WR40",
            evidence["results"][name]["cost40"]["WR_pct"],
            flush=True,
        )
    payload = (
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    (BASE / "RESULT.json").write_bytes(payload)
    trade_bytes = (
        json.dumps(trades, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    (BASE / "TRADES.json.gz").write_bytes(
        gzip.compress(trade_bytes, compresslevel=6, mtime=0)
    )
    print(
        "SOURCE_BOUND_ECON_RESULTS",
        sha(payload),
        "TRADES",
        sha((BASE / "TRADES.json.gz").read_bytes()),
        flush=True,
    )
    return evidence


if __name__ == "__main__":
    run()
