from datetime import datetime, timezone

import pytest

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    decode_message,
    digest,
)
from backend.research.rebuild.scalp7_micro_decision_v2 import (
    MicroDecision,
    MicroSourceError,
)

IDENTITY_HASH = "a" * 64


def utc(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()


def record(engine, timestamp, price, *, connection="one", maker=True, quantity="1"):
    import json

    wire = json.dumps(
        {
            "code": 0,
            "dataType": "BTC-USDT@trade",
            "data": [
                {
                    "s": "BTC-USDT",
                    "T": timestamp,
                    "p": str(price),
                    "q": quantity,
                    "m": maker,
                }
            ],
        }
    )
    row = {
        "schema": "economic7.bingx_raw_capture.v1",
        "kind": "received",
        "identity_sha256": IDENTITY_HASH,
        "local_seq": engine.local_seq + 1,
        "previous_sha256": engine.tail_hash,
        "connection_id": connection,
        "recorded_at_utc": utc(timestamp + 2),
        "received_at_utc": utc(timestamp + 1),
        "frame": decode_message(wire),
    }
    row["record_sha256"] = digest(row)
    return row


def engine():
    return MicroDecision(
        frozen_at_ms=0,
        initial_seq=0,
        initial_hash="0" * 64,
        identity_sha256=IDENTITY_HASH,
    )


def warmup(e):
    for timestamp, price in [(1, 105), (900_001, 100), (900_002, 110)]:
        assert e.update(record(e, timestamp, price)) == []


@pytest.mark.parametrize(
    "side,prices,stop", [(1, [111, 109, 112], 109), (-1, [99, 101, 98], 101)]
)
def test_ordered_break_retest_reclaim_emits_only_after_15m_boundary(side, prices, stop):
    e = engine()
    warmup(e)
    for i, price in enumerate(prices, 1):
        assert e.update(record(e, 1_800_000 + i, price)) == []
    signals = e.update(record(e, 2_700_001, 105))
    assert len(signals) == 1
    signal = signals[0]
    assert signal["side"] == side
    assert signal["stop_price"] == stop
    assert signal["signal_ts_ms"] == 2_700_002
    assert signal["available_ts_ms"] == 2_700_002
    assert signal["earliest_entry_ts_ms"] == 2_700_003
    assert signal["max_hold_bars"] == 4
    assert signal["l2_state"] == "UNUSED_SCHEMA_UNBOUND"
    assert signal["lane"] == "micro_edge"


@pytest.mark.parametrize(
    "prices", [[111, 112, 113], [111, 109, 108], [111, 99, 112], [99, 111, 98]]
)
def test_no_ordered_reclaim_or_invalidated_thesis_no_signal(prices):
    e = engine()
    warmup(e)
    for i, price in enumerate(prices, 1):
        e.update(record(e, 1_800_000 + i, price))
    assert e.update(record(e, 2_700_001, 105)) == []


def test_chain_corruption_fails_closed():
    e = engine()
    row = record(e, 1, 100)
    row["previous_sha256"] = "b" * 64
    row["record_sha256"] = digest(
        {k: v for k, v in row.items() if k != "record_sha256"}
    )
    with pytest.raises(MicroSourceError, match="RAW_CHAIN"):
        e.update(row)
    assert e.status == "HOLD_RAW_CHAIN_INTEGRITY"


def test_decoded_payload_cannot_override_actual_wire():
    e = engine()
    row = record(e, 1, 100)
    row["frame"]["decoded_text"] = "{}"
    row["record_sha256"] = digest(
        {k: v for k, v in row.items() if k != "record_sha256"}
    )
    with pytest.raises(MicroSourceError, match="WIRE_FRAME"):
        e.update(row)


def test_connection_restart_cannot_reuse_previous_window():
    e = engine()
    warmup(e)
    e.update(record(e, 1_800_001, 111))
    e.update(record(e, 1_800_002, 109, connection="two"))
    e.update(record(e, 1_800_003, 112, connection="two"))
    assert e.update(record(e, 2_700_001, 105, connection="two")) == []


def test_missing_observed_window_resets_context():
    e = engine()
    warmup(e)
    e.update(record(e, 3_600_001, 111))
    e.update(record(e, 3_600_002, 109))
    e.update(record(e, 3_600_003, 112))
    assert e.update(record(e, 4_500_001, 105)) == []


def test_direction_flag_and_quantity_are_not_strategy_inputs():
    outputs = []
    for maker, quantity in [(True, "1"), (False, "10000000")]:
        e = engine()
        warmup(e)
        for i, price in enumerate([111, 109, 112], 1):
            e.update(record(e, 1_800_000 + i, price, maker=maker, quantity=quantity))
        outputs.append(e.update(record(e, 2_700_001, 105))[0])
    keys = ["setup_id", "side", "stop_price", "signal_ts_ms", "max_hold_bars"]
    assert {k: outputs[0][k] for k in keys} == {k: outputs[1][k] for k in keys}


def test_pre_freeze_partial_window_cannot_be_context():
    e = MicroDecision(
        frozen_at_ms=100,
        initial_seq=0,
        initial_hash="0" * 64,
        identity_sha256=IDENTITY_HASH,
    )
    for stamp, price in [
        (101, 100),
        (102, 110),
        (900_001, 111),
        (900_002, 109),
        (900_003, 112),
    ]:
        assert e.update(record(e, stamp, price)) == []
    assert e.update(record(e, 1_800_001, 105)) == []


@pytest.mark.parametrize(
    "payload",
    [
        [],
        1,
        {"dataType": []},
        {"code": 0, "dataType": "BTC-USDT@trade", "data": [None]},
        {
            "code": 0,
            "dataType": "BTC-USDT@trade",
            "data": [{"s": "BTC-USDT", "T": 1, "p": None}],
        },
    ],
)
def test_valid_hash_malformed_payload_is_explicit_hold(payload):
    import json

    e = engine()
    row = record(e, 1, 100)
    row["frame"] = decode_message(json.dumps(payload))
    row["record_sha256"] = digest(
        {k: v for k, v in row.items() if k != "record_sha256"}
    )
    with pytest.raises(MicroSourceError):
        e.update(row)
    assert e.status.startswith("HOLD_")
