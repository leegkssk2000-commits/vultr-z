"""Q0's source-only immutable journal and one atomic observer checkpoint.

Only accepted completed 4h source records enter the journal. A transaction is
visible iff CURRENT.json points to its hash-addressed immutable batch. The
batch commits source deltas, the contiguous cursor, and model state together;
an interrupted unpublished batch is an orphan, never an extra model advance.
Loading reconstructs the source index, not historical economic experiments.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

INTERVAL = 4 * 60 * 60 * 1000
DAY = 6 * INTERVAL
SOURCE_OWNER = "G5_CLEAN_RUNNER_OWNER_V1"
SCHEMA = "Q0_PROSPECTIVE_ARCHIVE_V1"


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def initial_state(symbols, capture_start_ms, t0_ms, t_end_ms, engine_state=None):
    if (len(symbols) != len(set(symbols)) or not symbols
            or any(not isinstance(s, str) or not s for s in symbols)):
        raise RuntimeError("ARCHIVE_SYMBOLS_INVALID")
    if (any(type(t) is not int for t in (capture_start_ms, t0_ms, t_end_ms))
            or capture_start_ms % INTERVAL or t0_ms % DAY or t_end_ms % DAY
            or not 0 <= capture_start_ms <= t0_ms < t_end_ms):
        raise RuntimeError("ARCHIVE_BOUNDARY_INVALID")
    return {"schema_version": SCHEMA, "generation": 0, "head": None,
            "symbols": list(symbols), "capture_start_ms": capture_start_ms,
            "t0_ms": t0_ms, "t_end_ms": t_end_ms,
            "cursor_ms": capture_start_ms, "records": {}, "quarantine": {},
            "unresolved_gaps": [], "gap_history": [],
            "gap_suspended_until_ms": capture_start_ms,
            "engine_state": copy.deepcopy(engine_state or {}),
            "formal_credit": 0, "operating_adoption": False,
            "independent": False, "research_only": True}


def _key(symbol, stamp):
    return f"{symbol}:{stamp}"


def _normalize(envelope, state):
    record = copy.deepcopy(envelope)
    symbol, bar = record.get("symbol"), record.get("bar")
    if symbol not in state["symbols"] or not isinstance(bar, dict):
        raise RuntimeError("ARCHIVE_SOURCE_SYMBOL_OR_BAR_INVALID")
    start, close = bar.get("bar_open_ts"), bar.get("bar_close_ts")
    observed = record.get("observed_at_ms")
    if (type(start) is not int or type(close) is not int
            or type(observed) is not int or start % INTERVAL
            or close != start + INTERVAL or observed < close
            or start < state["capture_start_ms"]):
        raise RuntimeError("ARCHIVE_UNCLOSED_OR_BOUNDARY_INVALID")
    for field in ("open", "high", "low", "close", "volume"):
        value = bar.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or (value < 0 if field == "volume" else value <= 0)):
            raise RuntimeError("ARCHIVE_OHLCV_INVALID:" + field)
    if (bar["high"] < max(bar["open"], bar["close"], bar["low"])
            or bar["low"] > min(bar["open"], bar["close"], bar["high"])):
        raise RuntimeError("ARCHIVE_OHLC_ORDER_INVALID")
    if (record.get("source_owner") != SOURCE_OWNER
            or not record.get("run_id") or not record.get("source_commit")
            or not isinstance(record.get("raw"), (dict, list))
            or not record["raw"]):
        raise RuntimeError("ARCHIVE_SOURCE_PROVENANCE_MISSING")
    # Comparison ignores collection metadata, while the first actual raw
    # payload and its provenance remain permanently available in the journal.
    identity = {k: float(bar[k]) for k in ("open", "high", "low", "close", "volume")}
    identity.update(symbol=symbol, bar_open_ts=start, bar_close_ts=close)
    record["canonical_bar_sha256"] = digest(identity)
    record["archive_raw_sha256"] = digest(record["raw"])
    record["recorded_lag_ms"] = observed - close
    record["namespace"] = ("WARMUP_CAPTURE" if start < state["t0_ms"] else
                           "FUTURE_OBSERVATION" if close <= state["t_end_ms"] else
                           "AFTER_FROZEN_WINDOW")
    record["backfill"] = bool(record.get("backfill", False))
    return _key(symbol, start), record


def ingest(state, envelopes):
    """Validate atomically, preserve conflicts, release only full baskets.

    Returns (new_state, newly_contiguous_baskets, summary). A conflict latches
    the campaign's evidence hold. A gap suspends at the first missing basket;
    late repair is retained and explicitly marked, without deleting positions.
    """
    normalized = [_normalize(row, state) for row in envelopes]
    result = copy.deepcopy(state)
    added, conflicts, duplicates = [], [], 0
    prior_gaps = set(state["unresolved_gaps"])
    max_before = max((r["bar"]["bar_open_ts"] for r in state["records"].values()),
                     default=state["capture_start_ms"] - INTERVAL)
    for key, record in normalized:
        old = result["records"].get(key)
        if old is not None:
            if old["canonical_bar_sha256"] == record["canonical_bar_sha256"]:
                duplicates += 1
                continue
            conflict_id = digest({"key": key, "value": record["canonical_bar_sha256"]})
            if conflict_id not in result["quarantine"]:
                conflict = {"key": key, "first_sha256": old["canonical_bar_sha256"],
                            "conflicting_record": record,
                            "resolution": "UNRESOLVED_NO_OVERWRITE"}
                result["quarantine"][conflict_id] = conflict
                conflicts.append({"id": conflict_id, **conflict})
            continue
        record["out_of_order"] = record["bar"]["bar_open_ts"] < max_before
        record["gap_repair"] = key in prior_gaps
        record["backfill"] = record["backfill"] or record["gap_repair"]
        result["records"][key] = record
        added.append({"key": key, "record": record})

    baskets = []
    if not result["quarantine"]:
        stamp = state["cursor_ms"]
        while stamp < result["t_end_ms"]:
            keys = [_key(symbol, stamp) for symbol in result["symbols"]]
            if any(key not in result["records"] for key in keys):
                break
            records = [result["records"][key] for key in keys]
            backfill = any(row["backfill"] for row in records)
            # All already-received baskets held behind the gap were not
            # processed on time, even if their own raw source was punctual.
            delayed = backfill or stamp + INTERVAL <= state["gap_suspended_until_ms"]
            baskets.append({"bar_open_ts": stamp, "bar_close_ts": stamp + INTERVAL,
                "rows_by_symbol": {row["symbol"]: copy.deepcopy(row["bar"])
                                   for row in records},
                "observed_at_ms": max(row["observed_at_ms"] for row in records),
                "source_records": {row["symbol"]: {
                    k: row[k] for k in ("observed_at_ms", "run_id", "source_commit",
                                        "canonical_bar_sha256", "recorded_lag_ms")}
                    for row in records},
                "quality": {"backfill": backfill, "delayed": delayed,
                            "out_of_order": any(row["out_of_order"] for row in records),
                            "conflict": False,
                            "evidence_admissible": not delayed}})
            stamp += INTERVAL
        result["cursor_ms"] = stamp
    high = min(result["t_end_ms"], max(
        (row["bar"]["bar_close_ts"] for row in result["records"].values()),
        default=result["capture_start_ms"]))
    gaps = [_key(symbol, stamp)
            for stamp in range(result["cursor_ms"], high, INTERVAL)
            for symbol in result["symbols"]
            if _key(symbol, stamp) not in result["records"]]
    result["unresolved_gaps"] = gaps
    if gaps:
        result["gap_suspended_until_ms"] = max(result["gap_suspended_until_ms"], high)
    for key in gaps:
        if key not in result["gap_history"]:
            result["gap_history"].append(key)
    summary = {"accepted": len(added), "duplicates": duplicates,
               "new_conflicts": len(conflicts), "conflicts_total": len(result["quarantine"]),
               "gap_keys": len(gaps), "contiguous_baskets": len(baskets),
               "cursor_ms": result["cursor_ms"],
               "status": "CONFLICT_HOLD" if result["quarantine"] else
                         "GAP_HOLD" if gaps else "CONTIGUOUS"}
    # Internal deltas are returned only for the transaction writer. They are
    # source records, never another strategy or candidate evaluation.
    summary["delta"] = {"accepted": added, "conflicts": conflicts}
    return result, baskets, summary


def _fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".q0-tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_hashed(path, sha):
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != sha:
        raise RuntimeError("ARCHIVE_HASH_MISMATCH:" + str(path))
    return json.loads(payload)


def load(root, initial=None):
    """Rebuild the source index from committed deltas; ignore orphan batches."""
    root = Path(root)
    pointer = root / "CURRENT.json"
    if not pointer.exists():
        if initial is None:
            raise RuntimeError("ARCHIVE_NOT_INITIALIZED")
        return copy.deepcopy(initial)
    head = json.loads(pointer.read_text())
    chain, expected = [], head["transaction_sha256"]
    while expected:
        transaction = _read_hashed(root / "transactions" / (expected + ".json"), expected)
        if transaction.get("schema_version") != SCHEMA:
            raise RuntimeError("ARCHIVE_SCHEMA_MISMATCH")
        chain.append((expected, transaction))
        expected = transaction["previous_sha256"]
    if len(chain) != head["generation"]:
        raise RuntimeError("ARCHIVE_GENERATION_MISMATCH")
    state = None
    for expected, transaction in reversed(chain):
        if state is None:
            state = copy.deepcopy(transaction["initial"])
        if transaction["generation"] != state["generation"] + 1:
            raise RuntimeError("ARCHIVE_CHAIN_SEQUENCE_MISMATCH")
        for item in transaction["source_delta"]["accepted"]:
            if item["key"] in state["records"]:
                raise RuntimeError("ARCHIVE_DUPLICATE_COMMITTED_SOURCE_KEY")
            state["records"][item["key"]] = item["record"]
        for item in transaction["source_delta"]["conflicts"]:
            state["quarantine"][item["id"]] = {k: v for k, v in item.items() if k != "id"}
        state.update(copy.deepcopy(transaction["checkpoint"]))
        state["generation"], state["head"] = transaction["generation"], expected
    if state["generation"] != head["generation"]:
        raise RuntimeError("ARCHIVE_CURRENT_SEQUENCE_MISMATCH")
    return state


def transact(root, expected_generation, envelopes, engine_update, *, initial=None,
             crash_at=None):
    """Commit one source + model step, or no-op for identical recapture.

    engine_update(engine_state, baskets, archive_state) returns model state.
    The callback executes before any publication; exceptions commit nothing.
    crash_at is exclusively a synthetic fault-injection hook used by tests.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".writer.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = load(root, initial)
        if current["generation"] != expected_generation:
            raise RuntimeError("ARCHIVE_STALE_WRITER")
        updated, baskets, summary = ingest(current, envelopes)
        delta = summary.pop("delta")
        if not delta["accepted"] and not delta["conflicts"] and current["generation"]:
            return current, {**summary, "committed": False,
                             "transaction_sha256": current["head"]}
        updated["engine_state"] = engine_update(copy.deepcopy(current["engine_state"]),
                                                 baskets, updated)
        checkpoint = {key: copy.deepcopy(updated[key]) for key in (
            "cursor_ms", "unresolved_gaps", "gap_history",
            "gap_suspended_until_ms", "engine_state")}
        transaction = {"schema_version": SCHEMA,
            "generation": current["generation"] + 1,
            "previous_sha256": current["head"],
            "source_delta": delta, "checkpoint": checkpoint}
        if current["generation"] == 0:
            transaction["initial"] = copy.deepcopy(current)
        payload = canonical_bytes(transaction)
        sha = hashlib.sha256(payload).hexdigest()
        path = root / "transactions" / (sha + ".json")
        if path.exists():
            if path.read_bytes() != payload:
                raise RuntimeError("ARCHIVE_IMMUTABLE_COLLISION")
        else:
            _atomic(path, payload)
        if crash_at == "after_batch":
            raise RuntimeError("SYNTHETIC_CRASH_AFTER_BATCH")
        _atomic(root / "CURRENT.json", canonical_bytes({"schema_version": SCHEMA,
            "generation": transaction["generation"], "transaction_sha256": sha}))
        if crash_at == "after_pointer":
            raise RuntimeError("SYNTHETIC_CRASH_AFTER_POINTER")
        updated["generation"], updated["head"] = transaction["generation"], sha
        return updated, {**summary, "committed": True, "transaction_sha256": sha}
