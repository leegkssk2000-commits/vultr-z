from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCHEMA = "zel.production_bingx_l2_prospective.v1"
POLICY_SCHEMA = "zel.production_bingx_l2_prospective_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_bingx_l2_prospective_v1.json")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("BINGX_L2_PROSPECTIVE_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "PROSPECTIVE_PUBLIC_MARKET_HISTORY_COLLECTOR_NOT_STRATEGY":
        raise RuntimeError("BINGX_L2_PROSPECTIVE_ROLE_DRIFT")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_SELECTION_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("BINGX_L2_PROSPECTIVE_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_LIVE_FORBIDDEN")
    if policy.get("economic_signal_enabled") is not False or policy.get("history_gate_decision") != "UNSET_BY_COLLECTOR":
        raise RuntimeError("BINGX_L2_PROSPECTIVE_RESEARCH_BOUNDARY_INVALID")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_MUTATION_FORBIDDEN")
    base = str(policy.get("base_url") or "").rstrip("/")
    if base not in {"https://open-api.bingx.com", "https://open-api.bingx.pro"}:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_BASE_URL_INVALID")
    symbols = policy.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(not str(x).endswith("-USDT") for x in symbols):
        raise RuntimeError("BINGX_L2_PROSPECTIVE_SYMBOLS_INVALID")
    if str(policy.get("kline_interval") or "") not in {"1m", "3m", "5m", "15m", "30m", "1h"}:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_INTERVAL_INVALID")
    if int(policy.get("depth_limit") or 0) not in {5, 10, 20, 50, 100}:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_DEPTH_LIMIT_INVALID")
    if int(policy.get("bucket_ms") or 0) < 60_000:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_BUCKET_INVALID")
    if int(policy.get("request_pause_ms") or 0) < 0:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_PAUSE_INVALID")
    for key in ("history_path", "summary_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"BINGX_L2_PROSPECTIVE_PATH_MISSING:{key}")
    return dict(policy)


def _request_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ZEL-PAPER-RESEARCH/1.0", "X-SOURCE-KEY": "BX-AI-SKILL"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, Mapping):
        raise RuntimeError("BINGX_L2_PROSPECTIVE_RESPONSE_NOT_OBJECT")
    return dict(payload)


def _api_get(base: str, path: str, params: Mapping[str, Any], fetcher: Callable[[str], Mapping[str, Any]]) -> Any:
    query = dict(params)
    query["timestamp"] = int(time.time() * 1000)
    payload = fetcher(f"{base}{path}?{urllib.parse.urlencode(query)}")
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_L2_PROSPECTIVE_API_ERROR:{payload.get('code')}:{str(payload.get('msg') or '')[:200]}")
    return payload.get("data")


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"BINGX_L2_PROSPECTIVE_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"BINGX_L2_PROSPECTIVE_NUMERIC_NONFINITE:{label}")
    return out


def _normalize_klines(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_KLINES_EMPTY")
    rows: list[dict[str, Any]] = []
    for raw in data[:4]:
        if isinstance(raw, Mapping):
            required = {"time", "open", "high", "low", "close", "volume"}
            if not required.issubset(raw):
                raise RuntimeError("BINGX_L2_PROSPECTIVE_KLINE_OBJECT_SCHEMA_INVALID")
            rows.append({
                "time_ms": int(_finite(raw.get("time"), "time")),
                "open": _finite(raw.get("open"), "open"),
                "high": _finite(raw.get("high"), "high"),
                "low": _finite(raw.get("low"), "low"),
                "close": _finite(raw.get("close"), "close"),
                "volume": _finite(raw.get("volume"), "volume"),
                "schema": "BINGX_V3_OBJECT_OHLCV",
            })
        elif isinstance(raw, list) and len(raw) >= 7:
            rows.append({
                "time_ms": int(_finite(raw[0], "0")),
                "open": _finite(raw[1], "1"),
                "high": _finite(raw[2], "2"),
                "low": _finite(raw[3], "3"),
                "close": _finite(raw[4], "4"),
                "volume": _finite(raw[5], "5"),
                "close_time_ms": int(_finite(raw[6], "6")),
                "schema": "BINGX_ARRAY_OHLCV",
            })
        else:
            raise RuntimeError("BINGX_L2_PROSPECTIVE_KLINE_SCHEMA_INVALID")
    rows.sort(key=lambda x: int(x["time_ms"]))
    return rows


def _normalize_side(values: Any, label: str, limit: int) -> list[list[float]]:
    if not isinstance(values, list) or not values:
        raise RuntimeError(f"BINGX_L2_PROSPECTIVE_{label.upper()}_EMPTY")
    out: list[list[float]] = []
    for raw in values[:limit]:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise RuntimeError(f"BINGX_L2_PROSPECTIVE_{label.upper()}_SCHEMA_INVALID")
        price, qty = _finite(raw[0], f"{label}_price"), _finite(raw[1], f"{label}_qty")
        if price <= 0 or qty < 0:
            raise RuntimeError(f"BINGX_L2_PROSPECTIVE_{label.upper()}_VALUE_INVALID")
        out.append([price, qty])
    return out


def _depth_features(data: Any, limit: int) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise RuntimeError("BINGX_L2_PROSPECTIVE_DEPTH_NOT_OBJECT")
    bids = _normalize_side(data.get("bids"), "bids", limit)
    asks = _normalize_side(data.get("asks"), "asks", limit)
    best_bid, best_ask = bids[0][0], asks[0][0]
    if best_ask < best_bid:
        raise RuntimeError("BINGX_L2_PROSPECTIVE_CROSSED_BOOK")
    mid = (best_bid + best_ask) / 2.0
    features: dict[str, Any] = {
        "source_event_time_ms": int(data.get("T") or 0),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": (best_ask - best_bid) / mid * 10000.0,
        "bids": bids,
        "asks": asks,
    }
    for depth in (5, 10, 20):
        n = min(depth, len(bids), len(asks))
        if n <= 0:
            continue
        bid_qty = sum(row[1] for row in bids[:n])
        ask_qty = sum(row[1] for row in asks[:n])
        total = bid_qty + ask_qty
        features[f"bid_qty_top{depth}"] = bid_qty
        features[f"ask_qty_top{depth}"] = ask_qty
        features[f"qty_imbalance_top{depth}"] = (bid_qty - ask_qty) / total if total > 0 else 0.0
    return features


def capture_snapshot(
    policy: Mapping[str, Any],
    *,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_ms: int | None = None,
) -> list[dict[str, Any]]:
    cfg = validate_policy(policy)
    caller = fetcher or _request_json
    base = str(cfg["base_url"]).rstrip("/")
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    bucket_ms = int(cfg["bucket_ms"])
    bucket = now - (now % bucket_ms)
    rows: list[dict[str, Any]] = []
    call_count = 0
    for symbol in cfg["symbols"]:
        if call_count and int(cfg["request_pause_ms"]):
            sleep_fn(int(cfg["request_pause_ms"]) / 1000.0)
        klines = _api_get(base, "/openApi/swap/v3/quote/klines", {"symbol": symbol, "interval": cfg["kline_interval"], "limit": 2}, caller)
        call_count += 1
        if int(cfg["request_pause_ms"]):
            sleep_fn(int(cfg["request_pause_ms"]) / 1000.0)
        depth = _api_get(base, "/openApi/swap/v2/quote/depth", {"symbol": symbol, "limit": int(cfg["depth_limit"])}, caller)
        call_count += 1
        rows.append({
            "schema_version": SCHEMA,
            "capture_bucket_ms": bucket,
            "captured_at_ms": now,
            "symbol": str(symbol),
            "provider": "BINGX_PUBLIC_USDT_PERPETUAL",
            "source_contract": {"kline": "/openApi/swap/v3/quote/klines", "depth": "/openApi/swap/v2/quote/depth"},
            "kline_interval": str(cfg["kline_interval"]),
            "klines": _normalize_klines(klines),
            "l2": _depth_features(depth, int(cfg["depth_limit"])),
            "economic_signal_enabled": False,
            "history_gate_decision": "UNSET_BY_COLLECTOR",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
        })
    return rows


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _recent_keys(history_path: Path, max_lines: int = 256) -> set[tuple[str, int]]:
    if not history_path.is_file():
        return set()
    lines = history_path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    out: set[tuple[str, int]] = set()
    for line in lines:
        try:
            row = json.loads(line)
            out.add((str(row.get("symbol") or ""), int(row.get("capture_bucket_ms") or 0)))
        except Exception:
            continue
    return out


def append_rows(policy: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cfg = validate_policy(policy)
    history_path, summary_path = Path(str(cfg["history_path"])), Path(str(cfg["summary_path"]))
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = history_path.with_suffix(history_path.suffix + ".lock")
    lock_path.touch(exist_ok=True)
    appended: list[Mapping[str, Any]] = []
    with lock_path.open("r+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        seen = _recent_keys(history_path)
        with history_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                key = (str(row.get("symbol") or ""), int(row.get("capture_bucket_ms") or 0))
                if key in seen:
                    continue
                handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                appended.append(row)
                seen.add(key)
            handle.flush()
            os.fsync(handle.fileno())
        all_lines = history_path.read_text(encoding="utf-8", errors="replace").splitlines()
        counts: dict[str, int] = {}
        first_ms: int | None = None
        last_ms: int | None = None
        for line in all_lines:
            try:
                item = json.loads(line)
                symbol = str(item.get("symbol") or "")
                ts = int(item.get("capture_bucket_ms") or 0)
            except Exception:
                continue
            if not symbol or ts <= 0:
                continue
            counts[symbol] = counts.get(symbol, 0) + 1
            first_ms = ts if first_ms is None else min(first_ms, ts)
            last_ms = ts if last_ms is None else max(last_ms, ts)
        summary = {
            "schema_version": "zel.production_bingx_l2_prospective_summary.v1",
            "state": "PASS_BINGX_L2_PROSPECTIVE_HISTORY_ACCUMULATING",
            "role": "PROSPECTIVE_PUBLIC_MARKET_HISTORY_COLLECTOR_NOT_STRATEGY",
            "appended_count": len(appended),
            "total_observation_count": sum(counts.values()),
            "observation_count_by_symbol": counts,
            "first_capture_bucket_ms": first_ms,
            "last_capture_bucket_ms": last_ms,
            "elapsed_ms": (last_ms - first_ms) if first_ms is not None and last_ms is not None else 0,
            "prospective_history_started": bool(counts),
            "history_gate_decision": "UNSET_BY_COLLECTOR",
            "economic_signal_enabled": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": int(time.time() * 1000),
        }
        _atomic_json(summary_path, summary)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture one deduplicated prospective BingX OHLCV/L2 snapshot")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    rows = capture_snapshot(policy)
    summary = append_rows(policy, rows)
    print(json.dumps({
        "state": summary["state"],
        "appended_count": summary["appended_count"],
        "total_observation_count": summary["total_observation_count"],
        "observation_count_by_symbol": summary["observation_count_by_symbol"],
        "history_gate_decision": summary["history_gate_decision"],
        "economic_signal_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
