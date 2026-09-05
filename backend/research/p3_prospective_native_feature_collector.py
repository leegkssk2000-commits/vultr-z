#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
SYMBOLS = ("BTC-USDT", "ETH-USDT")
ENDPOINTS = {
    "premium_index": "/openApi/swap/v2/quote/premiumIndex",
    "open_interest": "/openApi/swap/v2/quote/openInterest",
}
PREMIUM_FIELDS = (
    "symbol", "markPrice", "indexPrice", "lastFundingRate", "fundingIntervalHours",
    "nextFundingTime", "minFundingRate", "maxFundingRate", "updateTime",
)
OI_FIELDS = ("symbol", "openInterest", "time")


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def to_ms(value: Any) -> int | None:
    try:
        x = int(float(value))
        return x * 1000 if x < 10_000_000_000 else x
    except Exception:
        return None


def get_json(path: str, params: dict[str, Any]) -> tuple[dict[str, Any], str, float]:
    ctx = ssl.create_default_context()
    errors: list[str] = []
    for base in BASES:
        try:
            url = base + path + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "ZEL-P3-prospective-readonly/1.0"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - t0) * 1000.0
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
            errors.append(f"{base}:{type(exc).__name__}:{str(exc)[:200]}")
    raise RuntimeError(" | ".join(errors))


def project(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload.get(key) for key in fields if key in payload}


def make_record(feature: str, symbol: str, payload: dict[str, Any], base: str, latency_ms: float, collected_ms: int) -> dict[str, Any]:
    if feature == "premium_index":
        values = project(payload, PREMIUM_FIELDS)
        source_ts = to_ms(payload.get("updateTime"))
        required = ("markPrice", "indexPrice", "updateTime")
    elif feature == "open_interest":
        values = project(payload, OI_FIELDS)
        source_ts = to_ms(payload.get("time"))
        required = ("openInterest", "time")
    else:
        raise ValueError(feature)
    missing = [key for key in required if payload.get(key) in (None, "")]
    if missing or source_ts is None:
        raise RuntimeError(f"HOLD_SCHEMA:{feature}:{symbol}:missing={missing}:source_ts={source_ts}")
    if source_ts > collected_ms:
        raise RuntimeError(f"HOLD_POINT_IN_TIME_CLOCK:{feature}:{symbol}")
    return {
        "schema_version": "zel.p3.prospective_native_feature_record.v1",
        "feature": feature,
        "symbol": symbol,
        "source_endpoint": ENDPOINTS[feature],
        "source_base": base,
        "source_timestamp_ms": source_ts,
        "collected_at_ms": collected_ms,
        "latency_ms": latency_ms,
        "values": values,
        "source_payload_sha256": canonical_sha(payload),
        "raw_payload": payload,
        "prospective_only": True,
        "historical_coverage_claim": False,
        "derived_basis_value_emitted": False,
        "signal_generation_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()
    observed_at = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    for feature in ("premium_index", "open_interest"):
        for symbol in SYMBOLS:
            payload, base, latency_ms = get_json(ENDPOINTS[feature], {"symbol": symbol})
            received_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            records.append(make_record(feature, symbol, payload, base, latency_ms, received_ms))
    keys = {(r["feature"], r["symbol"]) for r in records}
    expected = {(f, s) for f in ENDPOINTS for s in SYMBOLS}
    if keys != expected:
        raise RuntimeError(f"HOLD_RECORD_PARITY:{sorted(keys)}")
    receipt: dict[str, Any] = {
        "schema_version": "zel.p3.prospective_native_feature_snapshot.v1",
        "state": "PASS_P3_PROSPECTIVE_NATIVE_BASIS_OI_SNAPSHOT",
        "observed_at": observed_at.isoformat(),
        "symbols": list(SYMBOLS),
        "features": list(ENDPOINTS),
        "records": records,
        "record_count": len(records),
        "basis_source": "premiumIndex raw markPrice/indexPrice state; no derived basis admitted yet",
        "open_interest_source": "openInterest raw current snapshot",
        "flow_source_bound": False,
        "flow_blocker": "NO_VERIFIED_NATIVE_FLOW_ENDPOINT_IN_REPOSITORY_EVIDENCE",
        "prospective_only": True,
        "historical_coverage_claim": False,
        "replay_allowed": False,
        "parameter_selection_allowed": False,
        "signal_generation_enabled": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = canonical_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "record_count": len(records), "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
