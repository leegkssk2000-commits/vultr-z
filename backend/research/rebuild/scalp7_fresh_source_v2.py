"""Public closed 1m source capture for Scalp7; no signals, trades, or orders.

Each response is saved before normalization. Missing minutes stay absent.
Frozen identity and receipt cursors permit restart without downloading completed
windows. Failures are separate immutable attempts; completed data never changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from backend.research.rebuild.economic7_canonical_history_v1 import (
    Fetch,
    atomic_json,
    csv_gzip,
    immutable_bytes,
    json_bytes,
    normalize_row,
    public_fetch,
    request_windows,
)
from backend.research.rebuild.scalp7_source_data_v2 import (
    MINUTE_MS,
    SOURCE,
    SYMBOLS,
    SourceDataError,
    sha_file,
)


def normalize_closed(
    raw: bytes, start_ms: int, end_ms: int, received_at_ms: int
) -> tuple[list[dict[str, Any]], list[int]]:
    payload = json.loads(raw)
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise SourceDataError("FRESH_SOURCE_RESPONSE_REJECTED")
    rows = [normalize_row(row) for row in payload["data"]]
    rows.sort(key=lambda row: row["timestamp_ms"])
    timestamps = [row["timestamp_ms"] for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise SourceDataError("FRESH_DUPLICATE_TIMESTAMP")
    if any(
        not start_ms <= ts < end_ms or ts + MINUTE_MS > received_at_ms
        for ts in timestamps
    ):
        raise SourceDataError("FRESH_OUTSIDE_REQUEST_OR_UNCLOSED")
    missing = sorted(set(range(start_ms, end_ms, MINUTE_MS)) - set(timestamps))
    return rows, missing


def _receipt_frame(out: Path, receipt: dict[str, Any]) -> pd.DataFrame:
    query = receipt.get("query", {})
    if (
        receipt.get("source") != SOURCE
        or receipt.get("http_status") != 200
        or receipt.get("url", "").split("?")[0] != SOURCE
        or receipt.get("symbol") not in SYMBOLS
        or query.get("symbol") != receipt["symbol"]
        or query.get("interval") != "1m"
        or query.get("timeZone") != 0
        or query.get("startTime") != receipt["start_ms"]
        or query.get("endTime") != receipt["end_exclusive_ms"] - 1
        or receipt["start_ms"] % MINUTE_MS
        or receipt["end_exclusive_ms"] % MINUTE_MS
        or receipt["start_ms"] >= receipt["end_exclusive_ms"]
        or receipt["received_at_ms"] < receipt["end_exclusive_ms"]
    ):
        raise SourceDataError("FRESH_RECEIPT_SOURCE_IDENTITY")
    body_path = (out / receipt["body_path"]).resolve()
    normalized_path = (out / receipt["normalized_path"]).resolve()
    if not body_path.is_relative_to(
        out.resolve()
    ) or not normalized_path.is_relative_to(out.resolve()):
        raise SourceDataError("FRESH_RECEIPT_PATH_OUTSIDE_ROOT")
    if sha_file(body_path) != receipt["body_sha256"]:
        raise SourceDataError("FRESH_RAW_HASH_MISMATCH")
    rows, missing = normalize_closed(
        body_path.read_bytes(),
        receipt["start_ms"],
        receipt["end_exclusive_ms"],
        receipt["received_at_ms"],
    )
    normalized = out / receipt["normalized_path"]
    if sha_file(normalized) != receipt[
        "normalized_sha256"
    ] or normalized.read_bytes() != csv_gzip(rows):
        raise SourceDataError("FRESH_NORMALIZED_RAW_MISMATCH")
    if missing != receipt["missing_minutes"]:
        raise SourceDataError("FRESH_GAP_RECEIPT_MISMATCH")
    frame = pd.read_csv(normalized, float_precision="round_trip")
    frame["received_at_ms"] = receipt["received_at_ms"]
    return frame


def collect_once(
    out: str | Path,
    *,
    symbols: Sequence[str] = SYMBOLS,
    start_ms: int | None = None,
    end_ms: int | None = None,
    fetch: Fetch = public_fetch,
) -> dict[str, Any]:
    """Append only newly closed source windows; hold an exclusive writer lock."""
    import fcntl

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "collection.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SourceDataError("FRESH_SOURCE_OWNER_ALREADY_RUNNING") from exc
        return _collect_locked(out, symbols, start_ms, end_ms, fetch)


def _collect_locked(
    out: Path,
    symbols: Sequence[str],
    start_ms: int | None,
    end_ms: int | None,
    fetch: Fetch,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    closed_end = now_ms // MINUTE_MS * MINUTE_MS
    ending = closed_end if end_ms is None else end_ms
    if ending > closed_end or ending % MINUTE_MS:
        raise SourceDataError("FRESH_REQUEST_UNCLOSED_END")
    if (
        not symbols
        or len(symbols) != len(set(symbols))
        or any(s not in SYMBOLS for s in symbols)
    ):
        raise SourceDataError("FRESH_SYMBOL_IDENTITY")
    identity_path = out / "IDENTITY.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_bytes())
        if (
            identity["source"] != SOURCE
            or identity["symbols"] != list(symbols)
            or identity["module_sha256"] != sha_file(Path(__file__))
            or (start_ms is not None and identity["start_ms"] != start_ms)
        ):
            raise SourceDataError("FRESH_IDENTITY_CHANGED")
    else:
        beginning = closed_end - MINUTE_MS if start_ms is None else start_ms
        if beginning % MINUTE_MS or beginning >= ending or beginning < 0:
            raise SourceDataError("FRESH_INVALID_START")
        identity = {
            "schema": "scalp7.fresh_source.v2",
            "source": SOURCE,
            "interval": "1m",
            "timeZone": 0,
            "symbols": list(symbols),
            "start_ms": beginning,
            "frozen_at_ms": now_ms,
            "module_sha256": sha_file(Path(__file__)),
            "volume_units": "UNKNOWN",
            "order_authority": "BLOCKED",
            "synthetic_fill": False,
            "fresh_trade_credit": "ONLY_STRATEGY_DECISIONS_AFTER_SEPARATE_RULE_FREEZE",
        }
        immutable_bytes(identity_path, json_bytes(identity))
    state_path = out / "CURSOR.json"
    state = (
        json.loads(state_path.read_bytes())
        if state_path.exists()
        else {"identity_sha256": sha_file(identity_path), "symbols": {}}
    )
    if state["identity_sha256"] != sha_file(identity_path):
        raise SourceDataError("FRESH_CURSOR_IDENTITY_CHANGED")
    requested = 0
    for symbol in symbols:
        records = state["symbols"].setdefault(symbol, [])
        beginning = identity["start_ms"]
        for record in records:
            receipt_path = out / record["path"]
            if sha_file(receipt_path) != record["sha256"]:
                raise SourceDataError("FRESH_CURSOR_RECEIPT_HASH")
            receipt = json.loads(receipt_path.read_bytes())
            if receipt["symbol"] != symbol or receipt["start_ms"] != beginning:
                raise SourceDataError("FRESH_CURSOR_DISCONTINUITY")
            _receipt_frame(out, receipt)
            beginning = receipt["end_exclusive_ms"]
        for first, last in request_windows(beginning, ending):
            stamp = time.time_ns()
            stem = f"requests/{symbol}/{first}_{last}_{stamp}"
            query = {
                "symbol": symbol,
                "interval": "1m",
                "timeZone": 0,
                "startTime": first,
                "endTime": last - 1,
                "limit": 1000,
                "timestamp": int(time.time() * 1000),
            }
            url = SOURCE + "?" + urllib.parse.urlencode(query)
            status, raw = fetch(url)
            received = int(time.time() * 1000)
            body_path = stem + ".body"
            immutable_bytes(out / body_path, raw)
            raw_receipt = {
                "source": SOURCE,
                "query": query,
                "url": url,
                "symbol": symbol,
                "start_ms": first,
                "end_exclusive_ms": last,
                "requested_at_ms": query["timestamp"],
                "received_at_ms": received,
                "body_path": body_path,
                "body_sha256": hashlib.sha256(raw).hexdigest(),
                "http_status": status,
            }
            immutable_bytes(out / (stem + ".http.json"), json_bytes(raw_receipt))
            requested += 1
            if status != 200:
                raise SourceDataError(f"FRESH_HTTP_STATUS:{status}")
            rows, missing = normalize_closed(raw, first, last, received)
            normalized_path = stem + ".csv.gz"
            data = csv_gzip(rows)
            immutable_bytes(out / normalized_path, data)
            receipt = {
                **raw_receipt,
                "normalized_path": normalized_path,
                "normalized_sha256": hashlib.sha256(data).hexdigest(),
                "rows": len(rows),
                "missing_minutes": missing,
                "state": "GAP_PRESERVED" if missing else "COMPLETE",
                "volume_units": "UNKNOWN",
                "synthetic_fill": False,
            }
            receipt_path = stem + ".receipt.json"
            immutable_bytes(out / receipt_path, json_bytes(receipt))
            records.append(
                {"path": receipt_path, "sha256": sha_file(out / receipt_path)}
            )
            atomic_json(state_path, state)
    return {
        "state": "SOURCE_COLLECTION_COMPLETE_WITH_EXPLICIT_GAPS",
        "new_requests": requested,
        "end_exclusive_ms": ending,
        "symbols": list(symbols),
        "order_authority": "BLOCKED",
    }


def load_observed_minutes(out: str | Path) -> dict[str, pd.DataFrame]:
    """Read the atomically committed cursor; uncommitted attempts are not input."""
    out = Path(out)
    state = json.loads((out / "CURSOR.json").read_bytes())
    identity = json.loads((out / "IDENTITY.json").read_bytes())
    if (
        identity.get("source") != SOURCE
        or identity.get("interval") != "1m"
        or identity.get("timeZone") != 0
    ):
        raise SourceDataError("FRESH_SOURCE_IDENTITY")
    if state["identity_sha256"] != sha_file(out / "IDENTITY.json"):
        raise SourceDataError("FRESH_CURSOR_IDENTITY_CHANGED")
    output = {}
    for symbol, records in state["symbols"].items():
        if symbol not in identity["symbols"] or symbol not in SYMBOLS:
            raise SourceDataError("FRESH_CURSOR_SYMBOL_IDENTITY")
        beginning = identity["start_ms"]
        frames = []
        for record in records:
            path = out / record["path"]
            if sha_file(path) != record["sha256"]:
                raise SourceDataError("FRESH_CURSOR_RECEIPT_HASH")
            receipt = json.loads(path.read_bytes())
            if receipt["symbol"] != symbol or receipt["start_ms"] != beginning:
                raise SourceDataError("FRESH_CURSOR_SYMBOL_OR_WINDOW_MISMATCH")
            frames.append(_receipt_frame(out, receipt))
            beginning = receipt["end_exclusive_ms"]
        if frames:
            output[symbol] = pd.concat(frames, ignore_index=True)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--max-seconds", type=float, default=0)
    args = parser.parse_args(argv)
    started = time.monotonic()
    while True:
        result = collect_once(args.out, start_ms=args.start_ms)
        print(
            json.dumps({"at": datetime.now(timezone.utc).isoformat(), **result}),
            flush=True,
        )
        if args.max_seconds and time.monotonic() - started >= args.max_seconds:
            return 0
        time.sleep(min(10, 60 - time.time() % 60))


if __name__ == "__main__":
    raise SystemExit(main())
