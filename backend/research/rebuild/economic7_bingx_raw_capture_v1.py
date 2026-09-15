"""Archive BingX public WebSocket messages without economic or book interpretation.

No orders, strategy signals, volume-unit conversion, or inferred book updates.
The JSONL ledger is authoritative; the fsynced checkpoint is an advisory prefix.
A damaged ledger is never truncated or silently repaired.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import gzip
import hashlib
import importlib
import json
import math
import os
import signal
import sys
import time
import uuid
import zlib
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENDPOINT = "wss://open-api-swap.bingx.com/swap-market"
SCHEMA = "economic7.bingx_raw_capture.v1"
DOC_URL = "https://bingx-api.github.io/docs-v3/static/js/" "app.0faf11fb00445c19dd82.js"
DOC_SHA256 = "92820fd0cdef106befbf9b2f3487d2236df76dc70c0ebec39471d694b4802a74"
ZERO_HASH = "0" * 64
MAX_DECODED_BYTES = 16 * 1024 * 1024
MAX_WIRE_BYTES = 16 * 1024 * 1024
SEND_TIMEOUT_SECONDS = 1.0
DEFAULT_MAX_BYTES = 2 * 1024**3
METADATA_RESERVE_BYTES = 16 * 1024


class IntegrityError(RuntimeError):
    """An existing durable artifact cannot be safely resumed."""


class StorageBudgetError(IntegrityError):
    """Stop before exceeding the explicitly bounded archive storage."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def stream_identity(symbols: list[str]) -> dict[str, Any]:
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("SYMBOLS_EMPTY_OR_DUPLICATE")
    if any(symbol not in {"BTC-USDT", "ETH-USDT"} for symbol in symbols):
        raise ValueError("SYMBOL_NOT_AUTHORIZED")
    symbols = sorted(symbols)
    return {
        "schema": SCHEMA,
        "endpoint": ENDPOINT,
        "symbols": symbols,
        "channels": [
            symbol + suffix for symbol in symbols for suffix in ("@incrDepth", "@trade")
        ],
        "recorder_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "source_document_url": DOC_URL,
        "source_document_sha256": DOC_SHA256,
        "role": "RAW_PUBLIC_SOURCE_ARCHIVE_ONLY",
        "quantity_units": "UNBOUND",
        "book_update_semantics": "UNBOUND",
        "trade_direction": "UNINTERPRETED",
        "trade_dedup_recent_ids": 10000,
        "max_wire_message_bytes": MAX_WIRE_BYTES,
        "max_decoded_message_bytes": MAX_DECODED_BYTES,
        "send_timeout_seconds": SEND_TIMEOUT_SECONDS,
        "economic_signal_enabled": False,
        "order_authority": "BLOCKED",
    }


def atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(canonical(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def decode_message(wire: str | bytes) -> dict[str, Any]:
    """Retain the exact received application message, even when decoding fails."""
    raw = wire.encode("utf-8") if isinstance(wire, str) else wire
    result: dict[str, Any] = {
        "wire_type": "text" if isinstance(wire, str) else "binary",
        "wire_base64": base64.b64encode(raw).decode("ascii"),
        "wire_sha256": hashlib.sha256(raw).hexdigest(),
        "wire_bytes": len(raw),
        "compression": "gzip" if raw.startswith(b"\x1f\x8b") else "none",
    }
    try:
        if result["compression"] == "gzip":
            import io

            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
                decoded = handle.read(MAX_DECODED_BYTES + 1)
        else:
            decoded = raw
        if len(decoded) > MAX_DECODED_BYTES:
            raise ValueError("DECODED_MESSAGE_LIMIT")
        result["decoded_text"] = decoded.decode("utf-8")
    except (OSError, EOFError, UnicodeError, ValueError, zlib.error) as exc:
        result["decode_error"] = type(exc).__name__ + ":" + str(exc)
    return result


class Inspector:
    """Annotate only observed schema, sequence continuity, and repeated trade IDs."""

    def __init__(self, channels: list[str], recent_limit: int = 10000):
        self.channels = set(channels)
        self.depth: dict[str, tuple[int, str, bool]] = {}
        self.trades: OrderedDict[str, str] = OrderedDict()
        self.recent_limit = recent_limit

    def new_connection(self) -> None:
        self.depth.clear()

    def remember_trade(self, key: str, payload_hash: str) -> str:
        previous = self.trades.get(key)
        status = (
            "NEW"
            if previous is None
            else "DUPLICATE" if previous == payload_hash else "ID_PAYLOAD_CONFLICT"
        )
        if previous is None:
            self.trades[key] = payload_hash
        self.trades.move_to_end(key)
        if len(self.trades) > self.recent_limit:
            self.trades.popitem(last=False)
        return status

    def observe(self, frame: dict[str, Any]) -> dict[str, Any]:
        text = frame.get("decoded_text")
        if not isinstance(text, str):
            return {"kind": "DECODE_ERROR"}
        if text == "Ping":
            return {"kind": "HEARTBEAT_PING"}
        try:
            message = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            return {"kind": "NON_JSON"}
        if not isinstance(message, dict):
            return {"kind": "UNEXPECTED_TOP_LEVEL"}
        channel = message.get("dataType")
        if message.get("id") is not None and message.get("code") is not None:
            data = message.get("data")
            if data is None:
                return {
                    "kind": "ACK_OR_RESPONSE",
                    "request_id": message["id"],
                    "code": message["code"],
                    "channel": channel,
                }
        if channel not in self.channels:
            return {"kind": "UNEXPECTED_CHANNEL", "channel": channel}
        if message.get("code") not in (None, 0):
            return {"kind": "PROVIDER_ERROR", "channel": channel}
        if channel.endswith("@incrDepth"):
            return self._depth(channel, message.get("data"))
        return self._trade(channel, message.get("data"))

    def _depth(self, channel: str, data: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": "DEPTH", "channel": channel}
        if not isinstance(data, dict):
            return {**result, "sequence": "SCHEMA_INVALID"}
        sequence = data.get("lastUpdateId")
        action = data.get("action")
        result.update({"action": action, "last_update_id": sequence})
        levels_ok = all(
            isinstance(data.get(side), list)
            and all(isinstance(row, list) and len(row) == 2 for row in data[side])
            for side in ("bids", "asks")
        )
        if (
            type(sequence) is not int
            or sequence < 0
            or action not in {"all", "update"}
            or type(data.get("time")) is not int
            or not levels_ok
        ):
            self.depth.pop(channel, None)
            return {**result, "sequence": "SCHEMA_INVALID"}
        payload_hash = digest(data)
        prior = self.depth.get(channel)
        if action == "all":
            status, valid = "SNAPSHOT", True
        elif prior is None:
            status, valid = "MISSING_SNAPSHOT", False
        elif sequence == prior[0]:
            status = "DUPLICATE" if payload_hash == prior[1] else "ID_PAYLOAD_CONFLICT"
            valid = prior[2] and status == "DUPLICATE"
        elif sequence < prior[0]:
            self.depth[channel] = (prior[0], prior[1], False)
            return {
                **result,
                "sequence": "REGRESSION",
                "contiguous_from_snapshot": False,
                "expected_id": prior[0] + 1,
            }
        elif sequence != prior[0] + 1:
            status, valid = "GAP", False
        else:
            valid = prior[2]
            status = "CONTIGUOUS" if valid else "GAP_UNRECOVERED"
        self.depth[channel] = (sequence, payload_hash, valid)
        result.update({"sequence": status, "contiguous_from_snapshot": valid})
        if prior is not None:
            result["expected_id"] = prior[0] + 1
        return result

    def _trade(self, channel: str, data: Any) -> dict[str, Any]:
        rows = data if isinstance(data, list) else [data]
        observed = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or not {"s", "t", "p", "q", "T", "m"}.issubset(row)
                or row.get("s") != channel.split("@")[0]
                or type(row.get("t")) not in (int, str)
                or isinstance(row.get("t"), str)
                and not row["t"].strip()
                or type(row.get("m")) is not bool
            ):
                observed.append({"status": "SCHEMA_UNBOUND", "raw_preserved": True})
                continue
            key = str(row["s"]) + ":" + str(row["t"])
            payload_hash = digest(row)
            observed.append(
                {
                    "trade_key": key,
                    "payload_sha256": payload_hash,
                    "status": self.remember_trade(key, payload_hash),
                }
            )
        return {"kind": "TRADE", "channel": channel, "trade_events": observed}


class Archive:
    """Single-writer, append-only hash chain with validated crash resume."""

    def __init__(
        self, out: Path, identity: dict[str, Any], max_bytes: int = DEFAULT_MAX_BYTES
    ):
        if type(max_bytes) is not int or max_bytes <= METADATA_RESERVE_BYTES:
            raise ValueError("MAX_BYTES_INVALID")
        self.max_bytes = max_bytes
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self._lock = (out / "capture.lock").open("a+b")
        self._handle: Any = None
        try:
            try:
                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise IntegrityError("CAPTURE_ALREADY_RUNNING") from exc
            identity_path = out / "identity.json"
            ledger_path = out / "raw.jsonl"
            self.identity = identity
            self.identity_hash = digest(identity)
            if identity_path.exists():
                if json.loads(identity_path.read_bytes()) != identity:
                    raise IntegrityError("IMMUTABLE_STREAM_IDENTITY")
            else:
                if ledger_path.exists():
                    raise IntegrityError("IDENTITY_MISSING_FOR_EXISTING_LEDGER")
                atomic_json(identity_path, identity)
            metadata_bytes = sum(
                p.stat().st_size
                for p in out.rglob("*")
                if p.is_file() and p != ledger_path
            )
            self.max_ledger_bytes = max_bytes - max(
                METADATA_RESERVE_BYTES, metadata_bytes + METADATA_RESERVE_BYTES
            )
            self.ledger_bytes = (
                ledger_path.stat().st_size if ledger_path.exists() else 0
            )
            if self.ledger_bytes > self.max_ledger_bytes:
                raise StorageBudgetError("RAW_STORAGE_BUDGET_HOLD")
            self.seq, self.tail_hash = 0, ZERO_HASH
            self.inspector = Inspector(identity["channels"])
            self._recover(ledger_path)
            self._handle = ledger_path.open("ab", buffering=0)
            self.checkpoint()
        except BaseException:
            if self._handle is not None:
                self._handle.close()
            self._lock.close()
            raise

    def _recover(self, ledger_path: Path) -> None:
        checkpoint_path = self.out / "checkpoint.json"
        checkpoint = (
            json.loads(checkpoint_path.read_bytes())
            if checkpoint_path.exists()
            else None
        )
        if checkpoint is not None and (
            checkpoint.get("identity_sha256") != self.identity_hash
            or type(checkpoint.get("local_seq")) is not int
            or checkpoint["local_seq"] < 0
        ):
            raise IntegrityError("CHECKPOINT_INVALID")
        checkpoint_match = checkpoint is None or (
            checkpoint["local_seq"] == 0 and checkpoint.get("tail_sha256") == ZERO_HASH
        )
        if ledger_path.exists():
            with ledger_path.open("rb") as handle:
                for line in handle:
                    if not line.endswith(b"\n"):
                        raise IntegrityError("TORN_LEDGER_TAIL_PRESERVED")
                    try:
                        row = json.loads(line)
                        saved_hash = row.pop("record_sha256")
                        if (
                            type(row.get("local_seq")) is not int
                            or row["local_seq"] != self.seq + 1
                            or row.get("identity_sha256") != self.identity_hash
                            or row.get("previous_sha256") != self.tail_hash
                            or digest(row) != saved_hash
                        ):
                            raise IntegrityError("LEDGER_HASH_OR_SEQUENCE_INVALID")
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        raise IntegrityError("LEDGER_ROW_INVALID") from exc
                    self.seq, self.tail_hash = row["local_seq"], saved_hash
                    if checkpoint and checkpoint["local_seq"] == self.seq:
                        checkpoint_match = checkpoint.get("tail_sha256") == saved_hash
                    annotation = row.get("observation", {})
                    for event in annotation.get("trade_events", []):
                        if "trade_key" in event:
                            self.inspector.remember_trade(
                                event["trade_key"], event["payload_sha256"]
                            )
        if not checkpoint_match:
            raise IntegrityError("CHECKPOINT_NOT_VERIFIED_PREFIX")

    def append(self, kind: str, connection_id: str, **payload: Any) -> dict[str, Any]:
        row = {
            **payload,
            "schema": SCHEMA,
            "kind": kind,
            "connection_id": connection_id,
            "recorded_at_utc": utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            "local_seq": self.seq + 1,
            "identity_sha256": self.identity_hash,
            "previous_sha256": self.tail_hash,
        }
        row["record_sha256"] = digest(row)
        encoded = canonical(row) + b"\n"
        if self.ledger_bytes + len(encoded) > self.max_ledger_bytes:
            raise StorageBudgetError("RAW_STORAGE_BUDGET_HOLD")
        try:
            count = self._handle.write(encoded)
        except OSError as exc:
            raise IntegrityError("LEDGER_WRITE_FAILED") from exc
        if count != len(encoded):
            raise IntegrityError("PARTIAL_LEDGER_WRITE")
        self.ledger_bytes += count
        self.seq = row["local_seq"]
        self.tail_hash = row["record_sha256"]
        return row

    def receive(self, connection_id: str, wire: str | bytes) -> dict[str, Any]:
        received_at, received_ns = utc_now(), time.monotonic_ns()
        frame = decode_message(wire)
        try:
            observation = self.inspector.observe(frame)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            observation = {"kind": "SCHEMA_UNBOUND", "error": type(exc).__name__}
        return self.append(
            "received",
            connection_id,
            received_at_utc=received_at,
            received_monotonic_ns=received_ns,
            frame=frame,
            observation=observation,
        )

    def checkpoint(self) -> None:
        try:
            self._checkpoint()
        except OSError as exc:
            raise IntegrityError("CHECKPOINT_FAILED") from exc

    def _checkpoint(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())
        atomic_json(
            self.out / "checkpoint.json",
            {
                "schema": SCHEMA,
                "identity_sha256": self.identity_hash,
                "local_seq": self.seq,
                "tail_sha256": self.tail_hash,
                "ledger_bytes": self._handle.tell(),
                "max_bytes": self.max_bytes,
                "reserved_ledger_limit_bytes": self.max_ledger_bytes,
                "checkpoint_at_utc": utc_now(),
            },
        )

    def close(self) -> None:
        try:
            if self._handle is not None and not self._handle.closed:
                self.checkpoint()
        finally:
            if self._handle is not None:
                self._handle.close()
            self._lock.close()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


async def send_recorded(
    socket: Any,
    archive: Archive,
    connection_id: str,
    text: str,
    stop: asyncio.Event | None = None,
) -> None:
    if stop is not None and stop.is_set():
        archive.append("send_skipped", connection_id, reason="STOP_EVENT")
        return
    archive.append("send_attempt", connection_id, frame=decode_message(text))
    try:
        await asyncio.wait_for(socket.send(text), timeout=SEND_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        archive.append("send_timeout", connection_id)
        raise
    archive.append(
        "send_complete",
        connection_id,
        wire_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


async def capture_session(
    socket: Any, archive: Archive, connection_id: str, stop: asyncio.Event
) -> None:
    archive.inspector.new_connection()
    for channel in archive.identity["channels"]:
        if stop.is_set():
            return
        request = canonical(
            {"id": uuid.uuid4().hex, "reqType": "sub", "dataType": channel}
        ).decode()
        await send_recorded(socket, archive, connection_id, request, stop)
    last_sync = time.monotonic()
    while not stop.is_set():
        try:
            wire = await asyncio.wait_for(socket.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            wire = None
        if wire is not None:
            row = archive.receive(connection_id, wire)
            if row["observation"]["kind"] == "HEARTBEAT_PING":
                await send_recorded(socket, archive, connection_id, "Pong", stop)
        if time.monotonic() - last_sync >= 1.0:
            archive.checkpoint()
            last_sync = time.monotonic()


async def run_capture(
    out: Path,
    symbols: list[str],
    max_seconds: float,
    stop: asyncio.Event | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    if not math.isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("MAX_SECONDS_INVALID")
    stop = stop if stop is not None else asyncio.Event()
    connector = importlib.import_module("websockets").connect
    loop = asyncio.get_running_loop()
    registered = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
            registered.append(signum)
        except (NotImplementedError, RuntimeError):
            pass
    deadline = loop.time() + max_seconds if max_seconds else None
    timer = loop.call_later(max_seconds, stop.set) if max_seconds else None
    try:
        with Archive(out, stream_identity(symbols), max_bytes=max_bytes) as archive:
            archive.append("process_start", "", process_id=os.getpid())
            backoff = 1.0
            while not stop.is_set():
                connection_id = uuid.uuid4().hex
                started = time.monotonic()
                archive.append("connect_attempt", connection_id, endpoint=ENDPOINT)
                try:
                    async with connector(
                        ENDPOINT,
                        open_timeout=(
                            min(10.0, max(0.001, deadline - loop.time()))
                            if deadline
                            else 10.0
                        ),
                        close_timeout=2,
                        ping_interval=None,
                        compression=None,
                        max_size=MAX_WIRE_BYTES,
                        max_queue=32,
                    ) as socket:
                        archive.append("connected", connection_id)
                        await capture_session(socket, archive, connection_id, stop)
                except (OSError, TimeoutError, ConnectionError) as exc:
                    archive.append(
                        "connection_error",
                        connection_id,
                        error_type=type(exc).__name__,
                        error=str(exc)[:1000],
                    )
                except Exception as exc:
                    # Protocol closure exceptions belong to websockets, but durable
                    # write errors must not be swallowed into a reconnect loop.
                    if not type(exc).__module__.startswith("websockets"):
                        raise
                    if any(
                        getattr(getattr(exc, attr, None), "code", None) == 1009
                        for attr in ("sent", "rcvd")
                    ):
                        archive.append(
                            "transport_gap",
                            connection_id,
                            reason="SOURCE_FRAME_OVERSIZE",
                            raw_message_unavailable=True,
                            error_type=type(exc).__name__,
                            error=str(exc)[:1000],
                        )
                        raise IntegrityError("SOURCE_FRAME_OVERSIZE_HOLD") from exc
                    archive.append(
                        "connection_error",
                        connection_id,
                        error_type=type(exc).__name__,
                        error=str(exc)[:1000],
                    )
                archive.append("disconnected", connection_id)
                archive.checkpoint()
                if time.monotonic() - started >= 30:
                    backoff = 1.0
                if not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=backoff)
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(backoff * 2, 30.0)
            archive.append(
                "process_stop",
                "",
                reason=(
                    "TIME_LIMIT"
                    if deadline and loop.time() >= deadline
                    else "STOP_EVENT"
                ),
            )
    finally:
        if timer:
            timer.cancel()
        for signum in registered:
            loop.remove_signal_handler(signum)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--symbols", required=True, nargs="+")
    parser.add_argument(
        "--max-seconds", required=True, type=float, help="0 means continuous"
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="Total archive byte budget including reserved metadata; default 2 GiB",
    )
    args = parser.parse_args()
    try:
        asyncio.run(
            run_capture(
                args.out, args.symbols, args.max_seconds, max_bytes=args.max_bytes
            )
        )
    except (IntegrityError, ValueError, OSError) as exc:
        print(
            json.dumps(
                {"state": "HOLD", "reason": str(exc), "type": type(exc).__name__}
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
