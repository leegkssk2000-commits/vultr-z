"""Causal, narrow 1-minute SOL/ETH liquidation-proxy cheap screen. Not original bot implementation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

H = 60_000
BAR_REQUIRED = ("timestamp_ms", "open", "high", "low", "close", "volume")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def ts(x: str) -> int:
    return int(datetime.fromisoformat(x).timestamp() * 1000)


def load_rows(
    root: Path, symbol: str, pin: dict[str, str]
) -> Iterator[dict[str, float | int]]:
    files = sorted((root / symbol).glob("*.csv.gz"))
    if not files:
        raise ValueError("SOURCE_FILES_MISSING")
    last = None
    for path in files:
        raw = path.read_bytes()
        pin[path.name] = sha(raw)
        with gzip.open(path, "rt") as inp:
            reader = csv.DictReader(inp)
            if tuple(reader.fieldnames or ()) != BAR_REQUIRED:
                raise ValueError("SOURCE_SCHEMA_CHANGED")
            for item in reader:
                stamp = int(item["timestamp_ms"])
                if stamp % H:
                    raise ValueError("SOURCE_ALIGNMENT_BAD")
                if last is not None and stamp - last != H:
                    raise ValueError(f"SOURCE_GAP_OR_DUP:{symbol}:{last}:{stamp}")
                last = stamp
                bar: dict[str, float | int] = {"timestamp_ms": stamp}
                for k in ("open", "high", "low", "close", "volume"):
                    v = float(item[k])
                    if not math.isfinite(v) or (v <= 0 if k != "volume" else v < 0):
                        raise ValueError(f"SOURCE_NONFINITE_{k}")
                    bar[k] = v
                if float(bar["high"]) < max(
                    float(bar["open"]), float(bar["low"]), float(bar["close"])
                ) or float(bar["low"]) > min(
                    float(bar["open"]), float(bar["high"]), float(bar["close"])
                ):
                    raise ValueError("SOURCE_OHLC_INCONSISTENT")
                yield bar


def signal(
    last: deque[dict[str, float | int]],
    threshold: float,
    volume_multiple: float,
    baseline: int,
) -> bool:
    if len(last) < baseline + 1:
        return False
    # Complete at end of CURRENT minute; compare close to close from 5 minutes prior.
    prev5 = float(last[-6]["close"])
    close = float(last[-1]["close"])
    raw = math.log(close / prev5)
    avg_vol = (
        sum(float(last[-1 - k]["volume"]) for k in range(1, baseline + 1)) / baseline
    )
    return bool(
        raw <= threshold
        and avg_vol > 0
        and float(last[-1]["volume"]) >= avg_vol * volume_multiple
    )


def model(
    rows: Iterator[dict[str, float | int]], spec: dict[str, Any], symbol: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, int]], int]:
    windows = {k: (ts(a), ts(b)) for k, (a, b) in spec["periods"].items()}
    res: dict[str, list[dict[str, Any]]] = {k: [] for k in windows}
    counts: dict[str, dict[str, int]] = {k: defaultdict(int) for k in windows}
    baseline = int(spec["volume_baseline_completed_previous_bars"])
    lookback: deque[dict[str, float | int]] = deque(maxlen=max(baseline + 1, 65))
    threshold = float(spec["price_velocity_5bar_log_return_max"])
    vm = float(spec["volume_multiple"])
    hold = int(spec["hold_minutes"])
    expected = None
    per: str | None = None
    position: dict[str, Any] | None = None
    next_signal_ts: int | None = None
    n = 0
    for x in rows:
        n += 1
        stamp = int(x["timestamp_ms"])
        if expected is not None and stamp != expected:
            raise ValueError("CONTINUITY_VIOLATION")
        expected = stamp + H
        group = next(
            (key for key, (start, end) in windows.items() if start <= stamp < end), None
        )
        if per != group:
            if position is not None:
                assert per is not None
                counts[per]["censored_at_period_end"] += 1
            if next_signal_ts is not None and per is not None:
                counts[per]["censored_at_period_end"] += 1
            position = None
            next_signal_ts = None
            per = group
        # Execute scheduled trade events at OPEN, using only earlier complete bars.
        if per is not None and next_signal_ts is not None:
            if stamp != next_signal_ts:
                raise ValueError("NEXT_OPEN_SIGNAL_CLOCK_BAD")
            if position is not None:
                raise ValueError("SLOT_ALREADY_OCCUPIED")
            position = {
                "signal_ts_ms": stamp,
                "entry_ts_ms": stamp,
                "entry": float(x["open"]),
                "exit_at_ts": stamp + hold * H,
            }
            counts[per]["entered"] += 1
            next_signal_ts = None
        if per is not None and position is not None and stamp == position["exit_at_ts"]:
            gross = 10_000.0 * (float(x["open"]) / float(position["entry"]) - 1)
            res[per].append(
                {
                    "symbol": symbol,
                    "signal_ts_ms": position["signal_ts_ms"],
                    "entry_ts_ms": position["entry_ts_ms"],
                    "exit_ts_ms": stamp,
                    "entry": position["entry"],
                    "exit": float(x["open"]),
                    "gross_bps": gross,
                    "net1_bps": gross - 20,
                    "net2_bps": gross - 40,
                    "reason": "THREE_MIN_TIMED_NEXT_OPEN",
                }
            )
            counts[per]["closed"] += 1
            position = None
        lookback.append(x)
        # The current bar's high/low/close/volume are only known AFTER this bar finishes.
        # Signal ready at t+1 minute, never at the same bar's earlier open.
        if per is not None and signal(lookback, threshold, vm, baseline):
            counts[per]["raw_signals"] += 1
            if position is None and next_signal_ts is None:
                if stamp + H < windows[per][1]:
                    next_signal_ts = stamp + H
                    counts[per]["admitted"] += 1
                else:
                    counts[per]["censored_boundary_entry"] += 1
            else:
                counts[per]["occupied"] += 1
    if per is not None and position is not None:
        counts[per]["source_end_unresolved"] += 1
    return res, counts, n


def metrics(r: list[dict[str, Any]], days: int) -> dict[str, Any]:
    r = sorted(r, key=lambda x: (x["exit_ts_ms"], x["symbol"], x["entry_ts_ms"]))
    pnl = [float(x["net2_bps"]) for x in r]
    gross = [float(x["gross_bps"]) for x in r]
    gains = sum(v for v in pnl if v > 0)
    losses = -sum(v for v in pnl if v < 0)
    equity = peak = dd = 0.0
    streak = most_losses = 0
    for v in pnl:
        equity += v
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if v < 0 else 0
        most_losses = max(most_losses, streak)
    winners = sorted((v for v in pnl if v > 0), reverse=True)
    return {
        "T": len(r),
        "T_per_day": len(r) / days,
        "Gross_sum_trade_bps": sum(gross),
        "Gross_per_T_bps": sum(gross) / len(r) if r else None,
        "cost1_net_sum_trade_bps": sum(float(x["net1_bps"]) for x in r),
        "cost2_net_sum_trade_bps": sum(pnl),
        "cost2_net_per_T_bps": sum(pnl) / len(r) if r else None,
        "PF2": gains / losses if losses else None,
        "WR2_pct": 100 * len(winners) / len(r) if r else None,
        "MaxLossStreak2": most_losses,
        "DD2_exit_order_trade_bps": dd,
        "top_two_profit_share": sum(winners[:2]) / gains if gains else None,
        "Net2_excluding_top2": sum(pnl) - sum(winners[:2]),
    }


def execute(folder: Path) -> dict[str, Any]:
    freeze = (folder / "FREEZE.json").read_bytes()
    s = json.loads(freeze)
    root = Path(s["source_root"])
    if sha((root.parent / "MANIFEST.json").read_bytes()) != s["source_manifest_sha256"]:
        raise ValueError("SOURCE_MANIFEST_SHA_CHANGED")
    if (
        s["strategy_id"] != "CURUPIRA_CASCADE_1M_SOL_ETH_LONG_PRICE_PROXY_V1"
        or s["symbols"] != ["SOL-USDT", "ETH-USDT"]
        or s["roundtrip_cost_bps"] != [20.0, 40.0]
        or s["hold_minutes"] != 3
        or s["price_velocity_5bar_log_return_max"] != -0.01
    ):
        raise ValueError("PRE_RESULT_FREEZE_CHANGED")
    reports: dict[str, list[dict[str, Any]]] = {k: [] for k in s["periods"]}
    counters: dict[str, dict[str, int]] = {k: defaultdict(int) for k in s["periods"]}
    pins: dict[str, dict[str, str]] = {}
    source_bars: dict[str, int] = {}
    for sym in s["symbols"]:
        hashes: dict[str, str] = {}
        per, counts, n = model(load_rows(root, sym, hashes), s, sym)
        source_bars[sym] = n
        pins[sym] = hashes
        for k in s["periods"]:
            reports[k].extend(per[k])
            for metric, v in counts[k].items():
                counters[k][metric] += v
        print("ACTUAL_VERIFIED_1MIN", sym, n, len(hashes), flush=True)
    economic = {}
    for k, (a, b) in s["periods"].items():
        days = round((ts(b) - ts(a)) / 86_400_000)
        economic[k] = metrics(reports[k], days)
        print("COSTED", k, json.dumps(economic[k], sort_keys=True), flush=True)
    result = {
        "schema": "zel.external_cascade_fade_priceproxy_used_dev_result_v1",
        "freeze_sha256": sha(freeze),
        "source_manifest_sha256": s["source_manifest_sha256"],
        "raw_source_gzip_sha256_by_day": pins,
        "bars_by_symbol": source_bars,
        "economic": economic,
        "census": {k: dict(v) for k, v in counters.items()},
        "trade_rows": reports,
        "cost_basis": "fixed roundtrip20/40bps per completed model slot; no live measured funding/fees or liquidation",
        "source_executable_reproduction": False,
        "published_velocity_threshold_missing": True,
        "original_author_live_metrics_do_not_transfer": True,
        "formal_g4_g5_shadow_credit": 0,
        "order_calls": 0,
        "economic_full": 0,
        "state": "USED_DEV_CHEAP_SCREEN_ONLY",
    }
    output = (
        json.dumps(
            result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        + "\n"
    ).encode()
    (folder / "RESULT.json").open("xb").write(output)
    summ = {
        "freeze_sha256": sha(freeze),
        "result_sha256": sha(output),
        "source_manifest_sha256": s["source_manifest_sha256"],
        "economic": economic,
        "census": {k: dict(v) for k, v in counters.items()},
        "decision": (
            "REJECT_ECONOMIC_EARLY"
            if any(v["cost2_net_sum_trade_bps"] <= 0 for v in economic.values())
            else "POSITIVE_DEV_ONLY_AWAIT_INDEPENDENT"
        ),
        "no_real_orders": True,
        "fresh_oos": False,
        "actual_account_nav": None,
    }
    (folder / "SUMMARY.json").open("xb").write(
        (json.dumps(summ, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    )
    return summ


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, required=True)
    args = ap.parse_args()
    out = execute(args.folder)
    print("DONE", out["decision"], out["result_sha256"], flush=True)
