from __future__ import annotations

import argparse
import hashlib
import json
import math
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
ENDPOINT = "/openApi/swap/v2/quote/fundingRate"
DATASET_SHA = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
WARMUP_START_MS = 1770422400000
W1_START_MS = 1771027200000
W1_END_MS = 1774828800000
SYMBOLS = ("BTC-USDT", "ETH-USDT")
HOLD_HOURS = 8
ROUNDTRIP_COST_BPS = 8.0
MIN_EVENTS = 20
BOOTSTRAP_REPS = 4000
SEED = 42


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_json(params: Mapping[str, Any]) -> tuple[Any, str, float]:
    ctx = ssl.create_default_context()
    errors: list[str] = []
    for base in BASES:
        try:
            url = base + ENDPOINT + "?" + urllib.parse.urlencode(dict(params))
            req = urllib.request.Request(url, headers={"User-Agent": "ZEL-Edge-Factory-V2-readonly/1.0"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
            latency_ms = (time.perf_counter() - t0) * 1000.0
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("code") not in (None, 0):
                raise RuntimeError(f"code={obj.get('code')} msg={obj.get('msg')}")
            return (obj.get("data", obj) if isinstance(obj, dict) else obj), base, latency_ms
        except Exception as exc:
            errors.append(f"{base}:{type(exc).__name__}:{str(exc)[:180]}")
    raise RuntimeError(" | ".join(errors))


def normalize_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = []
        for key in ("data", "list", "rows", "fundingRates", "result"):
            if isinstance(data.get(key), list):
                candidates = data[key]
                break
        if not candidates:
            candidates = [data]
    else:
        candidates = []
    output: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        ts = None
        for key in ("fundingTime", "funding_time", "timestamp", "time", "ts"):
            if raw.get(key) is None:
                continue
            try:
                ts = int(float(raw[key]))
                if ts < 10_000_000_000:
                    ts *= 1000
            except Exception:
                ts = None
            break
        rate = None
        for key in ("fundingRate", "funding_rate", "rate"):
            if raw.get(key) is None:
                continue
            try:
                rate = float(raw[key])
            except Exception:
                rate = None
            break
        if ts is not None and rate is not None and math.isfinite(rate):
            output.append({"timestamp_ms": ts, "funding_rate": rate})
    dedup = {int(row["timestamp_ms"]): row for row in output}
    return [dedup[key] for key in sorted(dedup)]


def fetch_funding(symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, base, latency_ms = get_json({
        "symbol": symbol,
        "startTime": WARMUP_START_MS,
        "endTime": W1_END_MS,
        "limit": 1000,
    })
    rows = normalize_rows(data)
    in_requested = [row for row in rows if WARMUP_START_MS <= int(row["timestamp_ms"]) <= W1_END_MS]
    if not in_requested:
        return [], {
            "symbol": symbol,
            "base": base,
            "latency_ms": latency_ms,
            "row_count": 0,
            "state": "HOLD_NO_FUNDING_ROWS",
        }
    first = int(in_requested[0]["timestamp_ms"])
    last = int(in_requested[-1]["timestamp_ms"])
    coverage_ok = first <= WARMUP_START_MS + 8 * 3600_000 and last >= W1_END_MS - 8 * 3600_000
    return in_requested, {
        "symbol": symbol,
        "base": base,
        "latency_ms": latency_ms,
        "row_count": len(in_requested),
        "min_timestamp_ms": first,
        "max_timestamp_ms": last,
        "coverage_days": (last - first) / 86_400_000.0 if len(in_requested) >= 2 else 0.0,
        "coverage_ok": coverage_ok,
        "payload_sha256": stable_sha(in_requested),
        "raw_market_values_emitted": False,
        "state": "PASS_FUNDING_HISTORY" if coverage_ok else "HOLD_FUNDING_COVERAGE_GAP",
    }


def load_market(root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("state") != "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED":
        raise RuntimeError("DATASET_STATE")
    if manifest.get("dataset_sha256") != DATASET_SHA:
        raise RuntimeError("DATASET_SHA")
    post = {
        str(row.get("symbol")): row
        for row in manifest.get("results") or []
        if isinstance(row, Mapping) and row.get("segment_id") == "POST_GAP"
    }
    frames: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        row = post[symbol]
        path = root / "data" / str(row["file"])
        if file_sha(path) != str(row["file_sha256"]):
            raise RuntimeError(f"MARKET_SHA:{symbol}")
        frame = pd.read_csv(path, usecols=["timestamp_ms", "open", "high", "low", "close", "volume"])
        frame = frame[(frame["timestamp_ms"] >= W1_START_MS) & (frame["timestamp_ms"] < W1_END_MS)].copy()
        expected = (W1_END_MS - W1_START_MS) // 60_000
        if len(frame) != expected:
            raise RuntimeError(f"W1_ROWS:{symbol}:{len(frame)}")
        ts = frame["timestamp_ms"].astype("int64")
        if not bool((ts.diff().dropna() == 60_000).all()):
            raise RuntimeError(f"W1_GAP:{symbol}")
        frame["ts"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        h1 = frame.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float).resample(
            "1h", label="left", closed="left"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        frames[symbol] = h1
    return frames, {
        "dataset_sha256": manifest["dataset_sha256"],
        "w1_start_ms": W1_START_MS,
        "w1_end_exclusive_ms": W1_END_MS,
        "symbols": list(SYMBOLS),
    }


def event_return(frame: pd.DataFrame, funding_ms: int) -> tuple[pd.Timestamp, float] | None:
    ts = pd.to_datetime(funding_ms, unit="ms", utc=True)
    pos = int(frame.index.searchsorted(ts, side="right"))
    exit_pos = pos + HOLD_HOURS
    if pos >= len(frame) or exit_pos >= len(frame):
        return None
    entry_ts = frame.index[pos]
    if entry_ts >= pd.to_datetime(W1_END_MS, unit="ms", utc=True):
        return None
    entry = float(frame.iloc[pos]["open"])
    exit_ = float(frame.iloc[exit_pos]["open"])
    if entry <= 0.0 or exit_ <= 0.0:
        return None
    return entry_ts, exit_ / entry - 1.0


def bootstrap(net_bps: pd.Series) -> tuple[float, float, int]:
    if net_bps.empty:
        return float("nan"), float("nan"), 0
    df = pd.DataFrame({"net_bps": net_bps}).dropna()
    df["day"] = df.index.date
    daily = df.groupby("day")["net_bps"].mean().to_numpy(float)
    if len(daily) < 5:
        return float("nan"), float("nan"), int(len(daily))
    rng = np.random.default_rng(SEED)
    means = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        means[i] = rng.choice(daily, size=len(daily), replace=True).mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi), int(len(daily))


def summarize(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {"state": "REJECT_W1_NO_EVENTS", "event_count": 0}
    work = events.copy()
    work["net_bps"] = work["raw_return"] * 10_000.0 - ROUNDTRIP_COST_BPS
    lo, hi, days = bootstrap(work["net_bps"])
    by_symbol = work.groupby("symbol")["net_bps"].mean().sort_index()
    count = int(len(work))
    mean_net = float(work["net_bps"].mean())
    positive = int((by_symbol > 0.0).sum())
    if count < MIN_EVENTS:
        state = "HOLD_W1_LOW_SAMPLE"
    elif mean_net <= 0.0 or positive < 2:
        state = "REJECT_W1_NONPOSITIVE_OR_NARROW"
    elif math.isfinite(lo) and lo > 0.0:
        state = "PASS_W1_FUNDING_EFFECT_DISCOVERY"
    else:
        state = "HOLD_W1_POSITIVE_NOT_ROBUST"
    return {
        "state": state,
        "event_count": count,
        "independent_day_count": days,
        "mean_raw_bps": float(work["raw_return"].mean() * 10_000.0),
        "mean_net_bps_after_cost_floor": mean_net,
        "net_hit_rate_pct": float((work["net_bps"] > 0.0).mean() * 100.0),
        "daily_block_bootstrap95_net_bps": [lo, hi],
        "positive_symbol_count": positive,
        "symbol_mean_net_bps": {str(k): float(v) for k, v in by_symbol.items()},
    }


def make_events(
    funding: Mapping[str, list[dict[str, Any]]],
    frames: Mapping[str, pd.DataFrame],
    family: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        hist = funding[symbol]
        rates = pd.Series([float(row["funding_rate"]) for row in hist], dtype=float)
        q20 = rates.shift(1).rolling(20, min_periods=20).quantile(0.20)
        for idx, row in enumerate(hist):
            ts_ms = int(row["timestamp_ms"])
            if not (W1_START_MS <= ts_ms < W1_END_MS):
                continue
            rate = float(row["funding_rate"])
            if family == "NEGATIVE_FUNDING_LONG":
                eligible = rate < 0.0
            elif family == "EXTREME_NEGATIVE_FUNDING_LONG":
                threshold = float(q20.iloc[idx]) if idx < len(q20) and math.isfinite(float(q20.iloc[idx])) else float("nan")
                eligible = rate < 0.0 and math.isfinite(threshold) and rate <= threshold
            else:
                raise ValueError(family)
            if not eligible:
                continue
            outcome = event_return(frames[symbol], ts_ms)
            if outcome is None:
                continue
            entry_ts, raw_return = outcome
            rows.append({
                "ts": entry_ts,
                "symbol": symbol,
                "funding_timestamp_ms": ts_ms,
                "raw_return": raw_return,
            })
    if not rows:
        return pd.DataFrame(columns=["symbol", "funding_timestamp_ms", "raw_return"])
    return pd.DataFrame(rows).set_index("ts").sort_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    frames, market_meta = load_market(ns.dataset_root.resolve())
    funding: dict[str, list[dict[str, Any]]] = {}
    source_meta: dict[str, Any] = {}
    blockers: list[str] = []
    for symbol in SYMBOLS:
        rows, meta = fetch_funding(symbol)
        funding[symbol] = rows
        source_meta[symbol] = meta
        if meta.get("coverage_ok") is not True:
            blockers.append(f"FUNDING_COVERAGE_GAP:{symbol}")

    if blockers:
        receipt: dict[str, Any] = {
            "schema_version": "zel.edge_factory_v2.funding_w1.v1",
            "state": "HOLD_FUNDING_W1_SOURCE_GAP",
            "blockers": blockers,
            "market": market_meta,
            "funding_source": source_meta,
            "economic_replay_performed": False,
            "ai_used_for_discovery": False,
            "w2_w3_metrics_inspected": False,
            "survivor_declared": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
    else:
        results = {
            family: summarize(make_events(funding, frames, family))
            for family in ("NEGATIVE_FUNDING_LONG", "EXTREME_NEGATIVE_FUNDING_LONG")
        }
        passes = [family for family, row in results.items() if row.get("state") == "PASS_W1_FUNDING_EFFECT_DISCOVERY"]
        weak = [family for family, row in results.items() if row.get("state") == "HOLD_W1_POSITIVE_NOT_ROBUST"]
        candidates = (passes + [x for x in weak if x not in passes])[:1]
        state = "PASS_FUNDING_W1_WITH_CANDIDATE" if candidates else "HOLD_FUNDING_W1_NO_CANDIDATE"
        receipt = {
            "schema_version": "zel.edge_factory_v2.funding_w1.v1",
            "state": state,
            "blockers": [],
            "market": market_meta,
            "funding_source": source_meta,
            "method": {
                "endpoint": ENDPOINT,
                "families": ["NEGATIVE_FUNDING_LONG", "EXTREME_NEGATIVE_FUNDING_LONG"],
                "entry": "FIRST_1H_OPEN_STRICTLY_AFTER_FUNDING_TIMESTAMP",
                "holding_hours": HOLD_HOURS,
                "same_settlement_funding_income_counted": False,
                "roundtrip_cost_floor_bps": ROUNDTRIP_COST_BPS,
                "parameter_search": 0,
            },
            "results": results,
            "w2_candidate_count": len(candidates),
            "w2_candidates": candidates,
            "economic_replay_performed": True,
            "next": "FREEZE_FUNDING_RULE_AND_RUN_W2_ONLY" if candidates else "ROUTE_NEXT_ECONOMIC_SOURCE",
            "ai_used_for_discovery": False,
            "w2_w3_metrics_inspected": False,
            "survivor_declared": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
    receipt["receipt_sha256"] = stable_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({
        "state": receipt["state"],
        "blockers": receipt.get("blockers", []),
        "results": receipt.get("results", {}),
        "w2_candidates": receipt.get("w2_candidates", []),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
