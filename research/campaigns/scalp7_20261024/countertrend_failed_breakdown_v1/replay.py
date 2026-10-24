"""One native-source false-break long-only price hypothesis, historical used DEV only."""

from __future__ import annotations
import argparse
import hashlib
import importlib.util
import importlib.machinery
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

H = 1800000


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ms(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp() * 1000)


def signal(
    prev20_low: float, open_: float, high: float, low: float, close: float
) -> bool:
    return bool(
        np.isfinite(prev20_low)
        and low < prev20_low
        and close > prev20_low
        and close > open_
        and high > low
        and (high - close) / (high - low) <= 0.25
    )


def fills(
    open_: float, high: float, low: float, stop: float, target: float
) -> tuple[float | None, str | None]:
    if open_ <= stop:
        return open_, "STOP_GAP"
    if low <= stop:
        return stop, "STOP_FIRST"
    if open_ >= target:
        return target, "TARGET_GAP_CAPPED"
    if high >= target:
        return target, "TARGET"
    return None, None


def stats(rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    records = sorted(
        rows, key=lambda v: (v["exit_ts_ms"], v["symbol"], v["signal_ts_ms"])
    )
    a = [x["gross_bps"] - 20 for x in records]
    b = [x["gross_bps"] - 40 for x in records]
    win = sum(x for x in b if x > 0)
    loss = -sum(x for x in b if x < 0)
    eq = peak = dd = 0.0
    by_exit: dict[int, float] = defaultdict(float)
    for x, y in zip(records, b):
        by_exit[x["exit_ts_ms"]] += y
    for t in sorted(by_exit):
        eq += by_exit[t]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    maxloss = consecutive = 0
    for y in b:
        consecutive = consecutive + 1 if y < 0 else 0
        maxloss = max(maxloss, consecutive)
    wins = sorted((x for x in b if x > 0), reverse=True)
    return {
        "T": len(b),
        "T_per_day": len(b) / ((end - start) / 86400000),
        "Net1_bps": sum(a),
        "Net2_bps": sum(b),
        "PF2": win / loss if loss else None,
        "WR2_pct": 100 * len(wins) / len(b) if b else None,
        "MaxLossStreak2": maxloss,
        "DD2_equal_notional_trade_bps": dd,
        "top2_profit_share2": sum(wins[:2]) / win if win else None,
        "unique_entry_epochs": len({x["entry_ts_ms"] for x in records}),
    }


def run(root: Path, p: Path) -> dict[str, Any]:
    raw = (p / "FREEZE.json").read_bytes()
    f = json.loads(raw)
    if f["candidate"] != "COUNTERTREND_FAILED_20BAR_LOW_RECLAIM_30M_LONG_V1":
        raise ValueError("RULE_CHANGED")
    if (
        digest(Path(root.parent / "MANIFEST.json").read_bytes())
        != f["root_manifest_sha256"]
    ):
        raise ValueError("SOURCE_MANIFEST_CHANGED")
    loader = Path(f["loader_path"])
    if digest(loader.read_bytes()) != f["loader_sha256"]:
        preserved = loader.with_name("RUN_ORIGINAL_FROZEN.txt")
        if digest(preserved.read_bytes()) != f["loader_sha256"]:
            raise ValueError("LOADER_SOURCE_DRIFT")
        loader = preserved
    native_loader = importlib.machinery.SourceFileLoader(
        "squeeze_loader_pinned", str(loader)
    )
    mod = importlib.util.spec_from_loader("squeeze_loader_pinned", native_loader)
    if mod is None or mod.loader is None:
        raise ValueError("PINNED_LOADER_IMPORT")
    obj = importlib.util.module_from_spec(mod)
    mod.loader.exec_module(obj)
    allrows: dict[str, list[dict[str, Any]]] = {k: [] for k in f["dates"]}
    allcens: dict[str, list[dict[str, Any]]] = {k: [] for k in f["dates"]}
    hashes = {}
    for sym in (
        "BTC-USDT",
        "DOGE-USDT",
        "ETH-USDT",
        "LINK-USDT",
        "SOL-USDT",
        "XRP-USDT",
    ):
        x, pins = obj.source(root, sym)
        hashes[sym] = {"bars": len(x), "raw_file_sha256": pins}
        pc = x.close.shift(1)
        tr = pd.concat(
            [x.high - x.low, (x.high - pc).abs(), (x.low - pc).abs()], axis=1
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
        lows = x.low.shift(1).rolling(20).min()
        arr = x.to_dict("records")
        a = atr.to_numpy(float)
        prior = lows.to_numpy(float)
        for label, (st, en) in f["dates"].items():
            start, end = ms(st), ms(en)
            occupied = -1
            for i in range(240, len(arr) - 13):
                row = arr[i]
                ts = int(row["close_ts_ms"])
                if ts < start or ts >= end or i <= occupied:
                    continue
                if not signal(
                    prior[i],
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                ):
                    continue
                j = i + 1
                if j >= len(arr) or int(arr[j]["open_ts_ms"]) >= end:
                    allcens[label].append(
                        {"symbol": sym, "signal_ts_ms": ts, "state": "NO_ENTRY"}
                    )
                    continue
                entry = float(arr[j]["open"])
                stop = float(row["low"]) - 0.2 * a[i]
                risk = entry - stop
                if stop <= 0 or risk <= 0:
                    continue
                target = entry + 2.5 * risk
                terminal = None
                for k in range(j, min(len(arr), j + 12)):
                    if int(arr[k]["open_ts_ms"]) >= end:
                        break
                    y, reason = fills(
                        float(arr[k]["open"]),
                        float(arr[k]["high"]),
                        float(arr[k]["low"]),
                        stop,
                        target,
                    )
                    if y is not None:
                        terminal = (k, y, reason)
                        break
                if terminal is None:
                    deadline = j + 12
                    if deadline >= len(arr) or int(arr[deadline]["open_ts_ms"]) >= end:
                        allcens[label].append(
                            {
                                "symbol": sym,
                                "signal_ts_ms": ts,
                                "entry_ts_ms": int(arr[j]["open_ts_ms"]),
                                "state": "OPEN_AT_END",
                            }
                        )
                        occupied = len(arr) - 1
                        break
                    terminal = (
                        deadline,
                        float(arr[deadline]["open"]),
                        "TIME_NEXT_OPEN",
                    )
                k, y, reason = terminal
                allrows[label].append(
                    {
                        "symbol": sym,
                        "signal_ts_ms": ts,
                        "entry_ts_ms": int(arr[j]["open_ts_ms"]),
                        "exit_ts_ms": int(arr[k]["open_ts_ms"]),
                        "entry_px": entry,
                        "exit_px": y,
                        "stop": stop,
                        "target": target,
                        "gross_bps": 10000 * (y / entry - 1),
                        "reason": reason,
                    }
                )
                occupied = k
        print("MODEL_SOURCE_DONE", sym, len(x), flush=True)
    scores = {
        k: stats(v, ms(f["dates"][k][0]), ms(f["dates"][k][1]))
        for k, v in allrows.items()
    }
    result = {
        "source_input_manifest_sha256": f["root_manifest_sha256"],
        "freeze_sha256": digest(raw),
        "input_source_pins": hashes,
        "scores": scores,
        "rows": allrows,
        "censored": allcens,
        "scope": "USED_HISTORICAL_MODEL_NOT_FRESH_OOS",
        "no_real_fill_costs": True,
        "no_funding": True,
        "orders": 0,
        "economic_FULL": 0,
        "production_authority": False,
    }
    encoded = (
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        + "\n"
    ).encode()
    (p / "RESULT.json").open("xb").write(encoded)
    summ = {
        "source": "old used 30m 6 symbols",
        "freeze_sha": digest(raw),
        "result_sha": digest(encoded),
        "economics": scores,
        "count_censored": {k: len(v) for k, v in allcens.items()},
        "decision": "REVIEW_OR_REJECT_ONLY",
        "orders": 0,
    }
    (p / "SUMMARY.json").write_text(json.dumps(summ, sort_keys=True, indent=2) + "\n")
    print("RESULT", json.dumps(summ), flush=True)
    return summ


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    run(
        Path(json.loads((args.out / "FREEZE.json").read_text())["source_root"]),
        args.out,
    )
