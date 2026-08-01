from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_BINGX_EXECUTION_EVIDENCE_COLLECTOR_V1"
BASES = ("https://open-api.bingx.com", "https://open-api.bingx.pro")
READ_ENDPOINTS = {
    "balance": "/openApi/swap/v3/user/balance",
    "positions": "/openApi/swap/v2/user/positions",
    "commission": "/openApi/swap/v2/user/commissionRate",
    "income": "/openApi/swap/v2/user/income",
}
SENSITIVE_KEYS = {"orderid", "tradeid", "tranid", "clientorderid", "api_key", "apikey", "secret", "signature"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_params(params: Mapping[str, Any]) -> None:
    forbidden = set("&=?#\r\n")
    for key, value in params.items():
        if any(ch in str(value) for ch in forbidden):
            raise ValueError(f"FORBIDDEN_PARAM_CHAR:{key}")


def signed_query(secret: str, params: Mapping[str, Any]) -> str:
    validate_params(params)
    qs = urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))
    signature = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return f"{qs}&signature={signature}"


def read_get(path: str, params: Mapping[str, Any], api_key: str, secret: str, timeout: float = 10.0) -> Any:
    if path not in READ_ENDPOINTS.values():
        raise ValueError(f"ENDPOINT_NOT_ALLOWLISTED:{path}")
    all_params = dict(params)
    all_params["timestamp"] = int(time.time() * 1000)
    all_params.setdefault("recvWindow", 5000)
    query = signed_query(secret, all_params)
    last_error: Exception | None = None
    for index, base in enumerate(BASES):
        request = urllib.request.Request(
            f"{base}{path}?{query}",
            method="GET",
            headers={"X-BX-APIKEY": api_key, "X-SOURCE-KEY": "BX-AI-SKILL"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != 0:
                raise RuntimeError(f"BINGX_ERROR:{payload.get('code')}:{payload.get('msg')}")
            return payload.get("data")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            if index == len(BASES) - 1:
                raise
        except Exception:
            raise
    raise RuntimeError(f"BINGX_NETWORK_FAILURE:{last_error}")


def redact(value: Any) -> Any:
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                out[f"{key}_sha256"] = hashlib.sha256(str(item).encode()).hexdigest()
            else:
                out[str(key)] = redact(item)
        return out
    return value


def normalize_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        candidate = next((v for v in data.values() if isinstance(v, list)), [])
        rows = candidate if isinstance(candidate, list) else []
    else:
        rows = []
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean = redact(row)
        event_id = sha256_json(clean)
        if event_id in seen:
            continue
        seen.add(event_id)
        clean["evidence_event_sha256"] = event_id
        normalized.append(clean)
    return normalized


def collect_income(api_key: str, secret: str, start_ms: int, end_ms: int, limit: int = 1000, min_window_ms: int = 3_600_000) -> list[dict[str, Any]]:
    pending = [(start_ms, end_ms)]
    all_rows: list[dict[str, Any]] = []
    while pending:
        left, right = pending.pop()
        raw = read_get(READ_ENDPOINTS["income"], {"startTime": left, "endTime": right, "limit": limit}, api_key, secret)
        rows = normalize_rows(raw)
        if len(rows) >= limit and right - left > min_window_ms:
            middle = left + (right - left) // 2
            pending.extend([(left, middle), (middle + 1, right)])
            continue
        all_rows.extend(rows)
    unique = {row["evidence_event_sha256"]: row for row in all_rows}
    return sorted(unique.values(), key=lambda row: (int(row.get("time", 0) or 0), row["evidence_event_sha256"]))


def load_fill_import(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("fills", [])
    return normalize_rows(rows)


def build_receipt(evidence: Mapping[str, Any], lookback_days: int, source: str) -> dict[str, Any]:
    incomes = evidence.get("income", [])
    fills = evidence.get("fills", [])
    timestamps = [int(row.get("time", 0) or 0) for row in incomes if int(row.get("time", 0) or 0) > 0]
    coverage = {
        "requested_lookback_days": lookback_days,
        "income_event_count": len(incomes),
        "fill_event_count": len(fills),
        "first_income_time": min(timestamps) if timestamps else None,
        "last_income_time": max(timestamps) if timestamps else None,
        "missing_interval_detection": "WINDOW_SPLIT_AND_COUNT_ONLY_V1",
    }
    return {
        "schema_version": "zel.bingx.execution_evidence.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_BINGX_READ_ONLY_EVIDENCE_COLLECTED",
        "source": source,
        "evidence_sha256": sha256_json(evidence),
        "coverage": coverage,
        "direct_runtime_application_allowed": False,
        "strategy_mutated": False,
        "runtime_registry_written": False,
        "credentials_persisted": False,
        "raw_order_ids_persisted": False,
        "methods_used": ["GET"],
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    q = signed_query("secret", {"timestamp": 1, "limit": 100})
    assert "signature=" in q
    sample = [{"orderId": 123, "incomeType": "TRADING_FEE", "income": "-1", "time": 2}]
    rows = normalize_rows(sample)
    assert "orderId" not in rows[0] and "orderId_sha256" in rows[0]
    evidence = {"balance": {}, "positions": [], "commission": {}, "income": rows, "fills": []}
    receipt = build_receipt(evidence, 7, "SELF_TEST")
    assert receipt["credentials_persisted"] is False
    assert receipt["order_authority"] == "BLOCKED"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--fills-json", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.out_dir is None:
        parser.error("out-dir is required")
    if not 1 <= args.lookback_days <= 90:
        parser.error("lookback-days must be 1..90")
    api_key = os.environ.get("BINGX_API_KEY")
    secret = os.environ.get("BINGX_SECRET_KEY")
    if not api_key or not secret:
        raise SystemExit("BINGX_READ_ONLY_CREDENTIALS_MISSING")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.lookback_days)
    evidence = {
        "schema_version": "zel.bingx.execution_evidence.dataset.v1",
        "generated_at": now_iso(),
        "balance": redact(read_get(READ_ENDPOINTS["balance"], {}, api_key, secret)),
        "positions": normalize_rows(read_get(READ_ENDPOINTS["positions"], {}, api_key, secret)),
        "commission": redact(read_get(READ_ENDPOINTS["commission"], {}, api_key, secret)),
        "income": collect_income(api_key, secret, int(start.timestamp() * 1000), int(end.timestamp() * 1000)),
        "fills": load_fill_import(args.fills_json),
        "credentials_persisted": False,
        "raw_order_ids_persisted": False,
    }
    receipt = build_receipt(evidence, args.lookback_days, "BINGX_API_AND_OPTIONAL_LOCAL_FILL_IMPORT")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out_dir / "evidence.json"
    receipt_path = args.out_dir / "receipt.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["files"] = {
        "evidence.json": {"sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(), "bytes": evidence_path.stat().st_size}
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "income_events": len(evidence["income"]), "fill_events": len(evidence["fills"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
