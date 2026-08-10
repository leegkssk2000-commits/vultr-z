#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
W1_START_MS = 1782549000000  # 2026-06-27T08:30:00Z
W2_END_MS = 1784276940000    # 2026-07-17T08:29:00Z
ENDPOINTS = {
    "funding": "/openApi/swap/v2/quote/fundingRate",
    "premium_index": "/openApi/swap/v2/quote/premiumIndex",
    "open_interest": "/openApi/swap/v2/quote/openInterest",
    "ticker": "/openApi/swap/v2/quote/ticker",
}
SYMBOLS = ("BTC-USDT", "ETH-USDT")
TIME_KEYS = ("fundingTime", "funding_time", "timestamp", "time", "ts", "createTime", "updateTime")


def canonical_sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def get_json(path: str, params: dict[str, Any]) -> tuple[Any, str, float]:
    ctx = ssl.create_default_context()
    errors: list[str] = []
    for base in BASES:
        try:
            url = base + path + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "ZEL-P3-readonly/1.1"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
            latency_ms = (time.perf_counter() - t0) * 1000.0
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("code") not in (None, 0):
                raise RuntimeError(f"code={obj.get('code')} msg={obj.get('msg')}")
            return (obj.get("data", obj) if isinstance(obj, dict) else obj), base, latency_ms
        except Exception as exc:
            errors.append(f"{base}:{type(exc).__name__}:{str(exc)[:180]}")
    raise RuntimeError(" | ".join(errors))


def rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("data", "list", "rows", "fundingRates", "result"):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [data]
    return []


def to_ms(v: Any) -> int | None:
    try:
        x = int(float(v))
        return x * 1000 if x < 10_000_000_000 else x
    except Exception:
        return None


def timestamps(rs: list[dict[str, Any]]) -> tuple[list[int], list[str]]:
    out: list[int] = []
    used: set[str] = set()
    for r in rs:
        for key in TIME_KEYS:
            if key not in r:
                continue
            x = to_ms(r.get(key))
            if x is not None:
                out.append(x)
                used.add(key)
                break
    return sorted(out), sorted(used)


def safe_schema(rs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rs),
        "keys": sorted({str(k) for r in rs[:30] for k in r.keys()})[:100],
    }


def probe_endpoint(name: str, path: str, symbol: str, now_ms: int) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "endpoint": path, "symbol": symbol, "write_endpoint_called": False}
    variants = {
        "current": {"symbol": symbol},
        "historical_window": {"symbol": symbol, "startTime": W1_START_MS, "endTime": now_ms, "limit": 1000},
    }
    for label, params in variants.items():
        try:
            data, base, latency_ms = get_json(path, params)
            rs = rows(data)
            ts, keys_used = timestamps(rs)
            result[label] = {
                "state": "PASS_READ",
                "base": base,
                "latency_ms": latency_ms,
                **safe_schema(rs),
                "timestamp_keys_used": keys_used,
                "min_timestamp_ms": ts[0] if ts else None,
                "max_timestamp_ms": ts[-1] if ts else None,
                "coverage_days": (ts[-1] - ts[0]) / 86400000.0 if len(ts) >= 2 else 0.0,
                "covers_W1_start": bool(ts and ts[0] <= W1_START_MS),
                "covers_W2_end": bool(ts and ts[-1] >= W2_END_MS),
                "historical_coverage_for_W1_W2": bool(ts and ts[0] <= W1_START_MS and ts[-1] >= W2_END_MS and len(ts) > 1),
            }
        except Exception as exc:
            result[label] = {"state": "HOLD_READ_FAILED", "error": f"{type(exc).__name__}:{str(exc)[:500]}"}
    return result


def main() -> int:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    probes: list[dict[str, Any]] = []
    for name, path in ENDPOINTS.items():
        for symbol in SYMBOLS:
            probes.append(probe_endpoint(name, path, symbol, now_ms))

    def historical_ok(name: str) -> bool:
        xs = [p for p in probes if p["name"] == name]
        return len(xs) == len(SYMBOLS) and all(p.get("historical_window", {}).get("historical_coverage_for_W1_W2") is True for p in xs)

    funding_ok = historical_ok("funding")
    premium_ok = historical_ok("premium_index")
    oi_ok = historical_ok("open_interest")
    current_flags = {
        name: all(p.get("current", {}).get("state") == "PASS_READ" for p in probes if p["name"] == name)
        for name in ENDPOINTS
    }
    blockers: list[str] = []
    if not funding_ok:
        blockers.append("FUNDING_HISTORY_DOES_NOT_COVER_W1_W2")
    if not premium_ok:
        blockers.append("PREMIUM_INDEX_BASIS_HISTORY_DOES_NOT_COVER_W1_W2")
    if not oi_ok:
        blockers.append("OPEN_INTEREST_HISTORY_DOES_NOT_COVER_W1_W2")

    state = "PASS_P3_NATIVE_ENDPOINT_HISTORY_BINDING" if not blockers else "HOLD_P3_NATIVE_ENDPOINT_HISTORY_GAPS"
    receipt: dict[str, Any] = {
        "schema_version": "zel.p3.native_endpoint_probe.v1",
        "state": state,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "target_W1_start_ms": W1_START_MS,
        "target_W2_end_ms": W2_END_MS,
        "symbols": list(SYMBOLS),
        "endpoint_contract": ENDPOINTS,
        "endpoints_are_previously_discovered_runtime_literals": True,
        "probes": probes,
        "historical_binding": {
            "funding_W1_W2": funding_ok,
            "premium_index_W1_W2": premium_ok,
            "open_interest_W1_W2": oi_ok,
        },
        "current_endpoint_readability": current_flags,
        "blockers": blockers,
        "interpretation": "Passing current endpoint reads do not substitute for historical aligned coverage. No unobserved endpoint path, synthetic history, interpolation, or threshold is invented.",
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
