"""Non-order canonical source capture and availability-gated candidate references.

Current snapshots are isolated SOURCE_READINESS_ONLY, never retrospective fills or
formal evidence. Existing V2/forward observer files and schedules are not mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import fcntl
import json
import os
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://open-api.bingx.com"
ENDPOINTS = {
    "depth": "/openApi/swap/v2/quote/depth",
    "ohlcv4h": "/openApi/swap/v3/quote/klines",
    "funding": "/openApi/swap/v2/quote/fundingRate",
    "contracts": "/openApi/swap/v2/quote/contracts",
}
INTERVAL_MS = 14_400_000
ROOT = Path(__file__).resolve().parents[3]
SELECTION = ROOT / "research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/SELECTION.json"
SOURCE_CONTRACT = ROOT / "backend/research/rebuild/g5_clean_runner_contract_effective_v1.json"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as out:
        json.dump(value, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)


def parse_raw(raw: bytes, *, stream: str, received_at_ms: int) -> dict:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("code") not in (None, 0):
        raise ValueError("SOURCE_API_ERROR")
    data = payload.get("data")
    result = {"stream": stream, "received_at_ms": received_at_ms, "available_at_ms": received_at_ms,
              "source_sha256": hashlib.sha256(raw).hexdigest(), "formal_credit": 0,
              "classification": "SOURCE_READINESS_ONLY", "dev_use_forbidden": True,
              "exchange_event_ts_ms": None, "last_cursor": None, "missing_intervals": [],
              "duplicate_rows": 0, "state": "SNAPSHOT_ONLY"}
    if stream == "ohlcv4h":
        if not isinstance(data, list):
            raise ValueError("OHLCV_LIST_REQUIRED")
        unique = {}
        for row in data:
            stamp = int(row["time"] if isinstance(row, dict) else row[0])
            if stamp in unique:
                if unique[stamp] != row:
                    raise ValueError("CONFLICTING_SOURCE_DUPLICATE")
                result["duplicate_rows"] += 1
            unique[stamp] = row
        # Only completed exchange bars. Late receipt never retroactively makes a
        # historical close available at close time.
        closed = sorted(t for t in unique if t + INTERVAL_MS <= received_at_ms)
        result["rows"] = [unique[t] for t in closed]
        result["incomplete_rows"] = len(unique) - len(closed)
        result["last_cursor"] = closed[-1] + INTERVAL_MS if closed else None
        result["exchange_event_ts_ms"] = result["last_cursor"]
        result["missing_intervals"] = [[a + INTERVAL_MS, b] for a, b in zip(closed, closed[1:]) if b != a + INTERVAL_MS]
        if result["missing_intervals"]:
            result["state"] = "QUARANTINED_MISSING_INTERVAL"
    elif stream == "depth":
        if not isinstance(data, dict) or not data.get("bids") or not data.get("asks"):
            raise ValueError("DEPTH_EMPTY")
        result["rows"] = data
        result["exchange_event_ts_ms"] = data.get("T", data.get("timestamp", data.get("time")))
        result["last_cursor"] = data.get("lastUpdateId")
        result["sequence_continuity"] = "UNPROVEN_POINT_IN_TIME_SNAPSHOT"
    elif stream in ("funding", "contracts"):
        if not isinstance(data, list):
            raise ValueError("LIST_REQUIRED")
        result["rows"] = data  # Preserve signed rates and contract units verbatim.
        if stream == "funding":
            stamps = [int(r["fundingTime"]) for r in data if "fundingTime" in r]
            result["last_cursor"] = max(stamps) if stamps else None
            result["exchange_event_ts_ms"] = result["last_cursor"]
            result["settlement_coverage"] = "UNBOUND_TO_POSITION_INTERVAL"
    else:
        raise ValueError("UNSUPPORTED_STREAM")
    result["parsed_sha256"] = digest(result)
    return result


def ingest(directory: Path, *, stream: str, raw: bytes, uri: str, requested_at_ms: int,
           received_at_ms: int, run_id: str, symbol: str = "UNSPECIFIED") -> dict:
    """Deduplicate canonical raw bytes; candidates reference one saved source."""
    source_sha = hashlib.sha256(raw).hexdigest()
    target = directory / "raw" / (source_sha + ".json")
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("RAW_DIGEST_COLLISION")
    parsed = parse_raw(raw, stream=stream, received_at_ms=received_at_ms)
    if received_at_ms < requested_at_ms:
        raise ValueError("RECEIPT_CLOCK_REVERSED")
    state_path = directory / "cursor.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"streams": {}, "seen_sources": []}
    stream_key = stream + ":" + symbol
    canonical_identity = stream_key + ":" + source_sha
    if canonical_identity in state["seen_sources"]:
        return {"state": "REUSED_STORED_SOURCE", "source_sha256": source_sha, "raw_uri": str(target), "network_requests": 0}
    previous = state["streams"].get(stream_key)
    if previous and stream == "ohlcv4h":
        cursor = previous.get("last_cursor")
        first = min((int(r["time"] if isinstance(r, dict) else r[0]) for r in parsed["rows"]), default=None)
        if cursor is not None and first is not None and first > cursor:
            parsed["state"] = "QUARANTINED_RESTART_GAP"
            parsed["missing_intervals"].append([cursor, first])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") if not target.exists() else target.open("rb") as f:
        if f.writable():
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    receipt = {"stream": stream, "symbol": symbol, "uri": uri, "raw_uri": str(target), "source_sha256": source_sha,
               "requested_at_ms": requested_at_ms, "received_at_ms": received_at_ms,
               "run_id": run_id, "owner": "STEP7_S3", "host": socket.gethostname(),
               "formal_credit": 0, "dev_use_forbidden": True,
               "parsed": parsed, "online_offline_parse_equal": parse_raw(target.read_bytes(), stream=stream, received_at_ms=received_at_ms) == parse_raw(raw, stream=stream, received_at_ms=received_at_ms)}
    parsed["parsed_sha256"] = digest({k: v for k, v in parsed.items() if k != "parsed_sha256"})
    save(directory / "receipts" / (digest(canonical_identity) + ".json"), receipt)
    next_cursor = parsed["last_cursor"]
    if previous and previous.get("last_cursor") is not None and next_cursor is not None and next_cursor < previous["last_cursor"]:
        next_cursor = previous["last_cursor"]
    state["streams"][stream_key] = {"last_cursor": next_cursor, "source_sha256": source_sha, "state": parsed["state"], "received_at_ms": received_at_ms}
    state["seen_sources"].append(canonical_identity)
    save(state_path, state)
    return receipt


def candidate_reference(source: dict, *, candidate_id: str, decision_at_ms: int,
                        trigger_stream: str | None, required_stream: str,
                        stale_ms: int | None, stale_authority: str | None) -> dict:
    """Availability connector only: never manufactures a strategy signal/fill."""
    blockers = []
    if required_stream == "conditional_sl" and trigger_stream not in {"LAST", "MARK", "INDEX"}:
        blockers.append("TRIGGER_STREAM_UNBOUND")
    if source.get("available_at_ms", decision_at_ms + 1) > decision_at_ms:
        blockers.append("SOURCE_UNAVAILABLE_AT_DECISION")
    if stale_ms is None or not stale_authority:
        blockers.append("SOURCE_SPECIFIC_STALE_AUTHORITY_UNBOUND")
    elif decision_at_ms - source["available_at_ms"] > stale_ms:
        blockers.append("SOURCE_STALE")
    if source.get("state", "").startswith("QUARANTINED"):
        blockers.append("SOURCE_INTERVAL_QUARANTINED")
    if required_stream == "conditional_sl" and source.get("trigger_stream") != trigger_stream:
        blockers.append("TRIGGER_STREAM_MISMATCH")
    return {"candidate_id": candidate_id, "source_sha256": source.get("source_sha256"),
            "decision_at_ms": decision_at_ms, "state": "BLOCKED" if blockers else "REFERENCE_READY",
            "blockers": blockers, "formal_credit": 0, "actual_fill": False,
            "order_authority": False, "candidate_signal_evaluated": False}


def completed_exit_reference(*, decision_bar_close_ms: int, decision_available_at_ms: int,
                             decision_at_ms: int, open_event_at_ms: int,
                             open_received_at_ms: int, source_sha256: str) -> dict:
    """Preserve native next-open timing; late discovery cannot backdate a fill."""
    blockers = []
    if decision_available_at_ms < decision_bar_close_ms or decision_at_ms < decision_available_at_ms:
        blockers.append("DECISION_BAR_NOT_AVAILABLE")
    if open_event_at_ms < decision_at_ms or open_received_at_ms < open_event_at_ms:
        blockers.append("OPEN_NOT_CAUSALLY_AVAILABLE")
    if open_event_at_ms != decision_bar_close_ms:
        blockers.append("NATIVE_NEXT_OPEN_TIME_MISMATCH")
    return {"state": "BLOCKED" if blockers else "TIMING_REFERENCE_READY", "blockers": blockers,
            "source_sha256": source_sha256, "decision_at_ms": decision_at_ms,
            "open_event_at_ms": open_event_at_ms, "open_received_at_ms": open_received_at_ms,
            "formal_credit": 0, "actual_fill": False, "fee_or_funding_charged": False}


def source_manifest(selection: dict, source_contract: dict) -> dict:
    declared = selection.get("symbols")
    source_lists = [v["symbols"] for v in source_contract.values() if isinstance(v, dict) and "symbols" in v]
    if selection.get("candidate") != "KR3" or not isinstance(declared, list) or len(declared) != 7 or len(set(declared)) != 7:
        raise ValueError("SELECTED_KR3_SEVEN_SYMBOL_IDENTITY_REQUIRED")
    if not any(declared == xs for xs in source_lists):
        raise ValueError("SOURCE_UNIVERSE_SELECTION_MISMATCH")
    return {"symbols": declared, "selection_sha256": digest(selection), "source_contract_sha256": digest(source_contract),
            "requests_max": 3 * len(declared) + 1, "source_bundle_max": 1,
            "formal_credit": 0, "strategy_parity": "NOT_READY", "independence": "UNKNOWN_PREBOUNDARY_FORMAL_ZERO"}


def _capture(directory: Path, run_id: str) -> dict:
    """One finite public bundle; no automatic retry, scheduler, or paid API."""
    attempt_path = directory / "ATTEMPT.json"
    if attempt_path.exists():
        return json.loads(attempt_path.read_text())
    manifest = source_manifest(json.loads(SELECTION.read_text()), json.loads(SOURCE_CONTRACT.read_text()))
    save(directory / "MANIFEST.json", manifest)
    attempt = {"manifest": manifest, "schema_version": "zel.step7.source_bundle.v1", "run_id": run_id, "owner": "STEP7_S3", "host": socket.gethostname(),
               "started_at_ms": time.time_ns() // 1_000_000, "state": "STARTED",
               "requests": [], "formal_credit": 0, "market_symbols": manifest["symbols"], "coverage": "SEVEN_SYMBOL_SNAPSHOT_SEED_AND_STRATEGY_PARITY_NOT_READY", "requested_warmup_bars": 240, "independence": "UNKNOWN_PREBOUNDARY_FORMAL_ZERO", "retention_days": 90, "dev_use_forbidden": True,
               "process_continues_after_return": False, "existing_observers_modified": False}
    save(attempt_path, attempt)
    requests = [(stream, symbol) for symbol in manifest["symbols"] for stream in ("depth", "ohlcv4h", "funding")] + [("contracts", "ALL")]
    for stream, symbol in requests:
        endpoint = ENDPOINTS[stream]
        params = {} if stream == "contracts" else {"symbol": symbol}
        if stream == "depth": params["limit"] = 5
        if stream == "ohlcv4h": params.update(interval="4h", limit=240)
        if stream == "funding": params["limit"] = 3
        uri = BASE + endpoint + "?" + urllib.parse.urlencode(params)
        start = time.time_ns() // 1_000_000
        request = {"stream": stream, "symbol": symbol, "uri": uri, "requested_at_ms": start, "state": "REQUESTED"}
        attempt["requests"].append(request)
        save(attempt_path, attempt)
        try:
            with urllib.request.urlopen(urllib.request.Request(uri, headers={"User-Agent": "zel-step7-source-readiness-v1"}), timeout=8) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000: raise ValueError("SOURCE_RESPONSE_SIZE_LIMIT")
            received = time.time_ns() // 1_000_000
            raw_path = directory / "raw_http" / (stream + ("" if symbol == "UNSPECIFIED" else "_" + symbol) + ".bin")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw)
            request.update(raw_uri=str(raw_path), raw_sha256=hashlib.sha256(raw).hexdigest(), received_at_ms=received)
            save(attempt_path, attempt)
            receipt = ingest(directory, stream=stream, raw=raw, uri=uri, requested_at_ms=start, received_at_ms=received, run_id=run_id, symbol=symbol)
            request.update(state="STORED", received_at_ms=received, source_sha256=receipt["source_sha256"])
        except Exception as error:
            request.update(state="BLOCKED", failed_at_ms=time.time_ns() // 1_000_000,
                           error_type=type(error).__name__, error=str(error)[:300])
            attempt["state"] = "SOURCE_RUNTIME_BLOCKED"
            save(attempt_path, attempt)
            return attempt
        save(attempt_path, attempt)
    attempt["state"] = "SOURCE_SNAPSHOT_STORED_NOT_FORMAL"
    save(attempt_path, attempt)
    return attempt


def capture(directory: Path, run_id: str, budget: int = 1) -> dict:
    if budget != 1:
        raise ValueError("EXACT_ONE_BUNDLE_BUDGET_REQUIRED")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "capture.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _capture(directory, run_id)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--budget", type=int, default=1)
    args = p.parse_args()
    r = capture(args.out_dir, args.run_id, args.budget)
    print(json.dumps({"state": r["state"], "run_id": r["run_id"], "request_count": len(r["requests"]), "formal_credit": 0}))
