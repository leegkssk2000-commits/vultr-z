import json

import pytest

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    decode_message,
    IntegrityError,
)
from backend.research.rebuild.scalp7_trade_raw_source_v2 import (
    trade_identity,
    validate_observation,
)


def row(payload):
    return {
        "received_at_utc": "2026-09-15T00:00:00Z",
        "frame": decode_message(json.dumps(payload)),
    }


def trade():
    return {
        "code": 0,
        "dataType": "BTC-USDT@trade",
        "data": [
            {"s": "BTC-USDT", "T": 1789430400000, "p": "100", "q": "UNBOUND", "m": None}
        ],
    }


def test_dedicated_identity_never_subscribes_depth():
    identity = trade_identity()
    assert identity["channels"] == ["BTC-USDT@trade", "ETH-USDT@trade"]
    assert identity["l2_subscribed"] is False
    assert identity["order_authority"] == "BLOCKED"


def test_ack_requires_exact_request_id():
    pending = {"request1": "BTC-USDT@trade"}
    acked = set()
    assert (
        validate_observation(
            row({"id": "other", "code": 0, "dataType": ""}), pending, acked
        )
        is None
    )
    assert not acked and pending
    assert (
        validate_observation(
            row({"id": "request1", "code": 0, "dataType": ""}), pending, acked
        )
        == "BTC-USDT@trade"
    )
    assert acked == {"BTC-USDT@trade"} and not pending


def test_unacknowledged_trade_and_ack_rejection_hold():
    with pytest.raises(IntegrityError, match="NOT_ACKNOWLEDGED"):
        validate_observation(row(trade()), {}, set())
    with pytest.raises(IntegrityError, match="ACK_REJECTED"):
        validate_observation(
            row({"id": "request1", "code": 100001}),
            {"request1": "BTC-USDT@trade"},
            set(),
        )


def test_real_named_trade_price_does_not_require_unknown_quantity_or_maker():
    assert validate_observation(row(trade()), {}, {"BTC-USDT@trade"}) is None


@pytest.mark.parametrize(
    "payload", [[], {"id": []}, {"code": 0, "dataType": "BTC-USDT@trade", "data": [1]}]
)
def test_malformed_source_shapes_fail_closed(payload):
    with pytest.raises(IntegrityError):
        validate_observation(row(payload), {}, {"BTC-USDT@trade"})


@pytest.mark.parametrize(
    "field,value",
    [("p", None), ("p", True), ("p", "NaN"), ("T", 1789430400001), ("s", "ETH-USDT")],
)
def test_trade_price_time_and_symbol_integrity(field, value):
    payload = trade()
    payload["data"][0][field] = value
    with pytest.raises(IntegrityError):
        validate_observation(row(payload), {}, {"BTC-USDT@trade"})
