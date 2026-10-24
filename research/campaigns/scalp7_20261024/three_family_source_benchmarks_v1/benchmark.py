"""Pre-frozen source-backed trend/momentum/countertrend trio. Historical used-DEV only."""

from __future__ import annotations
import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ONE_HOUR = 3600000
FOUR_HOURS = 4 * ONE_HOUR
DAY = 86400000
SHORT = (3, 5, 8, 10, 12, 15)
LONG = (30, 35, 40, 45, 50, 60)
TREND = "TREND_GUPPY_GMMA_LONG_4H_V1"
MOM = "MOMENTUM_MOP_TSMOM_LONG_4H_V1"
COUNTER = "COUNTERTREND_CONNORS_DOUBLE7_LONG_4H_V1"
FAMILIES = (TREND, MOM, COUNTER)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ms(timestamp: str) -> int:
    return int(datetime.fromisoformat(timestamp).timestamp() * 1000)


def load_exact_60m(root: Path, sym: str) -> tuple[pd.DataFrame, dict[str, str]]:
    files = sorted((root / sym).glob("*.csv.gz"))
    if not files:
        raise ValueError("RAW_60M_FILES_MISSING:" + sym)
    pins = {}
    partitions = []
    for file in files:
        raw = file.read_bytes()
        pins[file.name] = digest(raw)
        df = pd.read_csv(file, float_precision="round_trip")
        if list(df.columns) != [
            "timestamp_ms",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            raise ValueError("SOURCE_OHLC_SCHEMA_CHANGED")
        partitions.append(df)
    x = pd.concat(partitions, ignore_index=True)
    t = x.timestamp_ms.to_numpy(dtype=np.int64)
    if len(t) < 4 * 240 or not np.all(np.diff(t) == ONE_HOUR):
        raise ValueError("SOURCE_MISSING_DUPLICATED_REORDERED_HOUR")
    if not np.all(t % ONE_HOUR == 0):
        raise ValueError("SOURCE_HOUR_NOT_ALIGNED")
    matrix = x[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if (
        not np.isfinite(matrix).all()
        or np.any(matrix[:, :4] <= 0)
        or np.any(matrix[:, 4] < 0)
    ):
        raise ValueError("SOURCE_NAN_OR_NEGATIVE_PRICE_VOLUME")
    if np.any(matrix[:, 1] < np.max(matrix[:, [0, 2, 3]], axis=1)) or np.any(
        matrix[:, 2] > np.min(matrix[:, [0, 1, 3]], axis=1)
    ):
        raise ValueError("OHLC_INCONSISTENT")
    return x, pins


def to_actual_4h(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame["bucket"] = frame.timestamp_ms // FOUR_HOURS
    four = (
        frame.groupby("bucket", sort=True)
        .agg(
            open_ts_ms=("timestamp_ms", "min"),
            count=("timestamp_ms", "size"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index(drop=True)
    )
    four = four.loc[
        (four["count"] == 4) & (four["open_ts_ms"] % FOUR_HOURS == 0)
    ].copy()
    four["close_ts_ms"] = four["open_ts_ms"] + FOUR_HOURS
    four.reset_index(drop=True, inplace=True)
    stamps = four.open_ts_ms.to_numpy(dtype=np.int64)
    if len(stamps) < 400 or not np.all(np.diff(stamps) == FOUR_HOURS):
        raise ValueError("FOUR_HOUR_AGGREGATION_GAP")
    if np.any(four.high < four[["open", "low", "close"]].max(axis=1)) or np.any(
        four.low > four[["open", "high", "close"]].min(axis=1)
    ):
        raise ValueError("FOUR_HOUR_OHLC_BAD")
    return four


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    c = x.close.astype(float)
    for n in sorted(set(SHORT + LONG)):
        x["ema_" + str(n)] = c.ewm(span=n, adjust=False).mean()
    prior = c.shift(1)
    tr = pd.concat(
        [x.high - x.low, (x.high - prior).abs(), (x.low - prior).abs()], axis=1
    ).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    x["sma200"] = c.rolling(200).mean()
    x["close7_min"] = c.rolling(7).min()
    x["close7_max"] = c.rolling(7).max()
    mom = np.log(c / c.shift(42))
    r = np.log(c / prior)
    prior_vol = r.rolling(42).std(ddof=0)
    x["mom_score"] = mom / prior_vol.replace(0.0, np.nan)
    sgrp = ["ema_" + str(n) for n in SHORT]
    lgrp = ["ema_" + str(n) for n in LONG]
    x["gmma_short_min"] = x[sgrp].min(axis=1)
    x["gmma_long_max"] = x[lgrp].max(axis=1)
    return x


def signal_for(family: str, rows: list[dict[str, Any]], i: int) -> bool:
    if i < 240:
        return False
    x = rows[i]
    prev = rows[i - 1]
    if family == TREND:
        return bool(
            x["gmma_short_min"] > x["gmma_long_max"]
            and prev["gmma_short_min"] <= prev["gmma_long_max"]
            and x["ema_60"] > prev["ema_60"]
        )
    if family == MOM:
        now, last = float(x["mom_score"]), float(prev["mom_score"])
        return bool(math.isfinite(now) and math.isfinite(last) and now > 0 >= last)
    if family == COUNTER:
        sma, lo = float(x["sma200"]), float(x["close7_min"])
        return bool(
            math.isfinite(sma)
            and math.isfinite(lo)
            and x["close"] > sma
            and x["close"] <= lo
        )
    raise ValueError("UNKNOWN_FAMILY")


def take_exit_on_close(family: str, row: dict[str, Any]) -> bool:
    if family == TREND:
        return bool(float(row["ema_15"]) < float(row["ema_30"]))
    if family == MOM:
        v = float(row["mom_score"])
        return bool(math.isfinite(v) and v < 0)
    if family == COUNTER:
        return bool(float(row["close"]) >= float(row["close7_max"]))
    raise ValueError("UNKNOWN_FAMILY")


def safety(family: str) -> tuple[float, int]:
    if family == TREND:
        return 2.5, 48
    if family == MOM:
        return 2.0, 24
    if family == COUNTER:
        return 3.0, 24
    raise ValueError("UNKNOWN_FAMILY")


def exit_at_open(
    open_: float, stop: float, scheduled_exit: bool
) -> tuple[float | None, str | None]:
    if open_ <= stop:
        return open_, "STOP_GAP"
    if scheduled_exit:
        return open_, "SCHEDULED_NEXT_OPEN"
    return None, None


def evaluate_symbol(
    rows: list[dict[str, Any]], sym: str, family: str, start: int, end: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    out: list[dict[str, Any]] = []
    censored: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    atr_mult, max_hold = safety(family)
    busy_until = -1
    for i in range(240, len(rows) - 1):
        stamp = int(rows[i]["close_ts_ms"])
        if not (start <= stamp < end):
            continue
        if not signal_for(family, rows, i):
            continue
        counts["frozen_signals"] += 1
        if i <= busy_until:
            counts["blocked_same_symbol_occupancy"] += 1
            continue
        entry_index = i + 1
        if int(rows[entry_index]["open_ts_ms"]) >= end:
            censored.append(
                {
                    "symbol": sym,
                    "signal_ts_ms": stamp,
                    "reason": "ENTRY_BEYOND_PARTITION",
                }
            )
            continue
        entry = float(rows[entry_index]["open"])
        atr = float(rows[i]["atr14"])
        stop = entry - atr * atr_mult
        if atr <= 0 or stop <= 0 or stop >= entry or not math.isfinite(stop):
            counts["invalid_initial_risk"] += 1
            continue
        pending = False
        terminal: tuple[int, float, str] | None = None
        for k in range(entry_index, min(len(rows), entry_index + max_hold + 1)):
            bar = rows[k]
            if int(bar["open_ts_ms"]) >= end:
                break
            op, lo = float(bar["open"]), float(bar["low"])
            opened, reason = exit_at_open(op, stop, pending)
            if opened is not None:
                terminal = k, opened, str(reason)
                break
            if lo <= stop:
                terminal = k, stop, "STOP_FIRST"
                break
            if k - entry_index >= max_hold - 1:
                pending = True
            elif take_exit_on_close(family, bar):
                pending = True
        if terminal is None:
            censored.append(
                {
                    "symbol": sym,
                    "signal_ts_ms": stamp,
                    "entry_ts_ms": int(rows[entry_index]["open_ts_ms"]),
                    "reason": "UNRESOLVED_AT_PARTITION_OR_SOURCE_END",
                }
            )
            busy_until = len(rows)  # don't generate overlapping fictional trades
            continue
        exit_index, exit_price, reason = terminal
        gross = 10000 * (exit_price / entry - 1)
        record = {
            "family": family,
            "symbol": sym,
            "signal_ts_ms": stamp,
            "entry_ts_ms": int(rows[entry_index]["open_ts_ms"]),
            "exit_ts_ms": int(rows[exit_index]["open_ts_ms"]),
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop,
            "exit_reason": reason,
            "gross_bps": gross,
            "net1x_bps": gross - 20,
            "net2x_bps": gross - 40,
            "entry_atr14": atr,
            "bars_occupied": exit_index - entry_index + 1,
        }
        out.append(record)
        busy_until = exit_index
    return out, censored, dict(counts)


def metrics(rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    rows = sorted(rows, key=lambda x: (x["exit_ts_ms"], x["symbol"], x["entry_ts_ms"]))
    pnl1 = [float(x["net1x_bps"]) for x in rows]
    pnl2 = [float(x["net2x_bps"]) for x in rows]
    gains = sum(x for x in pnl2 if x > 0)
    losses = -sum(x for x in pnl2 if x < 0)
    by_exit: dict[int, float] = defaultdict(float)
    for r in rows:
        by_exit[int(r["exit_ts_ms"])] += float(r["net2x_bps"])
    eq = peak = dd = 0.0
    for _, pnl in sorted(by_exit.items()):
        eq += pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    streak = longest = 0
    for v in pnl2:
        streak = streak + 1 if v < 0 else 0
        longest = max(longest, streak)
    best = sorted((z for z in pnl2 if z > 0), reverse=True)
    return {
        "T": len(rows),
        "T_per_day": len(rows) / ((end - start) / DAY),
        "unique_entry_epochs": len({r["entry_ts_ms"] for r in rows}),
        "Net1x_sum_trade_bps": sum(pnl1),
        "Net2x_sum_trade_bps": sum(pnl2),
        "Net2x_bps_per_trade": sum(pnl2) / len(rows) if rows else None,
        "PF2x": gains / losses if losses else None,
        "WR2x_pct": 100 * len(best) / len(rows) if rows else None,
        "MaxLossStreak2x": longest,
        "DD2x_exit_cohort_trade_bps": dd,
        "Top2WinnerShareOfPositiveProfit": sum(best[:2]) / gains if gains else None,
        "Net2x_excluding_top2_winners": sum(pnl2) - sum(best[:2]),
        "worst_trade_net2x": min(pnl2) if pnl2 else None,
    }


def overlap_by_signal(
    trades: dict[str, dict[str, list[dict[str, Any]]]]
) -> dict[str, dict[str, int]]:
    pairs: dict[str, dict[str, int]] = {}
    for partition in sorted(next(iter(trades.values()))):
        a, b, c = [trades[f][partition] for f in FAMILIES]
        for one, two, name in [
            (a, b, "trend_momentum"),
            (a, c, "trend_countertrend"),
            (b, c, "momentum_countertrend"),
        ]:
            overlap = [
                (x, y)
                for x in one
                for y in two
                if x["entry_ts_ms"] < y["exit_ts_ms"]
                and y["entry_ts_ms"] < x["exit_ts_ms"]
            ]
            pairs[partition + "_" + name] = {
                "overlap_pairs": len(overlap),
                "same_symbol_overlap_pairs": sum(
                    x["symbol"] == y["symbol"] for x, y in overlap
                ),
                "matching_same_signal_key": sum(
                    (x["symbol"], x["signal_ts_ms"]) == (y["symbol"], y["signal_ts_ms"])
                    for x, y in overlap
                ),
            }
    return pairs


def run(dir: Path) -> dict[str, Any]:
    original = (dir / "FREEZE.json").read_bytes()
    freeze = json.loads(original)
    root = Path(freeze["model_source_root"])
    if (
        digest((root.parent / "MANIFEST.json").read_bytes())
        != freeze["manifest_sha256"]
    ):
        raise ValueError("FROZEN_SOURCE_MANIFEST_HASH_DRIFT")
    if tuple(x["id"] for x in freeze["families"]) != FAMILIES or freeze[
        "cost_roundtrip_bps"
    ] != [20, 40]:
        raise ValueError("FROZEN_MODEL_IDS_COST_CHANGED")
    sources: dict[str, Any] = {}
    all_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        fam: {period: [] for period in freeze["intervals"]} for fam in FAMILIES
    }
    censored: dict[str, dict[str, list[dict[str, Any]]]] = {
        fam: {period: [] for period in freeze["intervals"]} for fam in FAMILIES
    }
    counting: dict[str, dict[str, dict[str, int]]] = {
        fam: {period: {} for period in freeze["intervals"]} for fam in FAMILIES
    }
    for sym in freeze["symbols"]:
        raw, file_sha = load_exact_60m(root, sym)
        f4 = to_actual_4h(raw)
        bar = enrich(f4)
        records = bar.to_dict("records")
        sources[sym] = {
            "raw_60m_n": len(raw),
            "four_hour_n": len(f4),
            "first_4h_ms": int(f4.open_ts_ms.iloc[0]),
            "last_4h_ms": int(f4.open_ts_ms.iloc[-1]),
            "file_sha256": file_sha,
        }
        for family in FAMILIES:
            for period, (a, b) in freeze["intervals"].items():
                out, uncompleted, cnt = evaluate_symbol(
                    records, sym, family, ms(a), ms(b)
                )
                all_rows[family][period].extend(out)
                censored[family][period].extend(uncompleted)
                count = counting[family][period]
                for key, value in cnt.items():
                    count[key] = count.get(key, 0) + value
        print("SOURCE_4H_COMPLETE", sym, "raw", len(raw), "4h", len(f4), flush=True)
    econ: dict[str, dict[str, dict[str, Any]]] = {}
    for family in FAMILIES:
        econ[family] = {}
        for period, (a, b) in freeze["intervals"].items():
            v = metrics(all_rows[family][period], ms(a), ms(b))
            econ[family][period] = v
            print(
                "COSTED_BENCHMARK",
                family,
                period,
                json.dumps(v, sort_keys=True),
                flush=True,
            )
    result: dict[str, Any] = {
        "schema": "zel.three_distinct_strategies_costed_useddev.v1",
        "frozen_sha256": digest(original),
        "original_source_manifest_sha256": freeze["manifest_sha256"],
        "sources": sources,
        "economic": econ,
        "model_trade_rows": all_rows,
        "censored": censored,
        "counts": counting,
        "overlap": overlap_by_signal(all_rows),
        "source_original_and_zEL_mapping": freeze["families"],
        "auth": {
            "new_WORK": 0,
            "real_order": 0,
            "economic_FULL": 0,
            "market_api": 0,
            "source_writer": 0,
            "fresh_OOS": False,
            "observed_history_funding": False,
            "NAV_proven": False,
            "selection_authority": False,
            "G5_authority": False,
        },
    }
    content = (
        json.dumps(
            result, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()
    with (dir / "RESULT.json").open("xb") as f:
        f.write(content)
    summary = {
        "frozen_sha256": digest(original),
        "result_sha256": digest(content),
        "source_manifest_sha256": freeze["manifest_sha256"],
        "economic": econ,
        "overlap": result["overlap"],
        "unresolved_count": {
            f: {p: len(v) for p, v in a.items()} for f, a in censored.items()
        },
        "used_dev_only": True,
        "automatic_promotion": False,
        "action": "hold",
    }
    (dir / "SUMMARY.json").write_text(
        json.dumps(
            summary, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    )
    return summary


if __name__ == "__main__":
    pa = argparse.ArgumentParser()
    pa.add_argument("--dir", required=True, type=Path)
    args = pa.parse_args()
    output = run(args.dir)
    print("THREE_FAMILY_COMPLETE_SHA", output["result_sha256"], flush=True)
