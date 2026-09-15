import json
from datetime import datetime, timezone

import pytest

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    decode_message,
    digest,
    stream_identity,
)
from backend.research.rebuild.economic7_canonical_history_v1 import json_bytes
from backend.research.rebuild import scalp7_micro_producer_v2 as producer
from backend.research.rebuild.scalp7_micro_decision_v2 import MicroSourceError


def utc(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()


def make_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    identity = stream_identity(["BTC-USDT", "ETH-USDT"])
    (source / "identity.json").write_bytes(json_bytes(identity))
    row = {
        "schema": "economic7.bingx_raw_capture.v1",
        "kind": "process_start",
        "connection_id": "",
        "recorded_at_utc": utc(0),
        "local_seq": 1,
        "identity_sha256": digest(identity),
        "previous_sha256": "0" * 64,
    }
    row["record_sha256"] = digest(row)
    raw = json_bytes(row)
    (source / "raw.jsonl").write_bytes(raw)
    (source / "checkpoint.json").write_bytes(
        json_bytes(
            {
                "identity_sha256": digest(identity),
                "local_seq": 1,
                "ledger_bytes": len(raw),
                "tail_sha256": row["record_sha256"],
            }
        )
    )
    return source, row


def append_ticks(source, previous):
    for stamp, price in [
        (1, 105),
        (900_001, 100),
        (900_002, 110),
        (1_800_001, 111),
        (1_800_002, 109),
        (1_800_003, 112),
        (2_700_001, 105),
    ]:
        wire = json.dumps(
            {
                "code": 0,
                "dataType": "BTC-USDT@trade",
                "data": [
                    {"s": "BTC-USDT", "T": stamp, "p": str(price), "q": "1", "m": True}
                ],
            }
        )
        row = {
            "schema": "economic7.bingx_raw_capture.v1",
            "kind": "received",
            "connection_id": "first",
            "recorded_at_utc": utc(stamp + 2),
            "received_at_utc": utc(stamp + 1),
            "local_seq": previous["local_seq"] + 1,
            "identity_sha256": previous["identity_sha256"],
            "previous_sha256": previous["record_sha256"],
            "frame": decode_message(wire),
        }
        row["record_sha256"] = digest(row)
        with (source / "raw.jsonl").open("ab") as handle:
            handle.write(json_bytes(row))
        previous = row


def test_restart_cursor_and_signal_dedup(tmp_path, monkeypatch):
    source, previous = make_source(tmp_path)
    out = tmp_path / "producer"
    out.mkdir()
    monkeypatch.setattr(producer.time, "time", lambda: 0)
    producer.poll(out, source)
    append_ticks(source, previous)
    result = producer.poll(out, source)
    assert result["new_signals"] == 1
    again = producer.poll(out, source)
    assert again["new_signals"] == 0
    assert again["total_signals"] == 1
    assert again["processed_records"] == 0


def test_crash_after_signal_before_cursor_does_not_duplicate(tmp_path, monkeypatch):
    source, previous = make_source(tmp_path)
    out = tmp_path / "producer"
    out.mkdir()
    monkeypatch.setattr(producer.time, "time", lambda: 0)
    producer.poll(out, source)
    append_ticks(source, previous)
    original = producer.atomic_json

    def failure(path, value):
        if path.name == "CHECKPOINT.json":
            raise OSError("simulated crash")
        original(path, value)

    monkeypatch.setattr(producer, "atomic_json", failure)
    with pytest.raises(OSError, match="simulated"):
        producer.poll(out, source)
    assert len((out / "signals.jsonl").read_text().splitlines()) == 1
    monkeypatch.setattr(producer, "atomic_json", original)
    result = producer.poll(out, source)
    assert result["total_signals"] == 1
    assert result["new_signals"] == 0
    assert len((out / "signals.jsonl").read_text().splitlines()) == 1


def test_torn_source_tail_is_not_committed(tmp_path, monkeypatch):
    source, _ = make_source(tmp_path)
    out = tmp_path / "producer"
    out.mkdir()
    monkeypatch.setattr(producer.time, "time", lambda: 0)
    producer.poll(out, source)
    before = json.loads((out / "CHECKPOINT.json").read_text())["offset"]
    with (source / "raw.jsonl").open("ab") as handle:
        handle.write(b'{"incomplete":')
    result = producer.poll(out, source)
    assert result["source_offset"] == before


def test_frozen_module_identity_changes_are_rejected(tmp_path, monkeypatch):
    source, _ = make_source(tmp_path)
    out = tmp_path / "producer"
    out.mkdir()
    monkeypatch.setattr(producer.time, "time", lambda: 0)
    producer.poll(out, source)
    monkeypatch.setattr(producer, "_code_hashes", lambda: {"changed": "new hash"})
    with pytest.raises(MicroSourceError, match="FROZEN_PRODUCER"):
        producer.poll(out, source)


def test_checkpoint_source_tamper_and_signal_torn_tail_hold(tmp_path, monkeypatch):
    source, _ = make_source(tmp_path)
    out = tmp_path / "producer"
    out.mkdir()
    monkeypatch.setattr(producer.time, "time", lambda: 0)
    producer.poll(out, source)
    (out / "signals.jsonl").write_bytes(b"torn")
    with pytest.raises(MicroSourceError, match="TORN_SIGNAL"):
        producer.poll(out, source)
