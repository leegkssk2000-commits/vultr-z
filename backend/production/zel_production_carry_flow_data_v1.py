from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "zel.production_carry_flow_data.v1"
BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
SYMBOLS = ("BTC-USDT", "ETH-USDT")
ENDPOINTS = {
    "premium_index": "/openApi/swap/v2/quote/premiumIndex",
    "open_interest": "/openApi/swap/v2/quote/openInterest",
}
DEFAULT_OUT = Path("/home/z/z/ledger/production_carry_flow_data_v1.json")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite_float(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"CARRY_FLOW_NUMERIC_INVALID:{label}") from exc
    if out != out or out in (float("inf"), float("-inf")):
        raise RuntimeError(f"CARRY_FLOW_NUMERIC_NONFINITE:{label}")
    return out


def _timestamp_ms(value: Any, label: str) -> int:
    try:
        out = int(float(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"CARRY_FLOW_TIMESTAMP_INVALID:{label}") from exc
    if out < 10_000_000_000:
        out *= 1000
    if out <= 0:
        raise RuntimeError(f"CARRY_FLOW_TIMESTAMP_INVALID:{label}")
    return out


def fetch_json(path: str, params: Mapping[str, Any]) -> tuple[dict[str, Any], str, float]:
    context = ssl.create_default_context()
    errors: list[str] = []
    for base in BASES:
        try:
            url = base + path + "?" + urllib.parse.urlencode(dict(params))
            request = urllib.request.Request(url, headers={"User-Agent": "ZEL-production-carry-flow/1.0"})
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=12, context=context) as response:
                obj = json.loads(response.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - started) * 1000.0
            if isinstance(obj, dict) and obj.get("code") not in (None, 0):
                raise RuntimeError(f"code={obj.get('code')} msg={obj.get('msg')}")
            data = obj.get("data", obj) if isinstance(obj, dict) else obj
            if isinstance(data, list):
                if len(data) != 1 or not isinstance(data[0], dict):
                    raise RuntimeError(f"unexpected_list_cardinality={len(data)}")
                data = data[0]
            if not isinstance(data, dict):
                raise RuntimeError(f"unexpected_payload_type={type(data).__name__}")
            return data, base, latency_ms
        except Exception as exc:
            errors.append(f"{base}:{type(exc).__name__}:{str(exc)[:160]}")
    raise RuntimeError("CARRY_FLOW_BINGX_FETCH_FAILED:" + " | ".join(errors))


def _normalize_premium(symbol: str, payload: Mapping[str, Any], source_base: str, latency_ms: float) -> dict[str, Any]:
    mark = _finite_float(payload.get("markPrice"), f"{symbol}.markPrice")
    index = _finite_float(payload.get("indexPrice"), f"{symbol}.indexPrice")
    funding = _finite_float(payload.get("lastFundingRate"), f"{symbol}.lastFundingRate")
    source_ts = _timestamp_ms(payload.get("updateTime"), f"{symbol}.updateTime")
    if mark <= 0.0 or index <= 0.0:
        raise RuntimeError(f"CARRY_FLOW_PRICE_NONPOSITIVE:{symbol}")
    basis_bps = (mark / index - 1.0) * 10_000.0
    return {
        "feature": "premium_index",
        "symbol": symbol,
        "source_endpoint": ENDPOINTS["premium_index"],
        "source_base": source_base,
        "source_timestamp_ms": source_ts,
        "latency_ms": float(latency_ms),
        "raw": {
            "markPrice": mark,
            "indexPrice": index,
            "lastFundingRate": funding,
            "fundingIntervalHours": payload.get("fundingIntervalHours"),
            "nextFundingTime": payload.get("nextFundingTime"),
        },
        "derived_observation": {"basis_bps": basis_bps},
        "source_payload_sha256": stable_sha(dict(payload)),
    }


def _normalize_oi(symbol: str, payload: Mapping[str, Any], source_base: str, latency_ms: float) -> dict[str, Any]:
    oi = _finite_float(payload.get("openInterest"), f"{symbol}.openInterest")
    source_ts = _timestamp_ms(payload.get("time"), f"{symbol}.time")
    if oi < 0.0:
        raise RuntimeError(f"CARRY_FLOW_OI_NEGATIVE:{symbol}")
    return {
        "feature": "open_interest",
        "symbol": symbol,
        "source_endpoint": ENDPOINTS["open_interest"],
        "source_base": source_base,
        "source_timestamp_ms": source_ts,
        "latency_ms": float(latency_ms),
        "raw": {"openInterest": oi},
        "source_payload_sha256": stable_sha(dict(payload)),
    }


def collect_snapshot(
    *,
    fetcher: Callable[[str, Mapping[str, Any]], tuple[dict[str, Any], str, float]] = fetch_json,
    now_ms: int | None = None,
) -> dict[str, Any]:
    observed_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    records: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        premium_payload, premium_base, premium_latency = fetcher(ENDPOINTS["premium_index"], {"symbol": symbol})
        oi_payload, oi_base, oi_latency = fetcher(ENDPOINTS["open_interest"], {"symbol": symbol})
        records.append(_normalize_premium(symbol, premium_payload, premium_base, premium_latency))
        records.append(_normalize_oi(symbol, oi_payload, oi_base, oi_latency))

    expected = {(feature, symbol) for symbol in SYMBOLS for feature in ENDPOINTS}
    actual = {(str(row["feature"]), str(row["symbol"])) for row in records}
    if actual != expected:
        raise RuntimeError("CARRY_FLOW_RECORD_PARITY_FAIL")

    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "PASS_CARRY_POSITIONING_RAW_DATA",
        "observed_at_ms": observed_at_ms,
        "symbols": list(SYMBOLS),
        "record_count": len(records),
        "records": records,
        "native_sources": ["premiumIndex", "openInterest"],
        "funding_source_bound": True,
        "basis_source_bound": True,
        "open_interest_source_bound": True,
        "flow_source_bound": False,
        "flow_blocker": "NO_VERIFIED_NATIVE_FLOW_SOURCE_BOUND",
        "economic_signal_generated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    snapshot["receipt_sha256"] = stable_sha(snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL production carry/positioning data collector")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = collect_snapshot()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_suffix(args.out.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(args.out)
    print(json.dumps({
        "state": result["state"],
        "record_count": result["record_count"],
        "flow_source_bound": result["flow_source_bound"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
