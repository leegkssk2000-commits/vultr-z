"""Real source-clock shape, raw linkage and unchanged Micro grammar fixtures."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild import scalp7_trade_raw_source_v3 as raw
from backend.research.rebuild import scalp7_micro_producer_v3 as producer
from backend.research.rebuild.scalp7_micro_decision_v3 import ClockMicroDecision
from backend.research.rebuild.scalp7_micro_decision_v2 import (
    MicroDecision,
    MicroSourceError,
)
from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    Archive,
    decode_message,
    digest,
    IntegrityError,
)
from backend.research.rebuild.scalp7_source_clock_v3 import (
    await_native_time,
    wall_clock_ms,
)

BASE = 1789502400000
INTERVAL = 900000


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def proof(native, received, usable):
    return {
        "schema": "scalp7.actual_source_clock_barrier.v3",
        "state": "USABLE_AFTER_ACTUAL_CLOCK_BARRIER",
        "native_ts_ms": native,
        "received_at_ms": received,
        "started_at_ms": received,
        "usable_at_ms": usable,
        "started_monotonic_ns": 0,
        "usable_monotonic_ns": (usable - received) * 1000000,
        "waited_ms": usable - received,
        "max_wait_ms": 5000,
        "quarantined": True,
        "clock_samples": [
            {"wall_ms": received, "monotonic_ns": 0},
            {"wall_ms": usable, "monotonic_ns": (usable - received) * 1000000},
        ],
        "native_timestamp_rewritten": False,
        "receipt_timestamp_rewritten": False,
        "clock_offset_or_tolerance_applied": False,
    }


class Tape:
    def __init__(self):
        self.seq = 0
        self.tail = "0" * 64
        self.engine = ClockMicroDecision(
            frozen_at_ms=BASE - 1,
            initial_seq=0,
            initial_hash=self.tail,
            identity_sha256="i",
        )
        self.send("connected", BASE)

    def row(self, kind, stamp, **extra):
        self.seq += 1
        value = {
            "schema": "economic7.bingx_raw_capture.v1",
            "identity_sha256": "i",
            "local_seq": self.seq,
            "previous_sha256": self.tail,
            "kind": kind,
            "connection_id": "c",
            "recorded_at_utc": iso(stamp),
            **extra,
        }
        value["record_sha256"] = digest(value)
        self.tail = value["record_sha256"]
        return value

    def send(self, kind, stamp, **extra):
        return self.engine.update(self.row(kind, stamp, **extra))

    def receive(self, stamp, price, received=None):
        received = stamp - 1 if received is None else received
        wire = json.dumps(
            {
                "code": 0,
                "dataType": "BTC-USDT@trade",
                "data": [{"s": "BTC-USDT", "T": stamp, "p": str(price)}],
            }
        )
        row = self.row(
            "received",
            max(stamp, received) + 1,
            received_at_utc=iso(received),
            frame=decode_message(wire),
        )
        assert self.engine.update(row) == []
        return row

    def admit(self, row, stamp, received):
        return self.send(
            "trade_clock_admitted",
            stamp + 2,
            raw_record_sha256=row["record_sha256"],
            raw_local_seq=row["local_seq"],
            proof=proof(stamp, received, stamp + 1),
            ack_verified=True,
        )

    def tick(self, stamp, price):
        row = self.receive(stamp, price)
        return self.admit(row, stamp, stamp - 1)


def test_economic_grammar_is_exact_inherited():
    assert ClockMicroDecision._observe is MicroDecision._observe
    assert ClockMicroDecision._finish is MicroDecision._finish


def test_native_ahead_is_pending_until_linked_actual_clock_proof():
    tape = Tape()
    row = tape.receive(BASE + 100, 100)
    assert tape.engine.windows == {}
    assert tape.engine.pending_clock["received_at_ms"] == BASE + 99
    tape.admit(row, BASE + 100, BASE + 99)
    assert tape.engine.windows["BTC-USDT"]["last"] == 100
    assert tape.engine.last_clock_usable_ms == BASE + 101
    assert tape.engine.pending_clock is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("usable_at_ms", BASE + 99),
        ("native_ts_ms", BASE + 101),
        ("received_at_ms", BASE + 98),
        ("receipt_timestamp_rewritten", True),
        ("max_wait_ms", 5001),
        ("usable_monotonic_ns", 6000000000),
    ],
)
def test_invalid_proof_never_updates_candles(field, value):
    tape = Tape()
    row = tape.receive(BASE + 100, 100)
    p = proof(BASE + 100, BASE + 99, BASE + 101)
    p[field] = value
    with pytest.raises(MicroSourceError):
        tape.send(
            "trade_clock_admitted",
            BASE + 102,
            raw_record_sha256=row["record_sha256"],
            raw_local_seq=row["local_seq"],
            proof=p,
            ack_verified=True,
        )
    assert tape.engine.windows == {}


def test_wrong_raw_hash_cannot_admit_price():
    tape = Tape()
    row = tape.receive(BASE + 100, 100)
    with pytest.raises(MicroSourceError, match="RAW_BINDING"):
        tape.send(
            "trade_clock_admitted",
            BASE + 102,
            raw_record_sha256="wrong",
            raw_local_seq=row["local_seq"],
            proof=proof(BASE + 100, BASE + 99, BASE + 101),
            ack_verified=True,
        )


def test_next_frame_without_proof_is_not_silently_skipped():
    tape = Tape()
    tape.receive(BASE + 100, 100)
    with pytest.raises(MicroSourceError, match="MISSING_CLOCK_ADMISSION"):
        tape.receive(BASE + 200, 101)


def test_tampered_wire_or_raw_chain_is_rejected():
    tape = Tape()
    row = tape.row(
        "received",
        BASE + 110,
        received_at_utc=iso(BASE + 100),
        frame=decode_message("Ping"),
    )
    row["received_at_utc"] = iso(BASE + 99)
    with pytest.raises(MicroSourceError, match="RAW_CHAIN_INTEGRITY"):
        tape.engine.update(row)


def test_sequence_emits_only_after_clock_admitted_later_boundary():
    tape = Tape()
    for stamp, price in [
        (BASE + 100, 110),
        (BASE + 200, 100),
        (BASE + 300, 105),
        (BASE + INTERVAL + 100, 111),
        (BASE + INTERVAL + 200, 109),
        (BASE + INTERVAL + 300, 112),
    ]:
        assert tape.tick(stamp, price) == []
    row = tape.receive(BASE + 2 * INTERVAL + 100, 113)
    assert len(tape.engine.emitted) == 0
    signals = tape.admit(row, BASE + 2 * INTERVAL + 100, BASE + 2 * INTERVAL + 99)
    assert len(signals) == 1
    signal = signals[0]
    assert (
        signal["timeframe_min"] == 15
        and signal["side"] == 1
        and signal["stop_price"] == 109
    )
    assert signal["available_ts_ms"] == BASE + 2 * INTERVAL + 101
    assert (
        signal["source_evidence"]["actual_transport_received_at_ms"]
        == BASE + 2 * INTERVAL + 99
    )
    assert (
        signal["source_evidence"]["clock_proof"]["native_ts_ms"]
        == BASE + 2 * INTERVAL + 100
    )


def test_observed_plus_four_ms_quote_shape_waits_and_preserves(monkeypatch):
    native = 1789503232797
    received = native - 4
    wire = json.dumps(
        {
            "code": 0,
            "dataType": "BTC-USDT@trade",
            "data": [{"s": "BTC-USDT", "T": native, "p": "75965.5"}],
        }
    )
    row = {"received_at_utc": iso(received), "frame": decode_message(wire)}
    original = json.dumps(row, sort_keys=True)
    clock_values = iter([received, native])
    mono_values = iter([0, 4000000])
    monkeypatch.setattr(
        raw,
        "await_native_time",
        lambda n, r, b: await_native_time(
            n,
            r,
            b,
            clock_ms=lambda: next(clock_values),
            monotonic_ns=lambda: next(mono_values),
            sleep=lambda _: None,
        ),
    )
    proofs: list[dict[str, Any]] = []
    raw.validate_observation(row, {}, {"BTC-USDT@trade"}, proofs)
    assert (
        proofs[0]["received_at_ms"] == received and proofs[0]["native_ts_ms"] == native
    )
    assert proofs[0]["usable_at_ms"] == native and proofs[0]["quarantined"]
    assert json.dumps(row, sort_keys=True) == original


def test_unacknowledged_trade_is_never_clock_admitted():
    wire = json.dumps(
        {
            "code": 0,
            "dataType": "BTC-USDT@trade",
            "data": [{"s": "BTC-USDT", "T": BASE, "p": "100"}],
        }
    )
    with pytest.raises(IntegrityError, match="NOT_ACKNOWLEDGED"):
        raw.validate_observation(
            {"received_at_utc": iso(BASE), "frame": decode_message(wire)}, {}, set(), []
        )


def test_new_producer_restarts_from_actual_archive_without_duplicate(tmp_path: Path):
    source = tmp_path / "raw"
    out = tmp_path / "micro"
    out.mkdir()
    with Archive(source, raw.trade_identity(), max_bytes=1000000) as archive:
        archive.append("connected", "c")
        archive.checkpoint()
        producer.initialize(out, source)
        native = wall_clock_ms()
        wire = json.dumps(
            {
                "code": 0,
                "dataType": "BTC-USDT@trade",
                "data": [{"s": "BTC-USDT", "T": native, "p": "100"}],
            }
        )
        row = archive.receive("c", wire)
        proofs: list[dict[str, Any]] = []
        raw.validate_observation(row, {}, {"BTC-USDT@trade"}, proofs)
        archive.append(
            "trade_clock_admitted",
            "c",
            raw_record_sha256=row["record_sha256"],
            raw_local_seq=row["local_seq"],
            proof=proofs[0],
            ack_verified=True,
        )
        archive.checkpoint()
        first = producer.poll(out, source)
        second = producer.poll(out, source)
        assert first["processed_records"] == 2 and second["processed_records"] == 0
        assert first["fresh_closed_trades"] == second["fresh_closed_trades"] == 0
        checkpoint = json.loads((out / "CHECKPOINT.json").read_text())
        assert checkpoint["engine"]["pending_clock"] is None
