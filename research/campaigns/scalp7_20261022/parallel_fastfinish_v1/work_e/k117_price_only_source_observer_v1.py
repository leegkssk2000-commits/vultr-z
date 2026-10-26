"""Single-writer, bounded K117 PRICE-ONLY development observer of existing public 1m receipts.

Default OFF; no additional collector, order API or historical prospective credit.
Does NOT override formal PREAUTO/G4/G5 or unknown future broker funding.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
import sqlite3
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

import importlib

k = importlib.import_module("k117_adapter")
journal = importlib.import_module("k117_shadow_noorder_journal_v1")
quotes = importlib.import_module("k117_existing_ws_quote_mark_v1")

HALF_HOUR = 1_800_000
MINUTE = 60_000
BARS = 136
SOURCE_ROOT = Path("/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified")
FROZEN_ROOT = k.ROOT
SCHEMA = "k117.price_only.orderless_forward_development.v1"
EVENT_CLOCK_SCHEMA = "k117.price_only.native_decision_clock.v1"
VIRTUAL_EXPORT_SCHEMA = "k117.price_only.virtual_signal_export.v1"
SOURCE_ONLY_CLOCK_SCHEMA = "k117.price_only.source_only_clock.v1"
VIRTUAL_RULE = "K117_PRICE_ONLY_30M_NATIVE"


def file_sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def source_snapshot(
    path: Path, now_ms: int, expected_close_ms: int, first_context_open_ms: int
) -> dict[str, pd.DataFrame]:
    contract = json.loads(k.PRICE_ONLY_CONTRACT.read_bytes())
    identity_raw = (path / "IDENTITY.json").read_bytes()
    identity = json.loads(identity_raw)
    identity_sha = file_sha(identity_raw)
    if (
        identity_sha != contract["source_identity_sha256"]
        or identity.get("schema") != contract["source_schema"]
        or identity.get("volume_units") != "UNKNOWN"
        or identity.get("synthetic_fill") is not False
        or sorted(identity.get("symbols", [])) != contract["required_context_symbols"]
        or identity.get("interval") != "1m"
    ):
        raise RuntimeError("SOURCE_IDENTITY_OR_SIX_SYMBOL_CONTRACT_MISMATCH")
    before = (path / "CURSOR.json").read_bytes()
    cursor = json.loads(before)
    if cursor["identity_sha256"] != identity_sha:
        raise RuntimeError("SOURCE_CURSOR_IDENTITY_MISMATCH")
    if expected_close_ms > (now_ms // HALF_HOUR) * HALF_HOUR:
        raise RuntimeError("INCOMPLETE_EXPECTED_NEXT_30M")
    latest_start = expected_close_ms - HALF_HOUR
    first_start = first_context_open_ms
    if first_start > latest_start - (BARS - 1) * HALF_HOUR:
        raise RuntimeError("FROZEN_WARMUP_CONTEXT_TOO_SHORT")
    end_exclusive = latest_start + HALF_HOUR
    frames = {}
    for symbol in contract["required_context_symbols"]:
        minutes: dict[int, tuple[Any, ...]] = {}
        for item in reversed(cursor["symbols"][symbol]):
            receipt_raw = (path / item["path"]).read_bytes()
            if file_sha(receipt_raw) != item["sha256"]:
                raise RuntimeError("SOURCE_RECEIPT_SHA_MISMATCH")
            receipt = json.loads(receipt_raw)
            if receipt["end_exclusive_ms"] <= first_start:
                break
            if receipt["start_ms"] >= end_exclusive:
                continue
            if (
                receipt["symbol"] != symbol
                or receipt["http_status"] != 200
                or receipt["synthetic_fill"] is not False
                or receipt["received_at_ms"] > now_ms
            ):
                raise RuntimeError("SOURCE_RECEIPT_CLOCK_OR_SYMBOL_INVALID")
            packed = (path / receipt["normalized_path"]).read_bytes()
            if file_sha(packed) != receipt["normalized_sha256"]:
                raise RuntimeError("SOURCE_NORMALIZED_SHA_MISMATCH")
            for candle in csv.DictReader(io.StringIO(gzip.decompress(packed).decode())):
                minute = int(candle["timestamp_ms"])
                if minute < first_start or minute >= end_exclusive:
                    continue
                vals = tuple(float(candle[c]) for c in ("open", "high", "low", "close"))
                if minute in minutes and minutes[minute][0] != vals:
                    raise RuntimeError("SOURCE_MINUTE_REVISION_MISMATCH")
                if (
                    minute not in minutes
                    or receipt["received_at_ms"] < minutes[minute][1]
                ):
                    minutes[minute] = (
                        vals, int(receipt["received_at_ms"]), item["path"],
                        item["sha256"], receipt["normalized_path"], receipt["normalized_sha256"],
                    )
        out = []
        for stamp in range(first_start, end_exclusive, HALF_HOUR):
            section = [minutes.get(stamp + i * MINUTE) for i in range(30)]
            if any(x is None for x in section):
                raise RuntimeError("SIX_CONTEXT_30M_MISSING_MINUTE:" + symbol)
            prices = [x[0] for x in section if x is not None]
            latest_available = max(int(x[1]) for x in section if x is not None)
            values: dict[str, Any] = {
                "open_ts_ms": stamp,
                "close_ts_ms": stamp + HALF_HOUR,
                "available_ts_ms": max(latest_available, stamp + HALF_HOUR),
                "segment_id": "EXACT_BINGX_1M_PRICE_ONLY_CONTIG",
                "open": prices[0][0],
                "high": max(x[1] for x in prices),
                "low": min(x[2] for x in prices),
                "close": prices[-1][3],
            }
            if int(values["available_ts_ms"]) > now_ms:
                raise RuntimeError("SIX_CONTEXT_BAR_NOT_AVAILABLE")
            out.append(values)
        frames[symbol] = pd.DataFrame(out)
        receipt_bindings = sorted({tuple(value[2:]) for value in minutes.values()})
        frames[symbol].attrs["source_receipt_evidence"] = {
            "symbol": symbol,
            "source_identity_sha256": identity_sha,
            "source_cursor_sha256": file_sha(before),
            "first_context_open_ms": first_start,
            "end_exclusive_ms": end_exclusive,
            "minute_count": len(minutes),
            "minute_binding_sha256": k.digest([[t, *minutes[t]] for t in sorted(minutes)]),
            "receipt_binding_count": len(receipt_bindings),
            "receipt_bindings_sha256": k.digest(receipt_bindings),
            "latest_bar_receipt_bindings": sorted({tuple(minutes[t][2:]) for t in minutes if t >= latest_start}),
            "normalized_source_verified": True,
            "raw_body_reverified_here": False,
        }
    after = (path / "CURSOR.json").read_bytes()
    if before != after:
        raise RuntimeError("SOURCE_CURSOR_CHANGED_DURING_SNAPSHOT")
    return frames


def safe_status(out: Path, body: dict[str, Any]) -> None:
    p = out / "STATUS.json"
    tmp = out / "STATUS.tmp"
    tmp.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, p)


def stamp_heartbeat(status: dict[str, Any], *, now_ms: int, poll_seconds: int, stopped: bool = False) -> None:
    status.update(pid=os.getpid(), updated_at_ms=int(now_ms),
                  producer_poll_seconds=int(poll_seconds), stopped=bool(stopped))


def validate_resume_checkpoint(saved: dict[str, Any], labels: list[str], now_ms: int) -> None:
    """Validate the committed batch boundary without reconstructing old clocks."""
    status, state = saved["status"], saved["adapter"]
    virtual = status.get("virtual_signal_export")
    if virtual is not None:
        if (virtual.get("schema") != VIRTUAL_EXPORT_SCHEMA
                or virtual.get("formal_adapter_sha256") != k.digest(state)
                or virtual.get("native_next_open_parity") is not False):
            raise ValueError("VIRTUAL_EXPORT_OR_FORMAL_ORIGIN_CHANGED")
        state = virtual["adapter_state"]
    started = int(status["started_at_ms"])
    next_close = int(status["next_expected_complete_close_ms"])
    first_close = (started // HALF_HOUR + 1) * HALF_HOUR
    if (status.get("schema") != SCHEMA or status.get("contract_sha256") != saved["contract_sha256"]
            or state.get("fresh_start_ms") != started or next_close < first_close
            or next_close % HALF_HOUR or started > now_ms
            or int(status["first_context_open_ms"]) != first_close - BARS * HALF_HOUR):
        raise ValueError("RESUME_START_OR_CONTEXT_CLOCK_MISMATCH")
    if status.get("next_open_entry_holds") or (state.get("pending") and virtual is None):
        raise ValueError("UNRESOLVED_PREVIOUS_NEXT_OPEN_HOLD_CANNOT_RESUME")
    decisions = status["decisions"]
    expected = [(close, sym) for close in range(first_close, next_close, HALF_HOUR) for sym in labels]
    actual = [(int(row["close_ts_ms"]), row["symbol"]) for row in decisions]
    if actual != expected or len(actual) != len(set(actual)):
        raise ValueError("RESUME_DUPLICATE_OR_INCOMPLETE_DECISION_BATCH")
    if status["signals"] != [row for row in decisions if row["status"] == "SIGNAL"]:
        raise ValueError("RESUME_SIGNAL_LEDGER_MISMATCH")
    if decisions and status.get("last_complete_30m_close_ms") != next_close - HALF_HOUR:
        raise ValueError("RESUME_LAST_COMPLETE_CLOCK_MISMATCH")
    if int(status.get("last_native_decision_ms", started)) > now_ms:
        raise ValueError("RESUME_DECISION_CLOCK_REVERSED")
    by_key = {(row["symbol"], int(row["close_ts_ms"])): row for row in decisions}
    snapshots = {}
    for source in status.get("source_receipt_snapshots", []):
        source_body = dict(source)
        claimed = source_body.pop("source_receipt_digest", None)
        if not claimed or claimed != k.digest(source_body) or claimed in snapshots:
            raise ValueError("RESUME_SOURCE_RECEIPT_SNAPSHOT_HASH_MISMATCH")
        snapshots[claimed] = source_body
    native_keys = set()
    latest_bar = {}
    previous = None
    for index, event in enumerate(state["events"]):
        body = dict(event)
        claimed = body.pop("event_sha256", None)
        if (body.get("seq") != index or body.get("previous") != previous
                or claimed != k.digest(body)):
            raise ValueError("RESUME_NATIVE_EVENT_HASH_MISMATCH")
        previous = claimed
        if event["kind"] == "BAR":
            native = event["body"]
            key = (native["symbol"], int(native["close_ts_ms"]))
            decision = by_key.get(key)
            if (key in native_keys or decision is None or decision["status"] != native["status"]
                    or decision.get("signal") != native.get("signal")
                    or int(native["decision_ts_ms"]) > now_ms):
                raise ValueError("RESUME_NATIVE_BAR_DECISION_MISMATCH")
            native_keys.add(key)
            latest_bar[key[0]] = native
            if decision.get("event_clock_schema") is not None:
                validate_clock_projection(decision, event, snapshots, now_ms)
        elif event["kind"] == "VIRTUAL_ADMISSION_ACK" and virtual is not None:
            if event["body"] not in virtual["admission_receipts"]:
                raise ValueError("VIRTUAL_ADMISSION_EVENT_WITHOUT_RECEIPT")
        elif event["kind"] != "HOLD":
            raise ValueError("RESUME_UNEXPECTED_NATIVE_EVENT")
    for symbol, cursor in state["signals"].items():
        latest = latest_bar.get(symbol)
        if (latest is None or int(cursor["last_open"]) + HALF_HOUR != int(latest["close_ts_ms"])
                or int(cursor["last_asof"]) != int(latest["decision_ts_ms"])):
            raise ValueError("RESUME_ADAPTER_CURSOR_MISMATCH")
    for row in decisions:
        if (row["symbol"], int(row["close_ts_ms"])) not in native_keys:
            raise ValueError("RESUME_UNCONSUMED_LEGACY_DECISION_NO_RETRO_REPAIR")
    if decisions and (set(state["signals"]) != set(labels) or any(
            int(cursor["last_open"]) + HALF_HOUR != next_close - HALF_HOUR
            for cursor in state["signals"].values())):
        raise ValueError("RESUME_ADAPTER_CURSOR_NOT_AT_COMMITTED_BATCH")
    if virtual is not None:
        exports = virtual["pending_exports"]
        if set(exports) != set(state["pending"]):
            raise ValueError("VIRTUAL_PENDING_EXPORT_MISMATCH")
        signals = {k.digest(row): row for row in status["signals"]}
        for symbol, uid in exports.items():
            row = signals.get(uid)
            if row is None or row["symbol"] != symbol or row["signal"] != state["pending"][symbol]["signal"]:
                raise ValueError("VIRTUAL_PENDING_SIGNAL_BINDING_MISMATCH")
        source_keys = set()
        last_source_close = {}
        for row in status["source_only_decisions"]:
            key = (row["symbol"], row["close_ts_ms"])
            source = snapshots.get(row.get("source_receipt_digest"))
            if (key in source_keys or row["symbol"] not in labels or source is None
                    or source["close_ts_ms"] != row["close_ts_ms"]
                    or not source["snapshot_asof_ms"] <= row["decision_ts_ms"] <= now_ms
                    or row["close_ts_ms"] <= last_source_close.get(row["symbol"], -1)):
                raise ValueError("RESUME_SOURCE_ONLY_CLOCK_OR_DUPLICATE_MISMATCH")
            expected = source_only_result(row["symbol"], pd.DataFrame([row["native_exit_input"]["bar"]]),
                                          row["source_receipt_digest"], row["decision_ts_ms"])
            if row != expected:
                raise ValueError("RESUME_SOURCE_ONLY_PROJECTION_MISMATCH")
            source_keys.add(key)
            last_source_close[row["symbol"]] = row["close_ts_ms"]
        if (virtual["source_only_next_close_ms"] < next_close
                or any(close >= virtual["source_only_next_close_ms"] for close in last_source_close.values())):
            raise ValueError("RESUME_SOURCE_ONLY_CURSOR_REVERSED")


def validate_clock_projection(row: dict[str, Any], native_event: dict[str, Any],
                              snapshots: dict[str, Any], now_ms: int) -> None:
    """Only new-clock rows have this contract; legacy missing timestamps stay missing."""
    source = snapshots.get(row.get("source_receipt_digest"))
    if (row.get("event_clock_schema") != EVENT_CLOCK_SCHEMA or source is None
            or source.get("close_ts_ms") != row["close_ts_ms"]
            or row["symbol"] not in source.get("symbols", {})
            or int(source["snapshot_asof_ms"]) > int(row["native_asof_ts_ms"])
            or int(row["decision_ts_ms"]) > now_ms):
        raise ValueError("RESUME_EVENT_CLOCK_OR_SOURCE_SNAPSHOT_MISMATCH")
    expected = decision_result(
        symbol=row["symbol"], target_close=int(row["close_ts_ms"]), item=row,
        native_events=[native_event], native_asof_ms=int(row["native_asof_ts_ms"]),
        decision_ts_ms=int(row["decision_ts_ms"]), available_ts_ms=int(row["available_ts_ms"]),
        source_receipt_digest=row["source_receipt_digest"], source_bar=row["native_exit_input"]["bar"],
        quote=row.get("post_decision_existing_ws_quote"))
    if any(row.get(key) != value for key, value in expected.items()):
        raise ValueError("RESUME_NATIVE_EVENT_CLOCK_PROJECTION_MISMATCH")


def append_producer_run(status: dict[str, Any], saved: dict[str, Any] | None, *,
                        actual_observer_sha: str, checkpoint_observer_sha: str,
                        resumed_at_ms: int) -> None:
    """Add current producer provenance only; legacy decision dictionaries stay byte-equivalent."""
    status.setdefault("event_clock_schema", EVENT_CLOCK_SCHEMA)
    status.setdefault("event_clock_applies_from_decision_index", len(status["decisions"]))
    status.setdefault("past_decision_clock_policy", "UNKNOWN_IF_ABSENT_NO_RECONSTRUCTION")
    status.setdefault("producer_runs", []).append({
        "actual_observer_source_sha256": actual_observer_sha,
        "checkpoint_observer_source_sha256": checkpoint_observer_sha,
        "observed_process_start_ts_ms": resumed_at_ms,
        "resumed_existing_checkpoint": saved is not None,
        "prior_checkpoint_sha256": journal.hash_body(saved) if saved is not None else None,
        "prior_adapter_state_sha256": k.digest(saved["adapter"]) if saved is not None else None,
        "prior_decision_count": len(status["decisions"]),
        "prior_native_event_count": len(saved["adapter"]["events"]) if saved is not None else 0,
    })


def decision_result(*, symbol: str, target_close: int, item: dict[str, Any],
                    native_events: list[dict[str, Any]], native_asof_ms: int,
                    decision_ts_ms: int, available_ts_ms: int,
                    source_receipt_digest: str, source_bar: dict[str, Any],
                    quote: dict[str, Any] | None) -> dict[str, Any]:
    """The decision clock is sampled after native return, before quote observation."""
    if decision_ts_ms < native_asof_ms or available_ts_ms > native_asof_ms:
        raise ValueError("DECISION_EVENT_CLOCK_REVERSED_OR_SOURCE_UNAVAILABLE")
    if (source_bar.get("close_ts_ms") != target_close
            or source_bar.get("open_ts_ms") != target_close - HALF_HOUR
            or source_bar.get("available_ts_ms") != available_ts_ms
            or target_close > native_asof_ms):
        raise ValueError("NATIVE_EXIT_INPUT_SOURCE_BAR_CLOCK_MISMATCH")
    o, h, low, c = (float(source_bar[key]) for key in ("open", "high", "low", "close"))
    if (not all(math.isfinite(value) and value > 0 for value in (o, h, low, c))
            or h < max(o, low, c) or low > min(o, h, c)):
        raise ValueError("NATIVE_EXIT_INPUT_PRICE_GEOMETRY_INVALID")
    if item["status"] == "DUPLICATE":
        raise ValueError("DUPLICATE_NATIVE_BAR_NOT_A_NEW_DECISION")
    if len(native_events) != 1:
        raise ValueError("NATIVE_EVENT_RECEIPT_COUNT_MISMATCH")
    event = native_events[0]
    body = dict(event)
    claimed = body.pop("event_sha256", None)
    native = event["body"]
    if (claimed != k.digest(body) or native.get("symbol") != symbol
            or event["kind"] not in {"BAR", "HOLD"}):
        raise ValueError("NATIVE_EVENT_RECEIPT_BINDING_MISMATCH")
    if event["kind"] == "BAR":
        if (native.get("close_ts_ms") != target_close or native.get("decision_ts_ms") != native_asof_ms
                or native.get("available_ts_ms") != available_ts_ms
                or native.get("status") != item["status"] or native.get("signal") != item.get("signal")):
            raise ValueError("NATIVE_BAR_RESULT_MISMATCH")
    elif item["status"] != "UNKNOWN" or native.get("asof_ms") != native_asof_ms:
        raise ValueError("NATIVE_HOLD_RESULT_MISMATCH")
    signal = item.get("signal")
    if item["status"] == "SIGNAL":
        if (not isinstance(signal, dict) or int(signal["signal_ts_ms"]) > native_asof_ms
                or int(signal["signal_open_ts_ms"]) + HALF_HOUR != target_close):
            raise ValueError("NATIVE_SIGNAL_EVENT_CLOCK_MISMATCH")
    elif signal is not None:
        raise ValueError("NATIVE_SIGNAL_STATUS_MISMATCH")
    return {
        "symbol": symbol, "close_ts_ms": target_close, "event_clock_schema": EVENT_CLOCK_SCHEMA,
        "decision_ts_ms": decision_ts_ms, "native_asof_ts_ms": native_asof_ms,
        "decision_clock_basis": "ACTUAL_UTC_WALL_CLOCK_AFTER_NATIVE_RETURN_BEFORE_QUOTE_READ",
        "native_signal_ts_ms": int(signal["signal_ts_ms"]) if signal else None,
        "native_signal_open_ts_ms": int(signal["signal_open_ts_ms"]) if signal else None,
        "native_signal_sha256": k.digest(signal) if signal else None,
        "native_event_seq": event["seq"], "native_event_kind": event["kind"],
        "native_receipt_sha256": claimed, "source_receipt_digest": source_receipt_digest,
        "next_open_eligibility": journal.next_open_eligibility(
            expected_open_ms=target_close, decision_ts_ms=decision_ts_ms,
            price_received_at_ms=available_ts_ms),
        "post_decision_existing_ws_quote": quote, "available_ts_ms": available_ts_ms,
        "status": item["status"], "reason": item.get("reason"), "signal": deepcopy(signal),
        "native_exit": None, "native_exit_status": "INPUT_ONLY_NO_POSITION_STATE",
        "native_exit_input": {"bar": deepcopy(source_bar), "source_bar_sha256": k.digest(source_bar),
                              "source_receipt_digest": source_receipt_digest},
        "actual_order_calls": 0, "virtual_fill": False,
    }


def observe_batch(observer: Any, *, bound: dict[str, pd.DataFrame], labels: list[str],
                  guard: dict[str, Any], fit: dict[str, Any], costs: dict[str, float],
                  target_close: int, source_receipt_digest: str,
                  clock_ms: Any = None, quote_observer: Any = None) -> list[dict[str, Any]]:
    """No partial native mutations survive a failed symbol/quote/result operation."""
    clock_ms = clock_ms or (lambda: int(time.time() * 1000))
    quote_observer = quote_observer or quotes.observe
    before = deepcopy(observer.state)
    results = []
    try:
        for sym in labels:
            native_asof = clock_ms()
            event_start = len(observer.state["events"])
            item = observer.on_bar(symbol=sym, frame=bound[sym], asof_ms=native_asof,
                                   source=guard, fit=fit, frozen_cost_bps=costs[sym])
            decision_time = clock_ms()
            native_events = observer.state["events"][event_start:]
            # UNKNOWN with a committed BAR is consumed (e.g. bootstrap unknown).
            # A HOLD-only exception rolled the adapter cursor back: retry this
            # same target, rather than creating a permanent gap on the next bar.
            if len(native_events) == 1 and native_events[0]["kind"] == "HOLD":
                raise RuntimeError("NATIVE_BAR_NOT_CONSUMED:" + sym + ":" + str(item.get("reason")))
            quote = (quote_observer(sym, decision_ts_ms=decision_time, read_at_ms=clock_ms())
                     if item["status"] == "SIGNAL" else None)
            last = bound[sym].iloc[-1]
            source_bar = {key: int(last[key]) for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms")}
            source_bar.update({key: float(last[key]) for key in ("open", "high", "low", "close")})
            results.append(decision_result(
                symbol=sym, target_close=target_close, item=item, native_events=native_events,
                native_asof_ms=native_asof, decision_ts_ms=decision_time,
                available_ts_ms=int(last.available_ts_ms), source_receipt_digest=source_receipt_digest,
                source_bar=source_bar, quote=quote))
    except BaseException:
        observer.state = before
        raise
    return results


def load_virtual_ledger_helper(path: Path, expected_sha: str) -> Any:
    if file_sha(path.read_bytes()) != expected_sha:
        raise ValueError("VIRTUAL_LEDGER_HELPER_CODE_PIN_MISMATCH")
    spec = importlib.util.spec_from_file_location("k117_pinned_virtual_ack_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_virtual_ack_ledger(path: Path, helper: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one SQLite snapshot; never instantiate its writer Store or mutate it."""
    if not path.is_file():
        raise ValueError("VIRTUAL_ACK_LEDGER_MISSING")
    connection = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        row = connection.execute("SELECT revision,state_sha256,event_count,head_sha256,payload FROM checkpoint WHERE singleton=1").fetchone()
        events = connection.execute("SELECT seq,event_id,event_sha256,payload FROM events ORDER BY seq").fetchall()
        if row is None:
            raise ValueError("VIRTUAL_ACK_CHECKPOINT_MISSING")
        revision, checksum, count, head, raw = row
        state = json.loads(raw)
        helper.verify(state)
        if k.digest(state) != checksum or count != len(events) or count != len(state["virtual_events"]):
            raise ValueError("VIRTUAL_ACK_CHECKPOINT_HASH_OR_COUNT_MISMATCH")
        for expected, stored in zip(state["virtual_events"], events):
            if (expected["seq"], expected["event_id"], expected["event_sha256"], helper.canonical(expected)) != stored:
                raise ValueError("VIRTUAL_ACK_EVENT_CHECKPOINT_MISMATCH")
        if head != (state["virtual_events"][-1]["event_sha256"] if events else None):
            raise ValueError("VIRTUAL_ACK_HEAD_MISMATCH")
        return state, {"revision": revision, "state_sha256": checksum, "event_count": count,
                       "head_sha256": head, "ledger_path": str(path.resolve())}
    finally:
        connection.close()


def initialize_virtual_export(status: dict[str, Any], formal_state: dict[str, Any], *,
                              ledger_path: Path, helper_sha: str) -> dict[str, Any]:
    binding = {"ledger_path": str(ledger_path.resolve()), "helper_sha256": helper_sha}
    existing = status.get("virtual_signal_export")
    if existing is not None:
        if existing["binding"] != binding or existing["formal_adapter_sha256"] != k.digest(formal_state):
            raise ValueError("VIRTUAL_EXPORT_BINDING_CHANGED")
        return existing
    if formal_state["pending"] or status.get("next_open_entry_holds"):
        raise ValueError("UNRESOLVED_FORMAL_PENDING_CANNOT_BECOME_VIRTUAL_ADMISSION")
    result = {
        "schema": VIRTUAL_EXPORT_SCHEMA, "binding": binding,
        "formal_adapter_sha256": k.digest(formal_state), "adapter_state": deepcopy(formal_state),
        "native_next_open_parity": False, "formal_fresh_credit": False,
        "pending_exports": {}, "admission_receipts": [], "terminal_receipts": [],
        "last_ledger_event_count": 0, "last_ledger_head_sha256": None,
        "source_only_next_close_ms": status["next_expected_complete_close_ms"],
        "virtual_exposure": {}, "native_causal_hold": None,
    }
    status["virtual_signal_export"] = result
    status.setdefault("source_only_decisions", [])
    return result


def apply_virtual_acknowledgements(status: dict[str, Any], observer: Any, ledger_state: dict[str, Any],
                                   proof: dict[str, Any], dependencies: Any, now_ms: int) -> int:
    """Only evidenced virtual admission drives the unchanged frozen reset callback."""
    before_status, before_adapter = deepcopy(status), deepcopy(observer.state)
    try:
        virtual = status["virtual_signal_export"]
        events = ledger_state["virtual_events"]
        count = virtual["last_ledger_event_count"]
        if (len(events) < count or (count and events[count-1]["event_sha256"] != virtual["last_ledger_head_sha256"])
                or int(ledger_state.get("updated_at_ms", now_ms)) > now_ms):
            raise ValueError("VIRTUAL_ACK_LEDGER_PREFIX_OR_CLOCK_REVERSED")
        acknowledgements = ledger_state.get("admission_acks", [])
        signal_rows = {k.digest(row): row for row in status["signals"]}
        changed = 0
        for symbol, uid in list(virtual["pending_exports"].items()):
            matching = [a for a in acknowledgements if a["original_signal_digest"] == uid]
            if not matching:
                continue  # Absence is UNKNOWN, never a synthetic rejection.
            if len(matching) != 1:
                raise ValueError("VIRTUAL_ADMISSION_ACK_NOT_UNIQUE")
            ack = matching[0]
            row = signal_rows[uid]
            ack_body = {key: value for key, value in ack.items() if key != "ack_sha256"}
            ack_events = [e for e in events if e["kind"] == "ADMISSION_ACK" and e["body"] == ack]
            if (k.digest(ack_body) != ack["ack_sha256"] or len(ack_events) != 1
                    or ack["rule_id"] != VIRTUAL_RULE or ack["symbol"] != symbol
                    or ack["decision_ms"] != row["decision_ts_ms"]
                    or type(ack["accepted"]) is not bool
                    or not row["decision_ts_ms"] <= ack["acknowledgement_ts_ms"] <= now_ms):
                raise ValueError("VIRTUAL_ADMISSION_ACK_IDENTITY_OR_CLOCK_MISMATCH")
            if ack["accepted"]:
                entries = [e for e in events if e["kind"] == "ENTRY"
                           and e["event_sha256"] == ack["source_entry_event_sha256"]]
                if (len(entries) != 1 or entries[0]["seq"] >= ack_events[0]["seq"]
                        or row["signal"].get("side") not in (1, "long", "LONG")):
                    raise ValueError("VIRTUAL_ACCEPTED_ENTRY_EVENT_MISSING_OR_UNSUPPORTED_SIDE")
                entry = entries[0]["body"]
                if (entry["virtual_id"] != ack["source_entry_virtual_id"]
                        or entry["original_signal_digest"] != uid or entry["rule_id"] != VIRTUAL_RULE
                        or entry["symbol"] != symbol or entry["decision_ms"] != row["decision_ts_ms"]
                        or entry["virtual_entry_observed_at_ms"] != ack["acknowledgement_ts_ms"]
                        or entry["source_quote_sha256"] != ack["source_evidence_sha256"]):
                    raise ValueError("VIRTUAL_ACCEPTED_ENTRY_ACK_JOIN_MISMATCH")
            pending = observer.state["pending"][symbol]
            if pending["signal"] != row["signal"] or pending["decision_ts_ms"] != row["native_asof_ts_ms"]:
                raise ValueError("VIRTUAL_PENDING_NATIVE_SIGNAL_CHANGED")
            hg = dependencies.helpers["_hg_load"](observer.state["signals"][symbol]["hg"])
            hg_before = dependencies.helpers["_hg_dump"](hg)
            policy = dependencies.reset()
            policy.generated(int(row["signal"]["signal_ts_ms"]))
            policy.decided(hg, accepted=ack["accepted"], decision_ts_ms=int(ack["acknowledgement_ts_ms"]))
            hg_after = dependencies.helpers["_hg_dump"](hg)
            receipt = {"symbol": symbol, "original_signal_digest": uid, "ack": deepcopy(ack),
                       "ack_event_sha256": ack_events[0]["event_sha256"], "ledger_proof": deepcopy(proof),
                       "pending_sha256": k.digest(pending), "hg_before_sha256": k.digest(hg_before),
                       "hg_after_sha256": k.digest(hg_after), "actual_ack_read_at_ms": now_ms,
                       "formal_native_entry_claimed": False, "virtual_profile_only": True}
            observer.state["signals"][symbol]["hg"] = hg_after
            del observer.state["pending"][symbol]
            del virtual["pending_exports"][symbol]
            observer.log("VIRTUAL_ADMISSION_ACK", receipt)
            virtual["admission_receipts"].append(receipt)
            changed += 1
        known_terminal = {r["event_sha256"] for r in virtual["terminal_receipts"]}
        for event in events:
            if (event["kind"] in {"EXIT", "CENSOR"} and event["body"]["rule_id"] == VIRTUAL_RULE
                    and event["event_sha256"] not in known_terminal):
                virtual["terminal_receipts"].append({"event_sha256": event["event_sha256"],
                    "kind": event["kind"], "body": deepcopy(event["body"]), "ledger_proof": deepcopy(proof),
                    "hg_reset_applied": False})
                changed += 1
        virtual["virtual_exposure"] = {
            symbol: {"virtual_id": pos["virtual_id"], "active_tracks": sorted(pos["tracks"])}
            for symbol, pos in ledger_state["positions"].items() if pos["rule_id"] == VIRTUAL_RULE}
        terminal_tracks = {}
        for receipt in virtual["terminal_receipts"]:
            terminal_tracks.setdefault(receipt["body"]["virtual_id"], set()).add(receipt["body"]["track"])
        virtual["paired_terminal_ids"] = sorted(uid for uid, tracks in terminal_tracks.items()
                                                 if tracks == {"native", "runner"})
        virtual["last_ledger_event_count"] = len(events)
        virtual["last_ledger_head_sha256"] = events[-1]["event_sha256"] if events else None
        return changed
    except BaseException:
        status.clear(); status.update(before_status)
        observer.state = before_adapter
        raise


def commit_observation(out: Path, status: dict[str, Any], observer: Any, formal_state: dict[str, Any],
                       contract_sha: str, observer_sha: str) -> str:
    if status.get("virtual_signal_export") is not None:
        status["virtual_signal_export"]["adapter_state"] = deepcopy(observer.state)
        state = formal_state
    else:
        state = observer.state
    return journal.commit_checkpoint(out, status, state, contract_sha, observer_sha)


def source_only_result(symbol: str, frame: pd.DataFrame, source_digest: str, now_ms: int) -> dict[str, Any]:
    last = frame.iloc[-1]
    source_bar = {key: int(last[key]) for key in ("open_ts_ms", "close_ts_ms", "available_ts_ms")}
    source_bar.update({key: float(last[key]) for key in ("open", "high", "low", "close")})
    if (source_bar["available_ts_ms"] > now_ms or source_bar["close_ts_ms"] > source_bar["available_ts_ms"]
            or source_bar["open_ts_ms"] % HALF_HOUR
            or source_bar["close_ts_ms"] - source_bar["open_ts_ms"] != HALF_HOUR):
        raise ValueError("SOURCE_ONLY_INPUT_NOT_AVAILABLE")
    o, h, low, c = (source_bar[key] for key in ("open", "high", "low", "close"))
    if (not all(math.isfinite(value) and value > 0 for value in (o, h, low, c))
            or h < max(o, low, c) or low > min(o, h, c)):
        raise ValueError("SOURCE_ONLY_PRICE_GEOMETRY_INVALID")
    return {"symbol": symbol, "close_ts_ms": source_bar["close_ts_ms"], "decision_ts_ms": now_ms,
            "available_ts_ms": source_bar["available_ts_ms"], "native_asof_ts_ms": None,
            "event_clock_schema": SOURCE_ONLY_CLOCK_SCHEMA, "status": "UNKNOWN", "signal": None,
            "reason": "VIRTUAL_ACK_PENDING_OR_NATIVE_CAUSAL_HOLD_SOURCE_ONLY",
            "native_status": "NOT_RUN", "native_receipt_sha256": None,
            "native_exit": None, "native_exit_status": "INPUT_ONLY_NO_POSITION_STATE",
            "source_receipt_digest": source_digest,
            "native_exit_input": {"bar": source_bar, "source_bar_sha256": k.digest(source_bar),
                                  "source_receipt_digest": source_digest},
            "actual_order_calls": 0, "virtual_fill": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-development-only", action="store_true")
    resume = parser.add_mutually_exclusive_group()
    resume.add_argument("--resume", action="store_true")
    resume.add_argument("--resume-existing", action="store_true")
    parser.add_argument("--expected-existing-observer-sha256")
    parser.add_argument("--virtual-signal-export-only", action="store_true")
    parser.add_argument("--virtual-ack-ledger", type=Path,
                        default=Path("/home/z/z/runtime/three_survivor_rr_shadow_20261026_v1/VIRTUAL_LEDGER.sqlite3"))
    parser.add_argument("--virtual-ledger-helper", type=Path)
    parser.add_argument("--expected-virtual-ledger-helper-sha256")
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-seconds", type=int, default=1500)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    if not args.enable_development_only:
        print("DEFAULT_OFF:EXPLICIT_DEVELOPMENT_ONLY_REQUIRED")
        return 0
    if not (1 <= args.max_seconds <= 604800 and 30 <= args.poll_seconds <= 300):
        raise SystemExit("BOUNDED_WATCH_REQUIRED")
    existing_sha = args.expected_existing_observer_sha256
    if args.resume_existing:
        if (not existing_sha or len(existing_sha) != 64
                or any(c not in "0123456789abcdef" for c in existing_sha)):
            raise SystemExit("EXPLICIT_EXISTING_OBSERVER_SHA256_REQUIRED")
    elif existing_sha is not None:
        raise SystemExit("EXISTING_OBSERVER_SHA_REQUIRES_RESUME_EXISTING")
    if args.virtual_signal_export_only:
        code_sha = args.expected_virtual_ledger_helper_sha256
        if (args.virtual_ledger_helper is None or not code_sha or len(code_sha) != 64
                or any(c not in "0123456789abcdef" for c in code_sha)):
            raise SystemExit("EXPLICIT_VIRTUAL_ACK_HELPER_PATH_AND_SHA_REQUIRED")
    elif args.virtual_ledger_helper is not None or args.expected_virtual_ledger_helper_sha256 is not None:
        raise SystemExit("VIRTUAL_HELPER_REQUIRES_EXPLICIT_VIRTUAL_EXPORT_MODE")
    # Original no-order isolation: scrub env before any K117 native dependencies.
    safe_env = {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT"}
    cleaned = {key: value for key, value in os.environ.items() if key in safe_env}
    os.environ.clear()
    os.environ.update(cleaned)
    # One and only one observer; does NOT claim original B4 producer.
    if args.resume or args.resume_existing:
        if not args.out.is_dir() or not (args.out / "STATE.json").is_file():
            raise ValueError("EXISTING_CHECKPOINT_REQUIRED_NO_NEW_START")
    else:
        args.out.mkdir(parents=True, exist_ok=False)
    with (args.out / "writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_locked(args)


def run_locked(args: argparse.Namespace) -> int:
    """Caller holds the original output-directory writer lock for the full run."""
    started = int(time.time() * 1000)
    process_started = started
    observer_source_sha = file_sha(Path(__file__).read_bytes())
    checkpoint_observer_sha = (
        args.expected_existing_observer_sha256 if args.resume_existing else observer_source_sha
    )
    contract_raw = k.PRICE_ONLY_CONTRACT.read_bytes()
    contract = json.loads(contract_raw)
    expected_sha = file_sha(contract_raw)
    fit_path = (
        FROZEN_ROOT
        / "research/campaigns/scalp7_20260915/broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json"
    )
    fit = json.loads(fit_path.read_text())["regime_fit"]
    if fit["sha256"] != contract["immutable_fit_sha256"]:
        raise RuntimeError("FROZEN_CONTEXT_FIT_HASH_MISMATCH")
    cost_path = (
        FROZEN_ROOT
        / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
    )
    raw_costs = cost_path.read_bytes()
    cost_data = json.loads(raw_costs)
    costs = cost_data["costs_bps"]
    d = k.dependencies()
    saved_checkpoint = None
    if args.resume or args.resume_existing:
        saved_checkpoint = journal.read_checkpoint(
            args.out, expected_sha, checkpoint_observer_sha
        )
        validate_resume_checkpoint(saved_checkpoint, contract["orderless_action_symbols"], process_started)
        started = int(saved_checkpoint["status"]["started_at_ms"])
    observer = k.Adapter(
        enabled=True,
        fixture=False,
        development=True,
        started_at_ms=started,
        state=None if saved_checkpoint is None else saved_checkpoint["adapter"],
    )
    guard = {
        "volume_units": "UNKNOWN",
        "source_schema": contract["source_schema"],
        "identity_sha256": contract["source_identity_sha256"],
        "price_only_contract_sha256": expected_sha,
        "native_price_only_six_context_verified": True,
        "no_trade_volume_used": True,
        "synthetic_fill": False,
        "higher_timeframe_complete": True,
        "stale_authority": "K117_PRICE_ONLY_30M_COMPLETE_RECEIPT_V1",
        "stale_ms": HALF_HOUR,
    }
    k.native_price_only_source_guard(guard)

    # Block all exchange/order/client network or arbitrary subprocess calls.
    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event in (
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        ):
            raise RuntimeError("ORDER_AND_SOURCE_NETWORK_CALL_BLOCKED")
        if event == "open" and arguments and isinstance(arguments[0], (str, bytes)):
            if Path(os.fsdecode(arguments[0])).name in (
                "credentials",
                "credentials.json",
                "id_rsa",
                "id_ed25519",
            ):
                raise RuntimeError("CREDENTIAL_FILE_BLOCKED")

    sys.meta_path.insert(0, k.NoOrderImports())
    sys.addaudithook(audit)
    labels = contract["orderless_action_symbols"]
    next_close = (started // HALF_HOUR + 1) * HALF_HOUR
    first_context_open = next_close - BARS * HALF_HOUR
    status: dict[str, Any] = {
        "schema": SCHEMA,
        "phase": "WAIT_FIRST_PROSPECTIVE_CLOSED_30M",
        "started_at_ms": started,
        "first_context_open_ms": first_context_open,
        "next_expected_complete_close_ms": next_close,
        "identity": k.IDENTITY,
        "contract_sha256": expected_sha,
        "source_identity_sha256": guard["identity_sha256"],
        "six_market_context_required": True,
        "price_only_volume_units": "UNKNOWN",
        "action_symbols": labels,
        "formal_shadow_active": False,
        "formal_fresh_credit": False,
        "full_funding_verified": False,
        "cost_is_reference_model": True,
        "reference_cost_snapshot_sha256": file_sha(raw_costs),
        "reference_cost_components": {
            sym: cost_data["snapshots"][sym] for sym in labels
        },
        "virtual_fills": 0,
        "order_calls": 0,
        "signals": [],
        "decisions": [],
        "next_open_entry_holds": [],
        "reason": "DEVELOPMENT_ONLY_NO_FORMAL_PREAUTO",
    }
    if saved_checkpoint is not None:
        status = deepcopy(saved_checkpoint["status"])
        next_close = int(status["next_expected_complete_close_ms"])
        first_context_open = int(status["first_context_open_ms"])
        if status.get("next_open_entry_holds"):
            raise ValueError("UNRESOLVED_PREVIOUS_NEXT_OPEN_HOLD_CANNOT_RESUME")
        status["phase"] = "RESUMED_DEVELOPMENT_OBSERVATION_NO_ORDER"
    formal_adapter_state = deepcopy(observer.state)
    ledger_helper = None
    if args.virtual_signal_export_only:
        sys.dont_write_bytecode = True
        ledger_helper = load_virtual_ledger_helper(args.virtual_ledger_helper, args.expected_virtual_ledger_helper_sha256)
        virtual = initialize_virtual_export(status, formal_adapter_state, ledger_path=args.virtual_ack_ledger,
                                            helper_sha=args.expected_virtual_ledger_helper_sha256)
        observer = k.Adapter(enabled=True, fixture=False, development=True, started_at_ms=started,
                             state=virtual["adapter_state"])
        status["observation_profile"] = "VIRTUAL_SIGNAL_EXPORT_ONLY_NO_NATIVE_NEXT_OPEN_FILL"
    elif status.get("virtual_signal_export") is not None:
        raise ValueError("VIRTUAL_EXPORT_RESUME_REQUIRES_SAME_EXPLICIT_MODE")
    append_producer_run(status, saved_checkpoint, actual_observer_sha=observer_source_sha,
                        checkpoint_observer_sha=checkpoint_observer_sha, resumed_at_ms=process_started)
    stamp_heartbeat(status, now_ms=int(time.time()*1000), poll_seconds=args.poll_seconds)
    state_sha = commit_observation(
        args.out, status, observer, formal_adapter_state, expected_sha, checkpoint_observer_sha
    )
    safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
    deadline = time.monotonic() + args.max_seconds
    try:
        while time.monotonic() < deadline:
            now = int(time.time() * 1000)
            stamp_heartbeat(status, now_ms=now, poll_seconds=args.poll_seconds)
            target_close = next_close
            ack_ready = True
            if args.virtual_signal_export_only:
                try:
                    ledger_state, proof = read_virtual_ack_ledger(args.virtual_ack_ledger, ledger_helper)
                    changed = apply_virtual_acknowledgements(status, observer, ledger_state, proof, d,
                                                            int(time.time()*1000))
                    status["virtual_ack_health"] = "VERIFIED_READ_ONLY_SQLITE_SNAPSHOT"
                    if changed:
                        seal = commit_observation(args.out, status, observer, formal_adapter_state,
                                                  expected_sha, checkpoint_observer_sha)
                        safe_status(args.out, {**status, "checkpoint_sha256": seal})
                except (ValueError, RuntimeError, OSError, KeyError, sqlite3.Error) as exc:
                    ack_ready = False
                    status["virtual_ack_health"] = "UNKNOWN:" + type(exc).__name__ + ":" + str(exc)
                virtual = status["virtual_signal_export"]
                if now - target_close >= HALF_HOUR:
                    virtual["native_causal_hold"] = "NATIVE_BAR_EXPIRED_NO_RETRO_SIGNAL_REPAIR"
                if not ack_ready or observer.state["pending"] or virtual["native_causal_hold"]:
                    source_close = int(virtual["source_only_next_close_ms"])
                    if source_close <= (now // HALF_HOUR) * HALF_HOUR:
                        source_before = deepcopy(status)
                        try:
                            frames = source_snapshot(args.source, now, source_close, first_context_open)
                            evidence = {"schema": "k117.price_only.six_context_receipts.v1", "snapshot_asof_ms": now,
                                        "close_ts_ms": source_close,
                                        "symbols": {sym: frames[sym].attrs["source_receipt_evidence"]
                                                    for sym in contract["required_context_symbols"]}}
                            receipt_digest = k.digest(evidence)
                            rows = [source_only_result(sym, frames[sym], receipt_digest, int(time.time()*1000)) for sym in labels]
                            status["source_only_decisions"].extend(rows)
                            status.setdefault("source_receipt_snapshots", []).append({**evidence, "source_receipt_digest": receipt_digest})
                            virtual["source_only_next_close_ms"] = source_close + HALF_HOUR
                            status["phase"] = "VIRTUAL_SOURCE_ONLY_NATIVE_PENDING_OR_CAUSAL_HOLD"
                        except (ValueError, RuntimeError, OSError, KeyError) as exc:
                            status = source_before
                            status["phase"] = "WAIT_SOURCE_ONLY_INPUT"
                            status["reason"] = type(exc).__name__ + ":" + str(exc)
                        except BaseException:
                            status = source_before
                            raise
                    seal = commit_observation(args.out, status, observer, formal_adapter_state,
                                              expected_sha, checkpoint_observer_sha)
                    safe_status(args.out, {**status, "checkpoint_sha256": seal})
                    time.sleep(args.poll_seconds)
                    continue
            if target_close > (now // HALF_HOUR) * HALF_HOUR:
                state_sha = commit_observation(args.out, status, observer, formal_adapter_state,
                                              expected_sha, checkpoint_observer_sha)
                safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
                time.sleep(args.poll_seconds)
                continue
            # A stale or interrupted observer is not permitted to label
            # historical bars as a fresh executable 30m signal on restart.
            if now - target_close >= HALF_HOUR:
                status["phase"] = "HOLD_EXPIRED_SOURCE_CLOSED_BAR"
                status["reason"] = "NEXT_OPEN_WITNESS_EXPIRED_NO_RETRO_EVALUATION"
                seal = commit_observation(
                    args.out, status, observer, formal_adapter_state, expected_sha, checkpoint_observer_sha
                )
                safe_status(args.out, {**status, "checkpoint_sha256": seal})
                break
            batch_before = (deepcopy(status), deepcopy(observer.state), next_close)
            batch_committed = False
            try:
                frames = source_snapshot(
                    args.source, now, target_close, first_context_open
                )
                source_evidence = {
                    "schema": "k117.price_only.six_context_receipts.v1",
                    "snapshot_asof_ms": now, "close_ts_ms": target_close,
                    "symbols": {sym: frames[sym].attrs["source_receipt_evidence"]
                                for sym in contract["required_context_symbols"]},
                }
                source_receipt_digest = k.digest(source_evidence)
                bound = d.helpers["bind_causal_context"](frames, fit)
                if any(
                    len(bound[s]) < 122 for s in contract["required_context_symbols"]
                ):
                    raise RuntimeError("NATIVE_WARMUP_121_NOT_AVAILABLE")
                common_last = {int(bound[s].iloc[-1].close_ts_ms) for s in bound}
                if len(common_last) != 1 or target_close not in common_last:
                    raise RuntimeError("SIX_CONTEXT_LAST_COMPLETE_MISMATCH")
                results = observe_batch(observer, bound=bound, labels=labels, guard=guard,
                                        fit=fit, costs=costs, target_close=target_close,
                                        source_receipt_digest=source_receipt_digest)
                next_close += HALF_HOUR
                status["next_expected_complete_close_ms"] = next_close
                status["decisions"].extend(results)
                status.setdefault("source_receipt_snapshots", []).append({
                    **source_evidence, "source_receipt_digest": source_receipt_digest})
                status["signals"].extend(x for x in results if x["status"] == "SIGNAL")
                for item in results:
                    if item["status"] == "SIGNAL":
                        if args.virtual_signal_export_only:
                            status["virtual_signal_export"]["pending_exports"][item["symbol"]] = k.digest(item)
                            continue
                        status["next_open_entry_holds"].append(
                            {
                                "symbol": item["symbol"],
                                "close_ts_ms": target_close,
                                "reason": item["next_open_eligibility"],
                                "signal_sha256": k.digest(item["signal"]),
                                "decision_ts_ms": item["decision_ts_ms"],
                                "native_signal_ts_ms": item["native_signal_ts_ms"],
                                "native_receipt_sha256": item["native_receipt_sha256"],
                                "actual_order_calls": 0,
                                "virtual_fill": False,
                            }
                        )
                if args.virtual_signal_export_only:
                    virtual = status["virtual_signal_export"]
                    virtual["source_only_next_close_ms"] = max(virtual["source_only_next_close_ms"], next_close)
                status["phase"] = (
                    "HOLD_SIGNAL_NEXT_OPEN_UNVERIFIED"
                    if status["next_open_entry_holds"]
                    else "ACTIVE_DEVELOPMENT_OBSERVATION_NO_ORDER"
                )
                status["last_complete_30m_close_ms"] = target_close
                status["last_native_decision_ms"] = max(x["decision_ts_ms"] for x in results)
                status["source_six_context_bars"] = len(
                    bound[contract["required_context_symbols"][0]]
                )
                status["source_cursor_atomic_verified"] = True
                status["adapter_event_hash"] = k.digest(observer.state["events"])
                status["reason"] = "REAL_POST_START_COMPLETED_30M_OBSERVED_NO_ORDER"
                state_sha = commit_observation(
                    args.out, status, observer, formal_adapter_state, expected_sha, checkpoint_observer_sha
                )
                batch_committed = True
                safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
                print(
                    json.dumps(
                        {
                            "state": status["phase"],
                            "fresh_30m_close": target_close,
                            "native_4_decisions": len(results),
                            "signals": len(status["signals"]),
                            "orders": 0,
                            "formal": False,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                if status["next_open_entry_holds"]:
                    break  # Fail closed: do NOT backfill this unresolved entry.
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                if not batch_committed:
                    status, observer.state, next_close = batch_before
                status["reason"] = type(exc).__name__ + ":" + str(exc)
                status["phase"] = "WAIT_SOURCE_OR_NATIVE_GUARD"
                state_sha = commit_observation(
                    args.out, status, observer, formal_adapter_state, expected_sha, checkpoint_observer_sha
                )
                safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
                print(
                    json.dumps({"state": status["phase"], "reason": status["reason"]}),
                    flush=True,
                )
            except BaseException:
                if not batch_committed:
                    status, observer.state, next_close = batch_before
                raise
            time.sleep(args.poll_seconds)
    finally:
        status["phase"] = "BOUNDED_DEVELOPMENT_OBSERVATION_STOPPED"
        stamp_heartbeat(status, now_ms=int(time.time()*1000), poll_seconds=args.poll_seconds, stopped=True)
        state_sha = commit_observation(
            args.out, status, observer, formal_adapter_state, expected_sha, checkpoint_observer_sha
        )
        safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
