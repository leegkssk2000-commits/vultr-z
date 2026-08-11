#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

SCHEMA = "zel.production_bootstrap_admission_evidence.v1"
STRATEGY_ID = "squeeze_break"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
BINGX_SYMBOL = {
    "BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT", "SOLUSDT": "SOL-USDT",
    "XRPUSDT": "XRP-USDT", "LINKUSDT": "LINK-USDT",
}
BASE_URLS = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
KLINE_ENDPOINT = "/openApi/swap/v3/quote/klines"
FUNDING_ENDPOINT = "/openApi/swap/v2/quote/fundingRate"
INTERVAL = "1m"
MINUTE_MS = 60_000
DAY_MS = 86_400_000
SOURCE_END_MS = 1_782_549_000_000  # frozen Exact25 first-window boundary: 2026-06-27 08:30 UTC
SOURCE_DAYS = 300  # derived from Exact25 2 trades / 30d and engine low-sample exit at 20 trades: 10x horizon
SOURCE_START_MS = SOURCE_END_MS - SOURCE_DAYS * DAY_MS
WINDOW_DAYS = 100
BOUNDARIES = (
    SOURCE_START_MS,
    SOURCE_START_MS + WINDOW_DAYS * DAY_MS,
    SOURCE_START_MS + 2 * WINDOW_DAYS * DAY_MS,
    SOURCE_END_MS,
)
WINDOWS = (("1m_w1", BOUNDARIES[0], BOUNDARIES[1]), ("1m_w2", BOUNDARIES[1], BOUNDARIES[2]), ("1m_w3", BOUNDARIES[2], BOUNDARIES[3]))
KLINE_LIMIT = 1000
KLINE_CHUNK_BARS = 999
ROUND_RETRIES = 6


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(value), fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def request_json(endpoint: str, params: Mapping[str, Any]) -> Any:
    last = ""
    query = urllib.parse.urlencode(params)
    for attempt in range(ROUND_RETRIES):
        for base in BASE_URLS:
            try:
                req = urllib.request.Request(base + endpoint + "?" + query, headers={"Accept": "application/json", "User-Agent": "ZEL-SQUEEZE-ADMISSION-V1"})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    obj = json.loads(resp.read().decode("utf-8"))
                if isinstance(obj, dict) and obj.get("code") not in (None, 0):
                    raise RuntimeError(f"BINGX_CODE:{obj.get('code')}:{obj.get('msg')}")
                return obj.get("data", obj) if isinstance(obj, dict) else obj
            except Exception as exc:
                last = f"{base}:{type(exc).__name__}:{str(exc)[:180]}"
        time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{endpoint}:{last}")


def normalize_kline(row: Any) -> dict[str, Any] | None:
    if isinstance(row, Mapping):
        ts = row.get("openTime", row.get("time", row.get("timestamp")))
        o, h, l, c = row.get("open"), row.get("high"), row.get("low"), row.get("close")
        v = row.get("volume", row.get("vol", 0))
    elif isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and len(row) >= 6:
        ts, o, h, l, c, v = row[:6]
    else:
        return None
    try:
        ts_i = int(float(ts))
        vals = [float(x) for x in (o, h, l, c, v)]
    except (TypeError, ValueError):
        return None
    if ts_i < 10_000_000_000: ts_i *= 1000
    if not all(math.isfinite(x) for x in vals) or min(vals[:4]) <= 0 or vals[4] < 0:
        return None
    return {"timestamp_ms": ts_i, "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3], "volume": vals[4]}


def extract_rows(data: Any) -> list[Any]:
    if isinstance(data, list): return data
    if isinstance(data, Mapping):
        for key in ("data", "list", "rows", "items", "klines", "result"):
            if isinstance(data.get(key), list): return list(data[key])
    return []


def fetch_window(symbol: str, window_id: str, start_ms: int, end_ms: int, out_root: Path) -> dict[str, Any]:
    by_ts: dict[int, dict[str, Any]] = {}
    cursor = start_ms
    requests = 0
    while cursor < end_ms:
        stop = min(end_ms, cursor + KLINE_CHUNK_BARS * MINUTE_MS)
        raw = request_json(KLINE_ENDPOINT, {"symbol": BINGX_SYMBOL[symbol], "interval": INTERVAL, "startTime": cursor, "endTime": stop, "limit": KLINE_LIMIT})
        requests += 1
        for item in extract_rows(raw):
            row = normalize_kline(item)
            if row is None: continue
            ts = int(row["timestamp_ms"])
            if cursor <= ts < stop:
                prior = by_ts.get(ts)
                if prior is not None and prior != row: raise RuntimeError(f"CONFLICTING_KLINE:{symbol}:{ts}")
                by_ts[ts] = row
        cursor = stop
        time.sleep(0.02)
    expected = list(range(start_ms, end_ms, MINUTE_MS))
    missing = [ts for ts in expected if ts not in by_ts]
    if missing:
        raise RuntimeError(f"SOURCE_GAP:{symbol}:{window_id}:missing={len(missing)}:first={missing[:3]}")
    rows = [by_ts[ts] for ts in expected]
    path = out_root / "market" / f"{window_id}_{symbol}_1m.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return {"kind": "market", "interval": "1m", "window_id": window_id, "symbol": symbol, "path": str(path.relative_to(out_root)), "row_count": len(rows), "start_ms": start_ms, "end_exclusive_ms": end_ms, "sha256": sha256_path(path), "request_count": requests}


def funding_time(row: Any) -> int | None:
    if not isinstance(row, Mapping): return None
    raw = row.get("fundingTime", row.get("time", row.get("timestamp")))
    try: ts = int(float(raw))
    except (TypeError, ValueError): return None
    return ts * 1000 if ts < 10_000_000_000 else ts


def fetch_funding(symbol: str, out_root: Path) -> dict[str, Any]:
    rows: dict[int, float] = {}
    cursor = SOURCE_START_MS
    requests = 0
    chunk = 7 * DAY_MS
    while cursor < SOURCE_END_MS:
        stop = min(SOURCE_END_MS, cursor + chunk)
        raw = request_json(FUNDING_ENDPOINT, {"symbol": BINGX_SYMBOL[symbol], "startTime": cursor, "endTime": stop, "limit": 1000})
        requests += 1
        for item in extract_rows(raw):
            ts = funding_time(item)
            if ts is None or not (SOURCE_START_MS <= ts < SOURCE_END_MS): continue
            try: rate = float(item.get("fundingRate"))
            except (TypeError, ValueError, AttributeError): continue
            if math.isfinite(rate): rows[ts] = rate
        cursor = stop
        time.sleep(0.02)
    ordered = [{"timestamp_ms": ts, "funding_rate": rows[ts]} for ts in sorted(rows)]
    gaps = [b-a for a,b in zip(sorted(rows), sorted(rows)[1:])]
    if not ordered or (gaps and max(gaps) > 24 * 60 * MINUTE_MS):
        raise RuntimeError(f"FUNDING_GAP:{symbol}:rows={len(ordered)}:max_gap_ms={max(gaps) if gaps else None}")
    path = out_root / "funding" / f"{symbol}.json"
    atomic_json(path, {"symbol": symbol, "rows": ordered, "source": "BINGX_NATIVE_FUNDING", "execution_authority": "NONE", "order_authority": "BLOCKED"})
    return {"symbol": symbol, "row_count": len(ordered), "sha256": sha256_path(path), "request_count": requests}


def load_module(path: Path) -> Any:
    name = f"zel_exact25_admission_engine_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError("ENGINE_IMPORT_FAILED")
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod); return mod


def payoff(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    vals = [float(r[field]) for r in rows if r.get(field) is not None]
    wins = [x for x in vals if x > 0]; losses = [-x for x in vals if x < 0]
    if not losses: return 999.0 if wins else 0.0
    if not wins: return 0.0
    return (sum(wins)/len(wins)) / (sum(losses)/len(losses))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, default=Path("/home/z/z"))
    ap.add_argument("--engine", type=Path, default=Path("/home/z/z/backend/tools/zel_historical_oos_exact25_replay_v1.py"))
    ap.add_argument("--queue", type=Path, default=Path("/home/z/z/ledger/production_performance_bootstrap_queue_v1.json"))
    ap.add_argument("--work-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    candidates = queue.get("admission_queue") or []
    if len(candidates) != 1 or candidates[0].get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("ADMISSION_QUEUE_NOT_SQUEEZE_BREAK_SINGLE")
    expected_owner = str(candidates[0].get("source_owner_sha256") or "")
    if not expected_owner: raise RuntimeError("ADMISSION_OWNER_SHA_MISSING")

    root = args.work_root.resolve(); root.mkdir(parents=True, exist_ok=True)
    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for window_id, start_ms, end_ms in WINDOWS:
            for symbol in SYMBOLS:
                tasks.append(pool.submit(fetch_window, symbol, window_id, start_ms, end_ms, root))
        files = [future.result() for future in tasks]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        funding = list(pool.map(lambda s: fetch_funding(s, root), SYMBOLS))
    total_rows = sum(int(r["row_count"]) for r in files)
    manifest = {
        "state": "PASS_HISTORICAL_OOS_DATA_READY",
        "total_market_rows": total_rows,
        "forward_overlap_count": 0,
        "historical_data_is_promotion_authority": False,
        "final_holdout_accessed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "symbols": list(SYMBOLS),
        "files": sorted(files, key=lambda r: (r["window_id"], r["symbol"])),
        "funding": funding,
        "source_start_ms": SOURCE_START_MS,
        "source_end_exclusive_ms": SOURCE_END_MS,
        "source_days": SOURCE_DAYS,
        "window_days": WINDOW_DAYS,
        "source_relation_to_exact25": "STRICTLY_PRECEDES_FROZEN_EXACT25_FIRST_WINDOW",
        "source_values_used_for_horizon_selection": False,
    }
    manifest["receipt_sha256"] = stable_sha(manifest); atomic_json(root / "manifest.json", manifest)

    engine = load_module(args.engine.resolve())
    engine.EXPECTED_DATA_ROWS = total_rows
    engine.init_worker(str(args.source_root.resolve()), str(root), "1m")
    raw = engine.replay_strategy(STRATEGY_ID)
    card, trades = engine.aggregate_strategy(raw)
    if card.get("owner_sha256") != expected_owner:
        raise RuntimeError(f"OWNER_SHA_MISMATCH:{card.get('owner_sha256')}:{expected_owner}")
    if int(card.get("error_count") or 0) != 0 or int(card.get("censored_open_at_window_end") or 0) != 0:
        raise RuntimeError("ADMISSION_REPLAY_INTEGRITY_FAIL")

    funded_field = "realized_R_including_funding_estimate"
    by_window: dict[str, Any] = {}
    for window_id, _, _ in WINDOWS:
        subset = [r for r in trades if str(r.get("window_id")) == window_id]
        m = engine.metrics(subset, funded_field)
        by_window[window_id.replace("1m_", "").upper()] = {
            "sample_count": int(m["sample_count"]),
            "net_pnl": float(m["net_R"]),
            "profit_factor": float(m["profit_factor"] or 0.0),
            "expectancy": float(m["expectancy_R"] or 0.0),
            "payoff_ratio": float(payoff(subset, funded_field)),
            "retention": 1.0,
            "retention_basis": "SAME_CANONICAL_RULE_NO_FILTER_OR_PARAMETER_CHANGE",
            "max_drawdown_R": float(m["max_drawdown_R"] or 0.0),
            "win_rate_pct": float(m["win_rate_pct"] or 0.0),
        }

    aggregate = engine.metrics(trades, funded_field)
    sample_count = int(aggregate["sample_count"])
    sample_gate = engine.claim_tier(sample_count) != "LOW_SAMPLE_HOLD" and sample_count >= 20
    windows_pass = all(
        row["sample_count"] > 0 and row["net_pnl"] > 0 and row["profit_factor"] >= 1.0 and row["expectancy"] > 0 and row["payoff_ratio"] >= 1.0 and row["retention"] >= 0.60
        for row in by_window.values()
    )
    economic_pass = sample_gate and windows_pass
    state = "HOLD_BOOTSTRAP_ECONOMIC_PASS_RISK_AUTHORITY_MISSING" if economic_pass else "REJECT_BOOTSTRAP_ADMISSION_EVIDENCE"
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "sample_gate_pass": sample_gate,
        "sample_gate_authority": {"engine_claim_tier": engine.claim_tier(sample_count), "low_sample_threshold_trades": 20},
        "integrity": {"error_count": int(card.get("error_count") or 0), "duplicate_count": 0, "censored_count": int(card.get("censored_open_at_window_end") or 0)},
        "windows": by_window,
        "aggregate_metrics": {
            "trade_count": sample_count,
            "net_expectancy": float(aggregate["expectancy_R"] or 0.0),
            "profit_factor": float(aggregate["profit_factor"] or 0.0),
            "net_pnl": float(aggregate["net_R"]),
            "max_dd_R": float(aggregate["max_drawdown_R"] or 0.0),
            "win_rate_pct": float(aggregate["win_rate_pct"] or 0.0),
            "payoff_ratio": float(payoff(trades, funded_field)),
        },
        "economic_gate_pass": economic_pass,
        "risk_authority_bound": False,
        "authority_candidate": None,
        "source": {"dataset_manifest_sha256": manifest["receipt_sha256"], "owner_sha256": expected_owner, "source_start_ms": SOURCE_START_MS, "source_end_exclusive_ms": SOURCE_END_MS, "window_days": WINDOW_DAYS, "funding_model": "BINGX_NATIVE_HISTORY_APPLIED_TO_EXACT25_ENTRY_NOTIONAL_SEMANTICS"},
        "rule_changed": False,
        "parameter_search": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "next": "BIND_CANONICAL_RISK_REQUEST_THEN_SEED_INCUMBENT" if economic_pass else "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result); atomic_json(args.out, result)
    print(json.dumps({"state": state, "sample_count": sample_count, "claim_tier": engine.claim_tier(sample_count), "economic_gate_pass": economic_pass, "windows": by_window, "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
