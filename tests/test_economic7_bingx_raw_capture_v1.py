import asyncio
import base64
import gzip
import json
from types import SimpleNamespace

import pytest

from backend.research.rebuild import economic7_bingx_raw_capture_v1 as capture


def identity():
    return capture.stream_identity(["BTC-USDT", "ETH-USDT"])


def depth(sequence=10, action="all", quantity="0.003"):
    return {
        "code": 0,
        "dataType": "BTC-USDT@incrDepth",
        "data": {
            "action": action,
            "lastUpdateId": sequence,
            "time": 1700000000000,
            "bids": [["42000", quantity]],
            "asks": [["42001", "0.002"]],
        },
    }


def trade(trade_id="42", price="42000"):
    return {
        "code": 0,
        "dataType": "BTC-USDT@trade",
        "data": {
            "e": "trade",
            "E": 1700000000001,
            "T": 1700000000000,
            "s": "BTC-USDT",
            "t": trade_id,
            "p": price,
            "q": "0.001",
            "m": True,
        },
    }


def observe(inspector, value):
    return inspector.observe(capture.decode_message(json.dumps(value)))


def ledger_rows(out):
    return [json.loads(line) for line in (out / "raw.jsonl").read_text().splitlines()]


def test_identity_is_order_independent_and_rejects_scope_expansion():
    assert identity() == capture.stream_identity(["ETH-USDT", "BTC-USDT"])
    assert identity()["quantity_units"] == "UNBOUND"
    assert identity()["order_authority"] == "BLOCKED"
    for symbols in ([], ["BTC-USDT", "BTC-USDT"], ["SOL-USDT"], ["BTCUSDT"]):
        with pytest.raises(ValueError):
            capture.stream_identity(symbols)


@pytest.mark.parametrize("binary", [True, False])
def test_exact_message_retained_with_gzip_and_plain_text(binary):
    text = ' { "data": [1, 2], "unicode": "\\u00e9" }\n'
    wire = gzip.compress(text.encode()) if binary else text
    frame = capture.decode_message(wire)
    assert frame["decoded_text"] == text
    assert base64.b64decode(frame["wire_base64"]) == (wire if binary else text.encode())
    assert (
        frame["wire_sha256"]
        == capture.hashlib.sha256(wire if binary else text.encode()).hexdigest()
    )


@pytest.mark.parametrize("wire", [b"\x1f\x8bgarbage", b"\xff\xfe"])
def test_malformed_bytes_still_preserved(wire):
    frame = capture.decode_message(wire)
    assert "decode_error" in frame
    assert base64.b64decode(frame["wire_base64"]) == wire
    assert (
        capture.Inspector(identity()["channels"]).observe(frame)["kind"]
        == "DECODE_ERROR"
    )


def test_oversized_decompression_is_bounded_but_raw_kept(monkeypatch):
    monkeypatch.setattr(capture, "MAX_DECODED_BYTES", 8)
    wire = gzip.compress(b"x" * 50)
    frame = capture.decode_message(wire)
    assert "DECODED_MESSAGE_LIMIT" in frame["decode_error"]
    assert base64.b64decode(frame["wire_base64"]) == wire


def test_depth_gap_duplicate_conflict_and_new_snapshot():
    inspector = capture.Inspector(identity()["channels"])
    assert observe(inspector, depth())["sequence"] == "SNAPSHOT"
    assert observe(inspector, depth(11, "update"))["sequence"] == "CONTIGUOUS"
    assert observe(inspector, depth(11, "update"))["sequence"] == "DUPLICATE"
    assert observe(inspector, depth(13, "update"))["sequence"] == "GAP"
    assert observe(inspector, depth(14, "update"))["sequence"] == "GAP_UNRECOVERED"
    assert (
        observe(inspector, depth(14, "update", "10"))["sequence"]
        == "ID_PAYLOAD_CONFLICT"
    )
    assert observe(inspector, depth(15, "all"))["contiguous_from_snapshot"]
    inspector.new_connection()
    assert observe(inspector, depth(16, "update"))["sequence"] == "MISSING_SNAPSHOT"


def test_regression_invalidates_until_another_snapshot():
    inspector = capture.Inspector(identity()["channels"])
    observe(inspector, depth())
    assert observe(inspector, depth(9, "update"))["sequence"] == "REGRESSION"
    assert observe(inspector, depth(11, "update"))["sequence"] == "GAP_UNRECOVERED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("lastUpdateId", True),
        ("lastUpdateId", "11"),
        ("time", None),
        ("bids", [["42000"]]),
        ("asks", None),
        ("action", "unknown"),
    ],
)
def test_depth_schema_not_coerced(field, value):
    inspector = capture.Inspector(identity()["channels"])
    payload = depth()
    payload["data"][field] = value
    assert observe(inspector, payload)["sequence"] == "SCHEMA_INVALID"


def test_trade_unordered_ids_and_bounded_dedup_without_side_claim():
    inspector = capture.Inspector(identity()["channels"], recent_limit=2)
    for tid in ("42", "40"):
        result = observe(inspector, trade(tid))
        assert result["trade_events"][0]["status"] == "NEW"
        assert "side" not in json.dumps(result)
    assert observe(inspector, trade("42"))["trade_events"][0]["status"] == "DUPLICATE"
    assert (
        observe(inspector, trade("42", "41000"))["trade_events"][0]["status"]
        == "ID_PAYLOAD_CONFLICT"
    )
    observe(inspector, trade("43"))
    assert observe(inspector, trade("40"))["trade_events"][0]["status"] == "NEW"


def test_list_trade_schema_preserved_and_missing_id_never_invented():
    inspector = capture.Inspector(identity()["channels"])
    payload = trade()
    row = payload["data"]
    missing = dict(row)
    missing.pop("t")
    payload["data"] = [row, missing]
    result = observe(inspector, payload)
    assert result["trade_events"][0]["trade_key"] == "BTC-USDT:42"
    assert result["trade_events"][1]["status"] == "SCHEMA_UNBOUND"


@pytest.mark.parametrize(
    "value,kind",
    [
        ([], "UNEXPECTED_TOP_LEVEL"),
        ({"dataType": "SOL-USDT@trade"}, "UNEXPECTED_CHANNEL"),
        ({"id": "subscription-1", "code": 0, "data": None}, "ACK_OR_RESPONSE"),
        ({"dataType": "BTC-USDT@trade", "code": 100400}, "PROVIDER_ERROR"),
    ],
)
def test_schema_annotation(value, kind):
    assert observe(capture.Inspector(identity()["channels"]), value)["kind"] == kind


def test_append_resume_preserves_raw_duplicates_and_rebuilds_trade_window(tmp_path):
    with capture.Archive(tmp_path, identity()) as archive:
        first = archive.receive("connection-1", json.dumps(trade()))
        archive.receive("connection-1", json.dumps(trade()))
        assert first["local_seq"] == 1
    before = (tmp_path / "raw.jsonl").read_bytes()
    with capture.Archive(tmp_path, identity()) as archive:
        row = archive.receive("connection-2", json.dumps(trade()))
        assert row["local_seq"] == 3
        assert row["observation"]["trade_events"][0]["status"] == "DUPLICATE"
        assert row["previous_sha256"] == ledger_rows(tmp_path)[1]["record_sha256"]
    assert (tmp_path / "raw.jsonl").read_bytes().startswith(before)
    assert len(ledger_rows(tmp_path)) == 3


def test_stale_checkpoint_is_a_verified_prefix_and_resume_keeps_extra_rows(tmp_path):
    archive = capture.Archive(tmp_path, identity())
    archive.append("test", "connection-1")
    archive.checkpoint()
    prefix = (tmp_path / "checkpoint.json").read_bytes()
    archive.append("test", "connection-1")
    archive.close()
    (tmp_path / "checkpoint.json").write_bytes(prefix)
    with capture.Archive(tmp_path, identity()) as resumed:
        assert resumed.seq == 2


def test_single_writer_lock_and_immutable_stream(tmp_path):
    with capture.Archive(tmp_path, identity()):
        with pytest.raises(capture.IntegrityError, match="ALREADY_RUNNING"):
            capture.Archive(tmp_path, identity())
    with pytest.raises(capture.IntegrityError, match="IMMUTABLE_STREAM"):
        capture.Archive(tmp_path, capture.stream_identity(["BTC-USDT"]))


@pytest.mark.parametrize(
    "damage", ["hash", "tail", "checkpoint_ahead", "missing_identity"]
)
def test_corruption_refuses_resume_and_preserves_bytes(tmp_path, damage):
    with capture.Archive(tmp_path, identity()) as archive:
        archive.append("test", "connection-1", payload="original")
    ledger = tmp_path / "raw.jsonl"
    if damage == "hash":
        ledger.write_bytes(ledger.read_bytes().replace(b"original", b"modified"))
    elif damage == "tail":
        ledger.write_bytes(ledger.read_bytes() + b'{"partial":')
    elif damage == "checkpoint_ahead":
        checkpoint = json.loads((tmp_path / "checkpoint.json").read_bytes())
        checkpoint["local_seq"] += 1
        (tmp_path / "checkpoint.json").write_text(json.dumps(checkpoint))
    else:
        (tmp_path / "identity.json").unlink()
    before = ledger.read_bytes()
    with pytest.raises(capture.IntegrityError):
        capture.Archive(tmp_path, identity())
    assert ledger.read_bytes() == before


def test_fsync_error_is_fatal_integrity_error(tmp_path, monkeypatch):
    archive = capture.Archive(tmp_path, identity())

    def fail(_):
        raise OSError("disk unavailable")

    with monkeypatch.context() as context:
        context.setattr(capture.os, "fsync", fail)
        with pytest.raises(capture.IntegrityError, match="CHECKPOINT_FAILED"):
            archive.checkpoint()
    archive.close()


class FakeSocket:
    def __init__(self, stop, messages):
        self.stop = stop
        self.messages = list(messages)
        self.sent = []

    async def send(self, text):
        self.sent.append(text)

    async def recv(self):
        wire = self.messages.pop(0)
        if not self.messages:
            self.stop.set()
        return wire


def test_async_gzip_heartbeat_subscription_and_ack_archive(tmp_path):
    async def exercise():
        stop = asyncio.Event()
        socket = FakeSocket(
            stop,
            [
                gzip.compress(b"Ping"),
                json.dumps({"id": "ack-1", "code": 0, "data": None}),
                gzip.compress(json.dumps(depth()).encode()),
                json.dumps(trade()),
            ],
        )
        with capture.Archive(tmp_path, identity()) as archive:
            await capture.capture_session(socket, archive, "connection-1", stop)
        assert socket.sent[-1] == "Pong"
        subscriptions = [json.loads(text) for text in socket.sent[:-1]]
        assert {r["dataType"] for r in subscriptions} == set(identity()["channels"])
        assert len({r["id"] for r in subscriptions}) == 4

    asyncio.run(exercise())
    rows = ledger_rows(tmp_path)
    received = [row for row in rows if row["kind"] == "received"]
    assert len(received) == 4
    assert received[0]["observation"]["kind"] == "HEARTBEAT_PING"
    assert received[1]["observation"]["kind"] == "ACK_OR_RESPONSE"
    assert received[2]["observation"]["sequence"] == "SNAPSHOT"
    assert all(row["received_at_utc"].endswith("+00:00") for row in received)


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_invalid_duration_never_imports_network_client(tmp_path, seconds, monkeypatch):
    def forbidden(_):
        raise AssertionError("network client should not be loaded")

    monkeypatch.setattr(capture.importlib, "import_module", forbidden)
    with pytest.raises(ValueError, match="MAX_SECONDS"):
        asyncio.run(capture.run_capture(tmp_path, ["BTC-USDT"], seconds))


def test_runner_uses_only_frozen_public_endpoint_with_mocked_transport(
    tmp_path, monkeypatch
):
    async def exercise():
        stop = asyncio.Event()
        seen = []

        class Context:
            async def __aenter__(self):
                return FakeSocket(stop, [gzip.compress(b"Ping")])

            async def __aexit__(self, *args):
                pass

        def connector(endpoint, **kwargs):
            seen.append((endpoint, kwargs))
            return Context()

        monkeypatch.setattr(
            capture.importlib,
            "import_module",
            lambda _: SimpleNamespace(connect=connector),
        )
        await capture.run_capture(tmp_path, ["BTC-USDT"], 5, stop)
        assert seen[0][0] == capture.ENDPOINT
        assert seen[0][1]["compression"] is None

    asyncio.run(exercise())
    rows = ledger_rows(tmp_path)
    assert rows[-1]["kind"] == "process_stop"
    assert any(row["kind"] == "connected" for row in rows)


def test_storage_budget_never_discards_or_exceeds_budget(tmp_path):
    maximum = capture.METADATA_RESERVE_BYTES * 3
    with capture.Archive(tmp_path, identity(), max_bytes=maximum) as archive:
        with pytest.raises(capture.StorageBudgetError, match="STORAGE_BUDGET_HOLD"):
            for _ in range(30):
                archive.receive("connection-1", "raw-" + "x" * 4000)
    before = (tmp_path / "raw.jsonl").read_bytes()
    assert before
    assert sum(p.stat().st_size for p in tmp_path.rglob("*") if p.is_file()) < maximum
    assert (
        json.loads((tmp_path / "checkpoint.json").read_text())["max_bytes"] == maximum
    )
    with capture.Archive(tmp_path, identity(), max_bytes=maximum):
        pass
    assert (tmp_path / "raw.jsonl").read_bytes() == before


@pytest.mark.parametrize("maximum", [-1, 0, 10, True])
def test_invalid_byte_budgets_fail_before_creating_archive(tmp_path, maximum):
    target = tmp_path / "archive"
    with pytest.raises(ValueError, match="MAX_BYTES_INVALID"):
        capture.Archive(target, identity(), max_bytes=maximum)
    assert not target.exists()


def test_disk_write_error_does_not_become_reconnect(tmp_path):
    class FailedWriter:
        def write(self, _):
            raise OSError("disk full")

    with capture.Archive(tmp_path, identity()) as archive:
        handle = archive._handle
        archive._handle = FailedWriter()
        try:
            with pytest.raises(capture.IntegrityError, match="LEDGER_WRITE_FAILED"):
                archive.append("test", "connection-1")
        finally:
            archive._handle = handle
        assert archive.seq == 0


def test_main_budget_failure_returns_hold_exit_two(tmp_path, monkeypatch, capsys):
    async def budget_failure(*args, **kwargs):
        raise capture.StorageBudgetError("RAW_STORAGE_BUDGET_HOLD")

    monkeypatch.setattr(capture, "run_capture", budget_failure)
    monkeypatch.setattr(
        capture.sys,
        "argv",
        [
            "capture",
            "--out",
            str(tmp_path),
            "--symbols",
            "BTC-USDT",
            "--max-seconds",
            "60",
        ],
    )
    with pytest.raises(SystemExit) as result:
        capture.main()
    assert result.value.code == 2
    assert json.loads(capsys.readouterr().err)["state"] == "HOLD"


def test_bounded_session_records_time_limit_and_finishes(tmp_path, monkeypatch):
    class QuietSocket:
        async def send(self, text):
            pass

        async def recv(self):
            await asyncio.sleep(20)

    class Context:
        async def __aenter__(self):
            return QuietSocket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        capture.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=lambda *args, **kwargs: Context()),
    )
    asyncio.run(capture.run_capture(tmp_path, ["BTC-USDT"], 0.01))
    assert ledger_rows(tmp_path)[-1]["reason"] == "TIME_LIMIT"


def test_blocked_send_cannot_outlive_bounded_capture(tmp_path, monkeypatch):
    class BlockedSocket:
        async def send(self, text):
            await asyncio.sleep(20)

    class Context:
        async def __aenter__(self):
            return BlockedSocket()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(capture, "SEND_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        capture.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=lambda *args, **kwargs: Context()),
    )
    asyncio.run(
        asyncio.wait_for(capture.run_capture(tmp_path, ["BTC-USDT"], 0.01), timeout=0.5)
    )
    rows = ledger_rows(tmp_path)
    assert any(row["kind"] == "send_timeout" for row in rows)
    assert rows[-1]["reason"] == "TIME_LIMIT"


def test_oversize_transport_gap_is_explicit_fatal_hold(tmp_path, monkeypatch):
    class TooLarge(Exception):
        __module__ = "websockets.exceptions"
        sent = SimpleNamespace(code=1009)
        rcvd = None

    class Socket:
        async def send(self, text):
            pass

        async def recv(self):
            raise TooLarge("message exceeds maximum size")

    seen = []

    class Context:
        async def __aenter__(self):
            return Socket()

        async def __aexit__(self, *args):
            pass

    def connector(*args, **kwargs):
        seen.append(kwargs)
        return Context()

    monkeypatch.setattr(
        capture.importlib,
        "import_module",
        lambda _: SimpleNamespace(connect=connector),
    )
    with pytest.raises(capture.IntegrityError, match="SOURCE_FRAME_OVERSIZE_HOLD"):
        asyncio.run(capture.run_capture(tmp_path, ["BTC-USDT"], 10))
    assert seen[0]["max_size"] == capture.MAX_WIRE_BYTES
    gap = ledger_rows(tmp_path)[-1]
    assert gap["kind"] == "transport_gap"
    assert gap["raw_message_unavailable"] is True


def test_stopped_sender_does_not_attempt_transport(tmp_path):
    async def exercise():
        stop = asyncio.Event()
        stop.set()
        with capture.Archive(tmp_path, identity()) as archive:
            await capture.send_recorded(object(), archive, "connection-1", "Pong", stop)

    asyncio.run(exercise())
    assert ledger_rows(tmp_path)[-1]["kind"] == "send_skipped"


def test_corrupted_gzip_deflate_preserves_exact_wire_and_does_not_crash(tmp_path):
    # Valid gzip header, reserved DEFLATE block type, dummy trailer.
    wire = bytes.fromhex("1f8b0800000000000003") + b"\x07" + b"\x00" * 8
    with pytest.raises(capture.zlib.error):
        gzip.decompress(wire)
    with capture.Archive(tmp_path, identity()) as archive:
        row = archive.receive("connection-1", wire)
    assert row["observation"]["kind"] == "DECODE_ERROR"
    assert base64.b64decode(row["frame"]["wire_base64"]) == wire
    assert row["frame"]["decode_error"].startswith("error:")
    assert len(ledger_rows(tmp_path)) == 1
