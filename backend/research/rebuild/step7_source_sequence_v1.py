"""One additional, bounded non-order source sequence; current raw stays isolated.

This allocation does not reset PR1209's completed snapshot allocation. Native
completed-bar progress and point-in-time depth progress are reported separately.
No historical fill, formal observation, retry, scheduler or service is created.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import time
import urllib.parse
import urllib.request

from backend.research.rebuild import step7_source_bridge_v1 as prior

ALLOCATION_ID = "STEP7_PR1209_EXECUTION_PATH_SOURCE_V1"
SELECTION_SEAL = "f63177df5c4720924ad1718ad7d50dde64697c0a8b2409413d94f44f5dddcf7d"
MAX_HTTP = 2_000
MAX_RAW = 1_073_741_824
MAX_SECONDS = 86_400
SELECTED_HTTP = 35
SELECTED_SECONDS = 180
MAX_RESPONSE = 2_000_000
MAX_WIRE = MAX_RESPONSE + 1
TERMINAL = {"SOURCE_SEQUENCE_STOPPED", "SOURCE_SEQUENCE_BLOCKED", "SOURCE_SEQUENCE_LIMIT_STOP"}


def now_ms():
    return time.time_ns() // 1_000_000


def validate_allocation(allocation: dict) -> dict:
    """The root owns the durable campaign grant; this enforces its lower bounds."""
    if allocation.get("allocation_id", allocation.get("id")) != ALLOCATION_ID:
        raise ValueError("ADDITIONAL_ALLOCATION_ID_REQUIRED")
    if allocation.get("status") != "RESERVED":
        raise ValueError("PERSISTENT_RESERVED_ALLOCATION_REQUIRED")
    for key, maximum in (("max_http_requests", MAX_HTTP), ("max_raw_bytes", MAX_RAW),
                         ("max_duration_seconds", MAX_SECONDS)):
        value = allocation.get(key)
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError("ALLOCATION_BOUND_INVALID:" + key)
    if allocation.get("max_batches") != 1 or allocation.get("used_batches", 0) != 0:
        raise ValueError("ADDITIONAL_ONE_UNSPENT_BATCH_REQUIRED")
    if allocation.get("selection_sha256") != SELECTION_SEAL:
        raise ValueError("SELECTED_KR3_SEAL_MISMATCH")
    runtime = allocation.get("selected_runtime_seconds", SELECTED_SECONDS)
    planned = allocation.get("selected_http_plan_max", SELECTED_HTTP)
    if type(runtime) is not int or not 0 < runtime <= min(SELECTED_SECONDS, allocation["max_duration_seconds"]):
        raise ValueError("FINITE_RUNTIME_BOUND_INVALID")
    if planned != SELECTED_HTTP or allocation["max_http_requests"] < planned:
        raise ValueError("FIXED_35_GET_SEQUENCE_REQUIRED")
    manifest = prior.source_manifest(json.loads(prior.SELECTION.read_text()), json.loads(prior.SOURCE_CONTRACT.read_text()))
    if allocation.get("symbols") != manifest["symbols"]:
        raise ValueError("ORIGINAL_SEVEN_SYMBOLS_REQUIRED")
    return {"allocation_id": ALLOCATION_ID, "symbols": manifest["symbols"],
            "runtime_seconds": runtime, "http_limit": min(planned, allocation["max_http_requests"]),
            "raw_bytes_limit": allocation["max_raw_bytes"], "allocation_sha256": prior.digest(allocation)}


def canonical_rows(parsed: dict) -> list[dict]:
    """Translate only already-completed raw exchange rows to native owner schema."""
    if parsed["state"].startswith("QUARANTINED"):
        raise ValueError("SOURCE_INTERVAL_QUARANTINED")
    rows = []
    for source in parsed["rows"]:
        if not isinstance(source, dict):
            raise ValueError("CANONICAL_DICTIONARY_OHLC_REQUIRED")
        stamp = int(source["time"])
        row = {"bar_open_ts": stamp, "bar_close_ts": stamp + prior.INTERVAL_MS,
               **{key: float(source[key]) for key in ("open", "high", "low", "close", "volume")}}
        vals = [row[k] for k in ("open", "high", "low", "close", "volume")]
        if stamp % prior.INTERVAL_MS or not all(math.isfinite(v) for v in vals):
            raise ValueError("SOURCE_ALIGNMENT_OR_NONFINITE")
        if min(vals[:4]) <= 0 or vals[4] < 0 or not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
            raise ValueError("SOURCE_OHLC_INVALID")
        rows.append(row)
    return rows


def advance_cursor(state: dict, key: str, cursor, received_ms: int) -> dict:
    """Only actual exchange cursors count; local receipt times never count."""
    old = state.get(key)
    result = dict(old or {"first_cursor": cursor, "last_cursor": cursor, "advances": 0,
                          "same_cursor_receipts": 0, "regressions": 0, "receipts": 0})
    if old is not None and cursor is not None and old["last_cursor"] is not None:
        try:
            before, current = int(old["last_cursor"]), int(cursor)
        except (TypeError, ValueError):
            raise ValueError("NONNUMERIC_EXCHANGE_CURSOR") from None
        if current < before:
            result["regressions"] += 1
            raise ValueError("EXCHANGE_CURSOR_REGRESSION")
        if current > before:
            result["advances"] += 1
        else:
            result["same_cursor_receipts"] += 1
    result.update(last_cursor=cursor, received_at_ms=received_ms, receipts=result["receipts"] + 1)
    state[key] = result
    return result


def _reserve(attempt: dict, directory: Path, clock) -> dict:
    stamp = clock()
    if stamp >= attempt["auto_stop_at_ms"]:
        raise ValueError("DEADLINE_REACHED")
    if len(attempt["requests"]) >= attempt["limits"]["http_limit"]:
        raise ValueError("HTTP_LIMIT_REACHED")
    if attempt["raw_bytes"] + attempt["reserved_raw_bytes"] + MAX_WIRE > attempt["limits"]["raw_bytes_limit"]:
        raise ValueError("RAW_STORAGE_LIMIT_REACHED")
    request = {"ordinal": len(attempt["requests"]) + 1, "state": "RESERVED_BEFORE_HTTP",
               "requested_at_ms": stamp, "reserved_response_bytes": MAX_WIRE}
    attempt["requests"].append(request)
    attempt["reserved_raw_bytes"] += MAX_WIRE
    # fsync + atomic rename completes before the caller can perform any HTTP.
    prior.save(directory / "ATTEMPT.json", attempt)
    return request


def _request(attempt, directory, *, stream, symbol, opener, clock):
    request = _reserve(attempt, directory, clock)
    params = {"symbol": symbol}
    if stream == "ohlcv4h":
        params.update(interval="4h", limit=400)
    elif stream == "depth":
        params["limit"] = 5
    elif stream == "funding":
        params["limit"] = 3
    uri = prior.BASE + prior.ENDPOINTS[stream] + "?" + urllib.parse.urlencode(params)
    request.update(stream=stream, symbol=symbol, uri=uri)
    prior.save(directory / "ATTEMPT.json", attempt)
    left = (attempt["auto_stop_at_ms"] - clock()) / 1_000
    if left <= 0:
        raise ValueError("DEADLINE_REACHED")
    with opener(urllib.request.Request(uri, headers={"User-Agent": "zel-step7-source-sequence-v1"}), timeout=min(8, left)) as response:
        code = getattr(response, "status", 200)
        raw = response.read(MAX_WIRE)
    received = clock()
    # Count every downloaded byte, including identical responses. Deduped disk
    # storage is never used to grant more raw/download allowance.
    attempt["raw_bytes"] += len(raw)
    attempt["reserved_raw_bytes"] -= MAX_WIRE
    source_sha = hashlib.sha256(raw).hexdigest()
    raw_path = directory / "raw" / (source_sha + ".bin")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        with raw_path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        attempt["stored_raw_bytes"] += len(raw)
    request.update(state="RAW_STORED", status_code=code, bytes=len(raw), received_at_ms=received,
                   response_delay_ms=received - request["requested_at_ms"], raw_sha256=source_sha)
    prior.save(directory / "ATTEMPT.json", attempt)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("RESPONSE_LIMIT_REACHED")
    if received >= attempt["auto_stop_at_ms"]:
        raise ValueError("DEADLINE_REACHED_AFTER_RESPONSE")
    parsed = prior.parse_raw(raw, stream=stream, received_at_ms=received)
    if parsed["state"].startswith("QUARANTINED"):
        raise ValueError("SOURCE_INTERVAL_QUARANTINED")
    if prior.parse_raw(raw_path.read_bytes(), stream=stream, received_at_ms=received) != parsed:
        raise ValueError("STORED_PARSE_PARITY_FAILED")
    cursor = parsed["last_cursor"]
    # BingX depth may expose a sequence ID or an exchange timestamp. Their
    # semantics are retained; a receipt timestamp is not a fallback cursor.
    cursor_kind = "EXCHANGE_SEQUENCE_OR_NATIVE_CLOSE"
    if stream == "depth" and cursor is None:
        cursor = parsed.get("exchange_event_ts_ms")
        cursor_kind = "EXCHANGE_EVENT_TIMESTAMP" if cursor is not None else "UNAVAILABLE"
    event = parsed.get("exchange_event_ts_ms")
    if event is not None and int(event) > received:
        raise ValueError("EXCHANGE_EVENT_IN_FUTURE")
    advance_cursor(attempt["cursors"], stream + ":" + symbol, cursor, received)
    request.update(state="STORED", cursor=cursor, cursor_kind=cursor_kind,
                   rows=len(parsed["rows"]) if isinstance(parsed["rows"], list) else None,
                   missing_intervals=parsed["missing_intervals"], duplicate_rows=parsed["duplicate_rows"],
                   exchange_event_ts_ms=event, stored_parse_parity=True)
    prior.save(directory / "ATTEMPT.json", attempt)
    return parsed


def _default_probe(rows, available_ms, state):
    from backend.research.rebuild.step7_kr3_execution_v1 import native_source_probe
    return native_source_probe(rows, available_ms, state)


def deadline_alarm(signum, frame):
    raise TimeoutError("DEADLINE_HARD_STOP")


def public_metadata(attempt: dict) -> dict:
    return {key: attempt[key] for key in (
        "schema", "allocation_id", "run_id", "owner", "host", "started_at_ms", "auto_stop_at_ms",
        "stopped_at_ms", "last_actual_log_ms", "state", "limits", "raw_bytes", "stored_raw_bytes", "reserved_raw_bytes",
        "cursors", "native_metadata", "blockers", "formal_credit", "actual_fills", "orders",
        "process_continues_after_return", "retention_scope", "sequence_assessment", "requests") if key in attempt}


def capture(directory: Path, allocation: dict, run_id: str, *, fixture_mode=False,
            opener=None, clock=None, sleeper=None, probe=None) -> dict:
    """Root dispatches once after shared reservation; a restart never retries IO."""
    injected = any(x is not None for x in (opener, clock, sleeper, probe))
    if injected and not fixture_mode:
        raise ValueError("FIXTURE_DEPENDENCIES_FORBIDDEN_IN_PRODUCTION")
    if not fixture_mode and (os.environ.get("GITHUB_ACTIONS") != "true" or
                             os.environ.get("GITHUB_REF") != "refs/heads/master" or
                             os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        raise ValueError("EXISTING_ACTIONS_FIRST_MASTER_PUSH_ONLY")
    clock, sleeper = clock or now_ms, sleeper or time.sleep
    opener, probe = opener or urllib.request.urlopen, probe or _default_probe
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "capture.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / "ATTEMPT.json"
        if path.exists():
            old = json.loads(path.read_text())
            if old["state"] not in TERMINAL:
                old.update(state="SOURCE_SEQUENCE_BLOCKED", stopped_at_ms=clock(),
                           blockers=old.get("blockers", []) + ["PRIOR_EXECUTION_AMBIGUOUS_NO_RETRY"],
                           process_continues_after_return=False)
                prior.save(path, old)
            return public_metadata(old)
        limits = validate_allocation(allocation)
        stamp = clock()
        attempt = {"schema": "zel.step7.additional.source.sequence.v1", "allocation_id": ALLOCATION_ID,
                   "run_id": run_id, "owner": "STEP7_SOURCE_SEQUENCE_ACTIONS", "host": socket.gethostname(),
                   "started_at_ms": stamp, "auto_stop_at_ms": stamp + 1_000 * limits["runtime_seconds"],
                   "state": "STARTED", "limits": limits, "raw_bytes": 0, "stored_raw_bytes": 0, "reserved_raw_bytes": 0,
                   "requests": [], "cursors": {}, "native_metadata": [], "blockers": [],
                   "formal_credit": 0, "actual_fills": 0, "orders": 0,
                   "process_continues_after_return": False, "retention_scope": "FINITE_NONFORMAL_CONNECTION_ONLY",
                   "fixture_mode": fixture_mode, "prior_source_allocation_reset": False}
        prior.save(path, attempt)
        rows_by = {}
        native_state = None
        previous_alarm = None
        if not fixture_mode:
            previous_alarm = signal.signal(signal.SIGALRM, deadline_alarm)
            signal.setitimer(signal.ITIMER_REAL, limits["runtime_seconds"])
        try:
            # An independent 400-row prefix replaces the insufficient 239-closed
            # snapshot only for this connection test, not for history/performance.
            for symbol in limits["symbols"]:
                parsed = _request(attempt, directory, stream="ohlcv4h", symbol=symbol, opener=opener, clock=clock)
                rows_by[symbol] = canonical_rows(parsed)
                _request(attempt, directory, stream="funding", symbol=symbol, opener=opener, clock=clock)
            for round_index in range(3):
                if round_index:
                    remaining = (attempt["auto_stop_at_ms"] - clock()) / 1_000
                    if remaining <= 0:
                        raise ValueError("DEADLINE_REACHED")
                    sleeper(min(5, remaining))
                for symbol in limits["symbols"]:
                    _request(attempt, directory, stream="depth", symbol=symbol, opener=opener, clock=clock)
                result = probe(rows_by, clock(), native_state)
                native_state = result.get("state")
                if not isinstance(native_state, dict) or not isinstance(result.get("metadata"), dict):
                    raise ValueError("NATIVE_PROBE_OUTPUT_CONTRACT_INVALID")
                prior.save(directory / "NATIVE_STATE.json", native_state)
                restored = json.loads((directory / "NATIVE_STATE.json").read_text())
                resumed = probe(rows_by, clock(), restored)
                # Replay may emit zero new signals on restart; the persisted
                # checkpoint itself must be identical and cause no duplicate IO.
                restart_equal = prior.digest(resumed.get("state")) == prior.digest(native_state)
                metadata = result.get("metadata", {k: result.get(k) for k in (
                    "status", "signal_count", "new_signal_count", "reference_event_count",
                    "decision_cursor", "seed", "restart_parity")})
                attempt["native_metadata"].append({"round": round_index + 1,
                    "metadata": metadata, "serialized_restart_state_equal": restart_equal,
                    "closed_bar_refreshes": 0, "historical_fills_performed": 0})
                if not restart_equal:
                    raise ValueError("NATIVE_SERIALIZED_RESTART_PARITY_FAILED")
                attempt["last_actual_log_ms"] = clock()
                prior.save(path, attempt)
            attempt["state"] = "SOURCE_SEQUENCE_STOPPED"
        except Exception as error:
            code = str(error).split("\n", 1)[0][:160]
            attempt["state"] = "SOURCE_SEQUENCE_LIMIT_STOP" if "LIMIT" in code or "DEADLINE" in code else "SOURCE_SEQUENCE_BLOCKED"
            attempt["blockers"].append(type(error).__name__ + ":" + code)
            if attempt["requests"] and attempt["requests"][-1]["state"] not in {"STORED"}:
                attempt["requests"][-1]["state"] = "FAILED_OR_AMBIGUOUS_NO_RETRY"
        finally:
            if not fixture_mode:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous_alarm)
        attempt.update(stopped_at_ms=clock(), last_actual_log_ms=clock(), process_continues_after_return=False)
        attempt["sequence_assessment"] = {
            "depth_symbols_with_two_actual_advances": [key.split(":", 1)[1] for key, cursor in attempt["cursors"].items()
                                                       if key.startswith("depth:") and cursor["advances"] >= 2],
            "native_closed_bar_advances": sum(cursor["advances"] for key, cursor in attempt["cursors"].items()
                                              if key.startswith("ohlcv4h:")),
            "closed_bar_continuation_test": "NOT_OBSERVED_SINGLE_COMPLETE_PREFIX",
            "depth_continuity": "POINT_IN_TIME_PROGRESS_NOT_FULL_EVENT_STREAM_PROOF",
            "full_formal_source_ready": False,
            "formal_blockers": ["FORMAL_SOURCE_RULES_UNAPPROVED", "NO_NATIVE_POST_START_COMPLETED_BAR_ADVANCE",
                                "NO_ACTUAL_ENTRY_EXIT_EXECUTION_EVIDENCE", "NO_FORMAL_COST_CONTRACT"]}
        prior.save(path, attempt)
        metadata = public_metadata(attempt)
        prior.save(directory / "PUBLIC_METADATA.json", metadata)
        return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = capture(args.out_dir, json.loads(args.allocation.read_text()), args.run_id)
    print("STEP7_SEQUENCE_METADATA=" + json.dumps(result, sort_keys=True))
