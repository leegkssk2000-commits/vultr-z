"""Single-owner, incrementally verified Scalp7 public 1m receipts.

The frozen v2 API, normalizer and source identity stay byte-identical. Every
new receipt is fully checked with v2._receipt_frame. An established immutable
cursor prefix is bound by its exact pointer-list SHA on EVERY iteration, while
periodic full-receipt audits remain a SEPARATE obligation. An old receipt body
not modified in CURSOR can only be found by that separate full audit.

No order, trade, Paper/Live, historical filling, or new market endpoint.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from backend.research.rebuild import scalp7_fresh_source_v2 as v2
from backend.research.rebuild.scalp7_source_data_v2 import (
    MINUTE_MS,
    SOURCE,
    SYMBOLS,
    SourceDataError,
    sha_file,
)

CHECKPOINT = "INCREMENTAL_V2_PREFIX_CHECKPOINT.json"
EXPECTED_V2_SHA = "08ef678e679aefdd1235aad3a120d88915b8865446ff099b67a34dcbf5c03691"


def prefix_sha(records: list[dict[str, str]]) -> str:
    return hashlib.sha256(v2.json_bytes(records)).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise SourceDataError("INCREMENTAL_PATH_ESCAPE")
    return path


def verify_receipt(
    out: Path, pointer: dict[str, str], sym: str, expected_start: int
) -> int:
    path = safe_path(out, pointer["path"])
    if sha_file(path) != pointer["sha256"]:
        raise SourceDataError("INCREMENTAL_RECEIPT_SHA_CHANGED:" + sym)
    r = json.loads(path.read_bytes())
    if r.get("symbol") != sym or r.get("start_ms") != expected_start:
        raise SourceDataError("INCREMENTAL_WINDOW_DISCONTINUITY:" + sym)
    v2._receipt_frame(out, r)
    return int(r["end_exclusive_ms"])


def checkpoint_for(
    out: Path,
    symbols: Sequence[str],
    *,
    bootstrap_prior_v2: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Pin historical v2-captured cursor once; replay unseen suffix exactly."""
    identity_raw = (out / "IDENTITY.json").read_bytes()
    identity = json.loads(identity_raw)
    identity_sha = hashlib.sha256(identity_raw).hexdigest()
    if (
        sha_file(Path(v2.__file__)) != EXPECTED_V2_SHA
        or identity.get("module_sha256") != EXPECTED_V2_SHA
        or identity.get("source") != SOURCE
        or identity.get("interval") != "1m"
        or identity.get("volume_units") != "UNKNOWN"
        or identity.get("synthetic_fill") is not False
        or identity.get("symbols") != list(symbols)
        or identity.get("order_authority") != "BLOCKED"
    ):
        raise SourceDataError("INCREMENTAL_FROZEN_V2_SOURCE_MISMATCH")
    cursor = json.loads((out / "CURSOR.json").read_bytes())
    if cursor["identity_sha256"] != identity_sha:
        raise SourceDataError("INCREMENTAL_CURSOR_IDENTITY_MISMATCH")
    cp_path = out / CHECKPOINT
    if not cp_path.exists():
        if not bootstrap_prior_v2:
            raise SourceDataError("INCREMENTAL_REQUIRES_PRIOR_V2_CHECKPOINT")
        # The original v2 writer must have completed its last FULL audit and
        # stopped first. A peer must never bootstrap over a running v2 writer.
        state: dict[str, Any] = {
            "schema": "zel.scalp7.v2.incremental_prefix.v1",
            "identity_sha256": identity_sha,
            "frozen_v2_module_sha256": EXPECTED_V2_SHA,
            "prefix_basis": "PRIOR_COMPLETED_V2_FULL_AUDIT_WRITER_STOPPED",
            "full_historical_audit_every_iteration": False,
            "historical_body_tamper_detection": "SEPARATE_FULL_AUDIT_REQUIRED",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbols": {},
        }
        for sym in symbols:
            records = cursor["symbols"][sym]
            if not records:
                raise SourceDataError("INCREMENTAL_EMPTY_PRIOR_V2_CURSOR:" + sym)
            initial = int(identity["start_ms"])
            # Anchor endpoints and source hashes; full prefix was verified by
            # the prior native v2 process before this explicit cutover.
            first_path = safe_path(out, records[0]["path"])
            first = json.loads(first_path.read_bytes())
            if (
                sha_file(first_path) != records[0]["sha256"]
                or first["start_ms"] != initial
            ):
                raise SourceDataError("INCREMENTAL_BAD_PREFIX_FIRST:" + sym)
            if len(records) > 1:
                prev_path = safe_path(out, records[-2]["path"])
                last_path = safe_path(out, records[-1]["path"])
                prev = json.loads(prev_path.read_bytes())
                last = json.loads(last_path.read_bytes())
                if (
                    sha_file(prev_path) != records[-2]["sha256"]
                    or sha_file(last_path) != records[-1]["sha256"]
                    or prev["end_exclusive_ms"] != last["start_ms"]
                ):
                    raise SourceDataError("INCREMENTAL_BAD_PREFIX_TAIL:" + sym)
            end = verify_receipt(
                out,
                records[-1],
                sym,
                int(
                    json.loads(safe_path(out, records[-1]["path"]).read_bytes())[
                        "start_ms"
                    ]
                ),
            )
            state["symbols"][sym] = {
                "count": len(records),
                "end_exclusive_ms": end,
                "prefix_sha256": prefix_sha(records),
            }
        v2.atomic_json(cp_path, state)
        return identity, cursor, state
    cp = json.loads(cp_path.read_bytes())
    if (
        cp.get("identity_sha256") != identity_sha
        or cp.get("frozen_v2_module_sha256") != EXPECTED_V2_SHA
        or cp.get("schema") != "zel.scalp7.v2.incremental_prefix.v1"
        or sorted(cp.get("symbols", {})) != sorted(symbols)
    ):
        raise SourceDataError("INCREMENTAL_CHECKPOINT_IDENTITY_CHANGED")
    for sym in symbols:
        records = cursor["symbols"][sym]
        old = cp["symbols"][sym]
        count = int(old["count"])
        if len(records) < count or prefix_sha(records[:count]) != old["prefix_sha256"]:
            raise SourceDataError("INCREMENTAL_HISTORIC_CURSOR_CHANGED:" + sym)
        begin = int(old["end_exclusive_ms"])
        for pointer in records[count:]:
            begin = verify_receipt(out, pointer, sym, begin)
        old.update(
            count=len(records),
            end_exclusive_ms=begin,
            prefix_sha256=prefix_sha(records),
        )
        if records:
            last_path = safe_path(out, records[-1]["path"])
            last = json.loads(last_path.read_bytes())
            if verify_receipt(out, records[-1], sym, int(last["start_ms"])) != begin:
                raise SourceDataError("INCREMENTAL_TAIL_CHANGED:" + sym)
    return identity, cursor, cp


def collect_once(
    out: Path,
    *,
    symbols: Sequence[str] = SYMBOLS,
    start_ms: int | None = None,
    end_ms: int | None = None,
    fetch: v2.Fetch = v2.public_fetch,
    bootstrap_prior_v2: bool = False,
) -> dict[str, Any]:
    """Same original append-only receipt, cursor, request and SHA semantics."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "collection.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SourceDataError("INCREMENTAL_ORIGINAL_WRITER_ACTIVE") from exc
        if not symbols or len(set(symbols)) != len(symbols):
            raise SourceDataError("INCREMENTAL_INVALID_SYMBOL_LIST")
        start_time = time.monotonic()
        identity, cursor, cp = checkpoint_for(
            out, symbols, bootstrap_prior_v2=bootstrap_prior_v2
        )
        if start_ms is not None and int(identity["start_ms"]) != start_ms:
            raise SourceDataError("INCREMENTAL_SOURCE_START_CHANGED")
        now_ms = int(time.time() * 1000)
        closed_end = now_ms // MINUTE_MS * MINUTE_MS
        ending = closed_end if end_ms is None else end_ms
        if ending > closed_end or ending % MINUTE_MS:
            raise SourceDataError("INCREMENTAL_UNCLOSED_REQUEST")
        requested = 0
        for sym in symbols:
            records = cursor["symbols"][sym]
            begin = int(cp["symbols"][sym]["end_exclusive_ms"])
            for first, last in v2.request_windows(begin, ending):
                stem = f"requests/{sym}/{first}_{last}_{time.time_ns()}"
                query = {
                    "symbol": sym,
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
                raw_body_path = stem + ".body"
                v2.immutable_bytes(out / raw_body_path, raw)
                raw_receipt = {
                    "source": SOURCE,
                    "query": query,
                    "url": url,
                    "symbol": sym,
                    "start_ms": first,
                    "end_exclusive_ms": last,
                    "requested_at_ms": query["timestamp"],
                    "received_at_ms": received,
                    "body_path": raw_body_path,
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                    "http_status": status,
                }
                v2.immutable_bytes(
                    out / (stem + ".http.json"), v2.json_bytes(raw_receipt)
                )
                requested += 1
                if status != 200:
                    raise SourceDataError(f"INCREMENTAL_HTTP_STATUS:{status}")
                try:
                    rows, missing = v2.normalize_closed(raw, first, last, received)
                except SourceDataError as exc:
                    # BingX returns HTTP 200 + code 100410 ("try later") under
                    # transient provider pressure. The raw body and HTTP proof
                    # above are already saved immutably; do NOT advance CURSOR.
                    try:
                        response = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise exc
                    if (
                        isinstance(response, dict)
                        and str(response.get("code")) == "100410"
                    ):
                        raise SourceDataError(
                            "INCREMENTAL_UPSTREAM_TRANSIENT_100410"
                        ) from exc
                    raise
                normalized_path = stem + ".csv.gz"
                normalized = v2.csv_gzip(rows)
                v2.immutable_bytes(out / normalized_path, normalized)
                receipt = {
                    **raw_receipt,
                    "normalized_path": normalized_path,
                    "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
                    "rows": len(rows),
                    "missing_minutes": missing,
                    "state": "GAP_PRESERVED" if missing else "COMPLETE",
                    "volume_units": "UNKNOWN",
                    "synthetic_fill": False,
                }
                rp = stem + ".receipt.json"
                v2.immutable_bytes(out / rp, v2.json_bytes(receipt))
                ptr = {"path": rp, "sha256": sha_file(out / rp)}
                verify_receipt(out, ptr, sym, first)
                records.append(ptr)
                v2.atomic_json(out / "CURSOR.json", cursor)
                begin = last
            cp["symbols"][sym].update(
                count=len(records),
                end_exclusive_ms=begin,
                prefix_sha256=prefix_sha(records),
            )
            # Store only AFTER the source cursor commits: crashes recover
            # by validating exact unseen suffix, not by replaying old fills.
            v2.atomic_json(out / CHECKPOINT, cp)
        return {
            "state": "SOURCE_COLLECTION_COMPLETE_WITH_EXPLICIT_GAPS",
            "new_requests": requested,
            "end_exclusive_ms": ending,
            "symbols": list(symbols),
            "order_authority": "BLOCKED",
            "incremental_prior_prefix_read_only": True,
            "legacy_full_audit_required_separately": True,
            "loop_elapsed_seconds": round(time.monotonic() - start_time, 3),
            "collector_impl_sha256": sha_file(Path(__file__)),
        }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--start-ms", type=int, required=True)
    p.add_argument("--bootstrap-prior-v2", action="store_true")
    p.add_argument("--max-seconds", type=int, default=0)
    args = p.parse_args()
    t0 = time.monotonic()
    while True:
        try:
            receipt = collect_once(
                args.out,
                start_ms=args.start_ms,
                bootstrap_prior_v2=args.bootstrap_prior_v2,
            )
        except SourceDataError as exc:
            if str(exc) != "INCREMENTAL_UPSTREAM_TRANSIENT_100410":
                raise
            print(
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "state": "HOLD_TRANSIENT_PROVIDER_100410_RAW_SAVED",
                        "source": SOURCE,
                        "order_authority": "BLOCKED",
                        "historical_fill_backfill": False,
                        "committed_failed_response_as_candle": False,
                        "retry_after_seconds": 60,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if args.max_seconds and time.monotonic() - t0 >= args.max_seconds:
                return 0
            time.sleep(60)
            continue
        print(
            json.dumps(
                {"at": datetime.now(timezone.utc).isoformat(), **receipt},
                sort_keys=True,
            ),
            flush=True,
        )
        if args.max_seconds and time.monotonic() - t0 >= args.max_seconds:
            return 0
        time.sleep(min(10, 60 - time.time() % 60))


if __name__ == "__main__":
    raise SystemExit(main())
