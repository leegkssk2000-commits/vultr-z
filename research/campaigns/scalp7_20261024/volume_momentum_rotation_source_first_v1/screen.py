"""Fixed daily volume-adjusted cross-sectional momentum, old used-DEV only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HOUR_MS = 3_600_000
DAY_HOURS = 24
ATRAIN = "TRAIN"
ALATER = "LATER"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1_000)


def load_source(root: Path, symbol: str) -> tuple[pd.DataFrame, dict[str, str]]:
    paths = sorted((root / symbol).glob("*.csv.gz"))
    if not paths:
        raise ValueError("SOURCE_FILES_MISSING:" + symbol)
    pins = {}
    parts = []
    for path in paths:
        raw = path.read_bytes()
        pins[path.name] = digest(raw)
        frame = pd.read_csv(path, float_precision="round_trip")
        if list(frame.columns) != [
            "timestamp_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            raise ValueError("SOURCE_SCHEMA:" + path.name)
        parts.append(frame)
    df = pd.concat(parts, ignore_index=True)
    ts = df.timestamp_ms.to_numpy(dtype=np.int64)
    if len(ts) < 240 or not np.all(np.diff(ts) == HOUR_MS):
        raise ValueError("MISSING_OR_UNORDERED_HOURS:" + symbol)
    if not np.all(ts % HOUR_MS == 0):
        raise ValueError("NOT_ALIGNED_UTC_HOUR")
    matrix = df[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.all(np.isfinite(matrix)) or np.any(matrix[:, :4] <= 0):
        raise ValueError("NONFINITE_OR_NONPOSITIVE")
    if np.any(matrix[:, 4] < 0):
        raise ValueError("NEGATIVE_VOLUME")
    if np.any(matrix[:, 1] < np.max(matrix[:, [0, 2, 3]], axis=1)) or np.any(
        matrix[:, 2] > np.min(matrix[:, [0, 1, 3]], axis=1)
    ):
        raise ValueError("INVALID_OHLC")
    return df, pins


def features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    close = df.close.to_numpy(dtype=float)
    vol = df.volume.to_numpy(dtype=float)
    prior_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce(
        [
            df.high.to_numpy() - df.low.to_numpy(),
            np.abs(df.high.to_numpy() - prior_close),
            np.abs(df.low.to_numpy() - prior_close),
        ]
    )
    # Explicit Wilder-style EWM, last bar i-1 only (never future i).
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    return close, vol, atr


def weights_at(
    decision_index: int, close: np.ndarray, volume: np.ndarray
) -> tuple[float, float]:
    i = decision_index
    if i < 240 or i < 8 * DAY_HOURS + 1:
        raise ValueError("WARMUP_MISSING")
    last24 = volume[i - 24 : i].sum()
    past24 = [volume[i - (j + 1) * 24 : i - j * 24].sum() for j in range(1, 8)]
    avg = float(np.mean(past24))
    if avg <= 0:
        return -math.inf, -math.inf
    ret = math.log(close[i - 1] / close[i - 25])
    if not np.isfinite(ret) or ret <= 0:
        return -math.inf, -math.inf
    volume_factor = min(3.0, last24 / avg)
    return ret * volume_factor, ret


def choose(
    i: int,
    frames: dict[str, pd.DataFrame],
    features_by_symbol: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    mode: str,
) -> tuple[str | None, dict[str, float]]:
    scores: dict[str, float] = {}
    for sym in sorted(frames):
        close, vol, _ = features_by_symbol[sym]
        volumesc, baseline = weights_at(i, close, vol)
        score = volumesc if mode == "VOLUME" else baseline
        if math.isfinite(score) and score > 0:
            scores[sym] = float(score)
    if not scores:
        return None, {}
    # Lexicographic tie-break in decreasing score
    return sorted(scores, key=lambda k: (-scores[k], k))[0], scores


def stop_fill(open_px: float, low_px: float, stop_px: float) -> float | None:
    if open_px <= stop_px:
        return open_px
    if low_px <= stop_px:
        return stop_px
    return None


def run_partition(
    frames: dict[str, pd.DataFrame],
    f_by: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    start: int,
    end: int,
    mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    base = frames[next(iter(frames))]
    stamp = base.timestamp_ms.to_numpy(dtype=np.int64)
    selected: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    censored: list[dict[str, Any]] = []
    # Daily decision always 00:00 UTC; prior 23:00 bar complete at this moment.
    for i in range(240, len(stamp) - 25):
        if stamp[i] < start or stamp[i] >= end or stamp[i] % (24 * HOUR_MS) != 0:
            continue
        sym, scores = choose(i, frames, f_by, mode)
        if sym is None:
            continue
        decision_ts = int(stamp[i])
        entry_i = i + 1
        exit_i = i + 25
        if stamp[entry_i] >= end:
            censored.append(
                {
                    "symbol": sym,
                    "decision_ts": decision_ts,
                    "reason": "NO_ELIGIBLE_ENTRY",
                }
            )
            continue
        arr = frames[sym]
        close, vol, atr = f_by[sym]
        entry = float(arr.open.iloc[entry_i])
        stop = entry - 2.0 * float(atr[i - 1])
        if stop <= 0 or not np.isfinite(stop):
            censored.append(
                {"symbol": sym, "decision_ts": decision_ts, "reason": "INVALID_STOP"}
            )
            continue
        selected.append(
            {
                "symbol": sym,
                "decision_ts": decision_ts,
                "entry_ts": int(stamp[entry_i]),
                "score": scores[sym],
            }
        )
        actual_exit_i = None
        actual_exit_px = None
        reason = None
        # Candle i+1 onward. At next calendar day i+25, only open exit, no overnight candle lookahead.
        for j in range(entry_i, exit_i):
            if j >= len(stamp) or stamp[j] >= end:
                break
            o = float(arr.open.iloc[j])
            lo = float(arr.low.iloc[j])
            fail = stop_fill(o, lo, stop)
            if fail is not None:
                actual_exit_i, actual_exit_px = j, float(fail)
                reason = "STOP_GAP" if o <= stop else "STOP_TOUCH"
                break
        if actual_exit_i is None:
            if exit_i >= len(stamp) or stamp[exit_i] >= end:
                censored.append(
                    {
                        "symbol": sym,
                        "decision_ts": decision_ts,
                        "entry_ts": int(stamp[entry_i]),
                        "reason": "PARTITION_END_UNRESOLVED",
                    }
                )
                continue
            actual_exit_i = exit_i
            actual_exit_px = float(arr.open.iloc[exit_i])
            reason = "NEXT_UTC_DAY_01_OPEN"
        assert actual_exit_px is not None and actual_exit_i is not None
        gross = 1e4 * (actual_exit_px / entry - 1)
        trades.append(
            {
                "model": mode,
                "symbol": sym,
                "decision_ts_ms": decision_ts,
                "entry_ts_ms": int(stamp[entry_i]),
                "exit_ts_ms": int(stamp[actual_exit_i]),
                "entry": entry,
                "exit": actual_exit_px,
                "stop": stop,
                "rank_score": scores[sym],
                "reason": reason,
                "gross_bps": gross,
                "net1x_bps": gross - 20,
                "net2x_bps": gross - 40,
            }
        )
    return trades, censored, selected


def metrics(trades: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda x: (x["exit_ts_ms"], x["symbol"]))
    days = (end - start) // (HOUR_MS * 24)
    x = [float(t["net2x_bps"]) for t in ordered]
    net1 = sum(float(t["net1x_bps"]) for t in ordered)
    net2 = sum(x)
    gains = sum(max(0, a) for a in x)
    losses = -sum(min(0, a) for a in x)
    eq = peak = dd = 0.0
    loss_streak = max_streak = 0
    for t in ordered:
        a = float(t["net2x_bps"])
        eq += a
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        loss_streak = loss_streak + 1 if a < 0 else 0
        max_streak = max(max_streak, loss_streak)
    winners = sorted([v for v in x if v > 0], reverse=True)
    return {
        "trades": len(x),
        "trades_per_day": len(x) / days,
        "net1x_trade_bps": net1,
        "net2x_trade_bps": net2,
        "net2x_profit_factor": gains / losses if losses else None,
        "win_rate_net2_pct": 100 * sum(y > 0 for y in x) / len(x) if x else None,
        "max_loss_streak_net2": max_streak,
        "realized_equal_notional_dd_net2_trade_bps": dd,
        "top2_positive_profit_share_net2": sum(winners[:2]) / gains if gains else None,
        "idle_days": days
        - len({int(t["entry_ts_ms"] // (24 * HOUR_MS)) for t in ordered}),
    }


def evaluate(root: Path, folder: Path) -> dict[str, Any]:
    spec_raw = (folder / "FREEZE.json").read_bytes()
    spec = json.loads(spec_raw)
    if (
        spec["candidate_id"]
        != "VOL_ADJUSTED_TSMOM_SINGLE_LONG_ROTATION_1H_DAILY_ZEL_V1"
    ):
        raise ValueError("FROZEN_CANDIDATE_DRIFT")
    if (
        digest((root.parent / "MANIFEST.json").read_bytes())
        != spec["source_manifest_sha256"]
    ):
        raise ValueError("SOURCE_MANIFEST_CHANGED")
    frames: dict[str, pd.DataFrame] = {}
    manifest: dict[str, Any] = {}
    for symbol in spec["symbols"]:
        df, pins = load_source(root, symbol)
        frames[symbol] = df
        manifest[symbol] = {
            "n_bars": len(df),
            "first_open": int(df.timestamp_ms.iloc[0]),
            "last_open": int(df.timestamp_ms.iloc[-1]),
            "file_sha256": pins,
        }
        print("SOURCE_VALIDATED", symbol, len(df), flush=True)
    stamps = [list(f.timestamp_ms) for f in frames.values()]
    if not all(x == stamps[0] for x in stamps[1:]):
        raise ValueError("CROSS_SYMBOL_HOURLY_CALENDAR_MISMATCH")
    f_by = {symbol: features(frames[symbol]) for symbol in frames}
    result: dict[str, Any] = {
        "frozen_rule_sha256": digest(spec_raw),
        "source_manifest_sha256": spec["source_manifest_sha256"],
        "raw_input_sha256": digest(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ),
        "source_files": manifest,
        "models": {},
        "restrictions": {
            "old_used_dev": True,
            "order_calls": 0,
            "market_api_calls": 0,
            "economic_full": 0,
            "no_live_promotion": True,
            "actual_funding": None,
            "historical_receive_times": None,
            "account_nav": None,
        },
    }
    for label, window in spec["sample_partitions_utc"].items():
        a, b = map(ms, window)
        for variant in ("PRICE_ONLY", "VOLUME"):
            trades, unresolved, decisions = run_partition(frames, f_by, a, b, variant)
            key = label + "_" + variant
            result["models"][key] = {
                "stats": metrics(trades, a, b),
                "trades": trades,
                "unresolved": unresolved,
                "decisions": decisions,
            }
            print(
                "MODEL_ECONOMICS",
                key,
                json.dumps(result["models"][key]["stats"]),
                flush=True,
            )
    payload = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    (folder / "RESULT.json").open("xb").write(payload)
    summary = {
        "rule_sha256": digest(spec_raw),
        "result_sha256": digest(payload),
        "source_manifest_sha256": spec["source_manifest_sha256"],
        "models": {k: v["stats"] for k, v in result["models"].items()},
        "trades_total": sum(len(v["trades"]) for v in result["models"].values()),
        "used_dev_only": True,
        "live_admission": False,
    }
    (folder / "SUMMARY.json").open("x").write(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    freeze = json.loads((args.folder / "FREEZE.json").read_text())
    out = evaluate(Path(freeze["original_market_source"]), args.folder)
    print("COMPLETE", json.dumps(out, sort_keys=True), flush=True)
