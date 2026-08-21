#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPO = "leegkssk2000-commits/vultr-z"
RAW = f"https://raw.githubusercontent.com/{REPO}"
FUNDING_API = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
DAY_MS = 86_400_000


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "zel-wrsr-source-audit-v1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8")


def get_json(url: str) -> Any:
    return json.loads(get_text(url))


def api_rows(url: str, params: Mapping[str, Any]) -> list[Any]:
    payload = get_json(url + "?" + urllib.parse.urlencode(params))
    if isinstance(payload, Mapping) and payload.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX_{payload.get('code')}:{payload.get('msg')}")
    rows = payload.get("data", []) if isinstance(payload, Mapping) else payload
    return rows if isinstance(rows, list) else []


def parse_ndjson(text: str) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"NDJSON_ROW_NOT_OBJECT:{line_no}")
        rows.append(value)
    return rows


def funding_rows(symbol: str) -> list[dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for row in api_rows(FUNDING_API, {"symbol": symbol, "limit": 100}):
        if not isinstance(row, Mapping):
            continue
        ts = row.get("fundingTime") or row.get("time") or row.get("timestamp")
        rate = row.get("fundingRate") if row.get("fundingRate") is not None else row.get("rate")
        try:
            ts_i, rate_f = int(ts), float(rate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(rate_f):
            out[ts_i] = {"ts": ts_i, "rate": rate_f}
    return [out[key] for key in sorted(out)]


def daily_rows(symbol: str) -> list[dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for row in api_rows(KLINE_API, {"symbol": symbol, "interval": "1d", "limit": 1000}):
        try:
            if isinstance(row, Mapping):
                ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
                close = float(row["close"])
            else:
                ts, close = int(row[0]), float(row[4])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if math.isfinite(close):
            out[ts] = {"ts": ts, "close": close}
    return [out[key] for key in sorted(out)]


def audit_oi(rows: list[dict[str, Any]], symbol: str, required_span_ms: int) -> dict[str, Any]:
    errors: list[str] = []
    collected: list[int] = []
    source: list[int] = []
    payload_hashes: set[str] = set()
    repeated_payload_hashes = 0
    for index, row in enumerate(rows):
        prefix = f"row_{index}"
        values = row.get("values") if isinstance(row.get("values"), Mapping) else {}
        try:
            collected.append(int(row["collected_at_ms"]))
            source.append(int(row["source_timestamp_ms"]))
            oi = float(values["openInterest"])
            if not math.isfinite(oi) or oi <= 0:
                errors.append(prefix + ":OPEN_INTEREST_INVALID")
        except (KeyError, TypeError, ValueError):
            errors.append(prefix + ":REQUIRED_VALUE_INVALID")
            continue
        expected = {
            "schema_version": "zel.p3.prospective_native_feature_record.v1",
            "feature": "open_interest",
            "symbol": symbol,
            "source_endpoint": "/openApi/swap/v2/quote/openInterest",
            "prospective_only": True,
            "historical_coverage_claim": False,
            "signal_generation_enabled": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
        for key, wanted in expected.items():
            if row.get(key) != wanted:
                errors.append(f"{prefix}:{key.upper()}_MISMATCH")
        digest = str(row.get("source_payload_sha256") or "")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            errors.append(prefix + ":PAYLOAD_SHA_INVALID")
        if digest in payload_hashes:
            # A native value may remain unchanged at a later valid source timestamp.
            # Timestamp duplication is blocked separately; equal payloads are diagnostic.
            repeated_payload_hashes += 1
        payload_hashes.add(digest)
    if not rows:
        errors.append("EMPTY")
    if any(b <= a for a, b in zip(collected, collected[1:])):
        errors.append("COLLECTED_AT_NOT_STRICTLY_INCREASING")
    if any(b <= a for a, b in zip(source, source[1:])):
        errors.append("SOURCE_TS_NOT_STRICTLY_INCREASING")
    collected_span = collected[-1] - collected[0] if len(collected) > 1 else 0
    source_span = source[-1] - source[0] if len(source) > 1 else 0
    return {
        "symbol": symbol,
        "records": len(rows),
        "collected_first_ms": collected[0] if collected else None,
        "collected_last_ms": collected[-1] if collected else None,
        "collected_span_ms": collected_span,
        "source_first_ms": source[0] if source else None,
        "source_last_ms": source[-1] if source else None,
        "source_span_ms": source_span,
        "repeated_payload_hash_count": repeated_payload_hashes,
        "coverage_progress_ratio": min(1.0, collected_span / required_span_ms) if required_span_ms else 0.0,
        "remaining_span_ms": max(0, required_span_ms - collected_span),
        "duration_gate_pass": collected_span >= required_span_ms,
        "integrity_pass": not errors,
        "errors": sorted(set(errors)),
    }


def audit_market_history(funding: list[dict[str, float]], bars: list[dict[str, float]], oi: Mapping[str, Any]) -> dict[str, Any]:
    first = oi.get("source_first_ms")
    last = oi.get("source_last_ms")
    fts = [int(row["ts"]) for row in funding]
    bts = [int(row["ts"]) for row in bars]
    funding_integrity = bool(fts) and all(b > a for a, b in zip(fts, fts[1:]))
    bars_integrity = bool(bts) and all(b > a for a, b in zip(bts, bts[1:]))
    funding_covers_left = bool(fts and first is not None and fts[0] <= int(first))
    bars_cover = bool(
        bts and first is not None and last is not None
        and bts[0] <= int(first)
        and bts[-1] >= int(last) - DAY_MS
    )
    return {
        "funding_rows": len(fts),
        "funding_first_ms": fts[0] if fts else None,
        "funding_last_ms": fts[-1] if fts else None,
        "funding_span_ms": fts[-1] - fts[0] if len(fts) > 1 else 0,
        "funding_integrity_pass": funding_integrity,
        "funding_attachable_to_oi_pass": funding_covers_left,
        "ohlcv_daily_rows": len(bts),
        "ohlcv_first_ms": bts[0] if bts else None,
        "ohlcv_last_ms": bts[-1] if bts else None,
        "ohlcv_integrity_pass": bars_integrity,
        "ohlcv_covers_oi_window_pass": bars_cover,
        "ready": funding_integrity and funding_covers_left and bars_integrity and bars_cover,
    }


def run(contract: Mapping[str, Any], fixture_dir: Path | None = None) -> dict[str, Any]:
    gate = contract["source_gate"]
    branch = str(gate["data_branch"])
    required = int(gate["required_open_interest_capture_span_ms"])
    coverage_text = (
        (fixture_dir / "latest_coverage.json").read_text(encoding="utf-8")
        if fixture_dir else get_text(f"{RAW}/{branch}/{gate['coverage_path']}")
    )
    coverage = json.loads(coverage_text)
    streams: dict[str, Any] = {}
    histories: dict[str, Any] = {}
    for symbol in gate["symbols"]:
        filename = str(gate["open_interest_paths"][symbol])
        text = (
            (fixture_dir / Path(filename).name).read_text(encoding="utf-8")
            if fixture_dir else get_text(f"{RAW}/{branch}/{filename}")
        )
        oi = audit_oi(parse_ndjson(text), symbol, required)
        streams[symbol] = oi
        if fixture_dir:
            funding = json.loads((fixture_dir / f"funding__{symbol.replace('-', '')}.json").read_text())
            bars = json.loads((fixture_dir / f"ohlcv__{symbol.replace('-', '')}.json").read_text())
        else:
            funding, bars = funding_rows(symbol), daily_rows(symbol)
        histories[symbol] = audit_market_history(funding, bars, oi)
    integrity_errors = []
    for symbol, row in streams.items():
        integrity_errors.extend(f"{symbol}:{error}" for error in row["errors"])
    coverage_contract_ok = (
        coverage.get("schema_version") == "zel.p3.prospective_native_coverage.v1"
        and int(coverage.get("required_capture_span_ms") or -1) == required
        and coverage.get("historical_coverage_claim") is False
        and coverage.get("selection_authority") is False
        and coverage.get("promotion_authority") is False
        and coverage.get("execution_authority") == "NONE"
        and coverage.get("order_authority") == "BLOCKED"
    )
    if not coverage_contract_ok:
        integrity_errors.append("P3_COVERAGE_CONTRACT_MISMATCH")
    source_integrity_pass = not integrity_errors and all(row["integrity_pass"] for row in streams.values())
    oi_duration_ready = all(row["duration_gate_pass"] for row in streams.values())
    market_history_ready = all(row["ready"] for row in histories.values())
    ready = source_integrity_pass and oi_duration_ready and market_history_ready
    if ready:
        state = "PASS_WRSR_SOURCE_HISTORY_READY_FOR_PREREG_EVALUATOR_FREEZE"
        next_action = "FREEZE_WRSR_EXECUTABLE_SPEC_AND_DEVELOPMENT_EVALUATOR"
    elif not source_integrity_pass or not market_history_ready:
        state = "HOLD_WRSR_SOURCE_INTEGRITY"
        next_action = "REPAIR_SINGLE_SOURCE_INTEGRITY_CAUSE"
    else:
        state = "HOLD_SOURCE_HISTORY"
        next_action = "CONTINUE_EXISTING_APPEND_ONLY_OI_COLLECTOR"
    min_progress = min(row["coverage_progress_ratio"] for row in streams.values())
    max_remaining = max(row["remaining_span_ms"] for row in streams.values())
    result = {
        "schema_version": "zel.a1_wrsr_new_002_source_history_audit.v1",
        "state": state,
        "candidate_id": contract["candidate_id"],
        "candidate_sha256": contract["candidate_sha256"],
        "contract_sha256": hashlib.sha256(canonical(contract).encode()).hexdigest(),
        "source_branch": branch,
        "p3_coverage_receipt": coverage.get("receipt_sha256"),
        "required_open_interest_capture_span_ms": required,
        "oi_coverage_progress_ratio": min_progress,
        "remaining_span_ms": max_remaining,
        "remaining_days": max_remaining / DAY_MS,
        "source_integrity_pass": source_integrity_pass,
        "open_interest_duration_ready": oi_duration_ready,
        "funding_and_ohlcv_ready": market_history_ready,
        "history_ready": ready,
        "streams": streams,
        "market_history": histories,
        "integrity_errors": sorted(set(integrity_errors)),
        "collector_action": "REUSE_ACTIVE_P3_APPEND_ONLY_COLLECTOR",
        "new_collector_installed": False,
        "fresh_boundary_created": False,
        "development_replay_started": False,
        "next_permitted_action": next_action,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def self_test() -> int:
    required = 21 * DAY_MS
    def oi_rows(symbol: str, count: int) -> list[dict[str, Any]]:
        out = []
        for index in range(count):
            ts = 1_700_000_000_000 + index * 3_600_000
            out.append({
                "schema_version": "zel.p3.prospective_native_feature_record.v1",
                "collected_at_ms": ts,
                "source_timestamp_ms": ts,
                "source_payload_sha256": hashlib.sha256(f"{symbol}:{index}".encode()).hexdigest(),
                "feature": "open_interest", "symbol": symbol,
                "source_endpoint": "/openApi/swap/v2/quote/openInterest",
                "prospective_only": True, "historical_coverage_claim": False,
                "signal_generation_enabled": False, "selection_authority": False,
                "promotion_authority": False, "execution_authority": "NONE",
                "order_authority": "BLOCKED", "values": {"openInterest": str(1000 + index)},
            })
        return out
    good = audit_oi(oi_rows("BTC-USDT", 22 * 24 + 1), "BTC-USDT", required)
    short = audit_oi(oi_rows("BTC-USDT", 10 * 24 + 1), "BTC-USDT", required)
    assert good["duration_gate_pass"] and good["integrity_pass"]
    assert not short["duration_gate_pass"] and short["integrity_pass"]
    duplicate = oi_rows("BTC-USDT", 3)
    duplicate[2]["source_timestamp_ms"] = duplicate[1]["source_timestamp_ms"]
    assert not audit_oi(duplicate, "BTC-USDT", required)["integrity_pass"]
    print("PASS_A1_WRSR_NEW_002_SOURCE_HISTORY_AUDIT_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=Path("backend/research/contracts/a1_wrsr_new_002_source_contract_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("out/a1_wrsr_new_002_source_history_audit_v1.json"))
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = run(contract, args.fixture_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "state", "history_ready", "source_integrity_pass", "open_interest_duration_ready",
        "funding_and_ohlcv_ready", "oi_coverage_progress_ratio", "remaining_days",
        "next_permitted_action", "receipt_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
