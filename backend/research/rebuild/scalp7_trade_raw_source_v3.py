"""Separate V3 raw archive: preserve transport/native clocks, then prove usability.

Reuses the frozen raw recorder without editing it. Subscribes to trades only,
binds ACK request IDs exactly, and preserves all wire bytes before validation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.research.rebuild.scalp7_source_clock_v3 import (
    await_native_time,
    SourceClockError,
)

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    Archive,
    ENDPOINT,
    IntegrityError,
    MAX_WIRE_BYTES,
    canonical,
    send_recorded,
    stream_identity,
)


def trade_identity() -> dict[str, Any]:
    identity = stream_identity(["BTC-USDT", "ETH-USDT"])
    identity.update(
        {
            "channels": ["BTC-USDT@trade", "ETH-USDT@trade"],
            "wrapper_source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "role": "MICRO15M_TRADE_PRICE_RAW_ACTUAL_CLOCK_V3",
            "l2_subscribed": False,
            "clock_profile": "PRESERVED_TIMESTAMPS_ACTUAL_CLOCK_BARRIER_V3",
            "max_clock_wait_ms": 5000,
            "clock_source_sha256": hashlib.sha256(
                Path(__file__).with_name("scalp7_source_clock_v3.py").read_bytes()
            ).hexdigest(),
            "ack_binding": "EXACT_REQUEST_ID_AND_CODE_ZERO",
            "trade_fields_used_for_validation": ["s", "T", "p"],
            "quantity_or_maker_semantics": "UNINTERPRETED",
        }
    )
    return identity


def validate_observation(
    row: dict[str, Any],
    pending: dict[str, str],
    acknowledged: set[str],
    clock_proofs: list[dict[str, Any]] | None = None,
) -> str | None:
    frame = row["frame"]
    if "decode_error" in frame:
        raise IntegrityError("TRADE_RAW_DECODE_ERROR")
    text = frame["decoded_text"]
    if text == "Ping":
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise IntegrityError("TRADE_RAW_NON_JSON") from exc
    if not isinstance(payload, dict):
        raise IntegrityError("TRADE_RAW_PAYLOAD_MAPPING")
    request_id = payload.get("id")
    if request_id is not None and not isinstance(request_id, str):
        raise IntegrityError("TRADE_ACK_REQUEST_ID_STRING_REQUIRED")
    if request_id in pending:
        if str(payload.get("code")) != "0":
            raise IntegrityError("TRADE_SUBSCRIPTION_ACK_REJECTED")
        ack_channel = pending.pop(request_id)
        if payload.get("dataType") not in ("", ack_channel, None):
            raise IntegrityError("TRADE_ACK_CHANNEL_MISMATCH")
        acknowledged.add(ack_channel)
        return ack_channel
    channel = payload.get("dataType")
    if channel in ("", None):
        return None
    if (
        channel not in ("BTC-USDT@trade", "ETH-USDT@trade")
        or channel not in acknowledged
    ):
        raise IntegrityError("TRADE_CHANNEL_NOT_ACKNOWLEDGED")
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise IntegrityError("TRADE_SOURCE_SCHEMA")
    received = int(
        datetime.fromisoformat(
            row["received_at_utc"].replace("Z", "+00:00")
        ).timestamp()
        * 1000
    )
    for item in payload["data"]:
        if (
            not isinstance(item, dict)
            or item.get("s") != channel.split("@")[0]
            or type(item.get("T")) is not int
            or item["T"] < 0
        ):
            raise IntegrityError("TRADE_SOURCE_IDENTITY_OR_TIME")
        try:
            if isinstance(item.get("p"), bool):
                raise ValueError("boolean price")
            price = float(item["p"])
        except (KeyError, ValueError, TypeError) as exc:
            raise IntegrityError("TRADE_PRICE_INVALID") from exc
        if not math.isfinite(price) or price <= 0:
            raise IntegrityError("TRADE_PRICE_INVALID")
    if payload["data"]:
        try:
            proof = await_native_time(
                max(x["T"] for x in payload["data"]), received, 5000
            )
        except SourceClockError as exc:
            raise IntegrityError("TRADE_CLOCK_BARRIER:" + str(exc)) from exc
        if clock_proofs is not None:
            clock_proofs.append(proof)
    return None


async def capture_trade_session(
    socket: Any, archive: Archive, connection_id: str, stop: asyncio.Event
) -> None:
    archive.inspector.new_connection()
    pending: dict[str, str] = {}
    acknowledged: set[str] = set()
    for channel in archive.identity["channels"]:
        request_id = uuid.uuid4().hex
        pending[request_id] = channel
        await send_recorded(
            socket,
            archive,
            connection_id,
            canonical(
                {"id": request_id, "reqType": "sub", "dataType": channel}
            ).decode(),
            stop,
        )
    sent_at = time.monotonic()
    last_sync = sent_at
    while not stop.is_set():
        try:
            wire = await asyncio.wait_for(socket.recv(), timeout=1)
        except asyncio.TimeoutError:
            wire = None
        if wire is not None:
            row = archive.receive(connection_id, wire)
            clock_proofs: list[dict[str, Any]] = []
            ack = validate_observation(row, pending, acknowledged, clock_proofs)
            for proof in clock_proofs:
                archive.append(
                    "trade_clock_admitted",
                    connection_id,
                    raw_record_sha256=row["record_sha256"],
                    raw_local_seq=row["local_seq"],
                    proof=proof,
                    ack_verified=True,
                )
            if ack:
                archive.append(
                    "subscription_ack_verified",
                    connection_id,
                    channel=ack,
                    ack_record_sha256=row["record_sha256"],
                    code=0,
                )
            if row["frame"].get("decoded_text") == "Ping":
                await send_recorded(socket, archive, connection_id, "Pong", stop)
        if pending and time.monotonic() - sent_at >= 10:
            raise IntegrityError("TRADE_SUBSCRIPTION_ACK_TIMEOUT")
        if time.monotonic() - last_sync >= 1:
            archive.checkpoint()
            last_sync = time.monotonic()


async def run(
    out: Path, *, max_seconds: float = 0, max_bytes: int = 4 * 1024**3
) -> None:
    import websockets

    if not math.isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("INVALID_MAX_SECONDS")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    timer = loop.call_later(max_seconds, stop.set) if max_seconds else None
    try:
        with Archive(out, trade_identity(), max_bytes=max_bytes) as archive:
            archive.append("process_start", "", process_id=os.getpid())
            while not stop.is_set():
                connection_id = uuid.uuid4().hex
                archive.append("connect_attempt", connection_id, endpoint=ENDPOINT)
                try:
                    async with websockets.connect(
                        ENDPOINT,
                        open_timeout=10,
                        close_timeout=2,
                        ping_interval=None,
                        compression=None,
                        max_size=MAX_WIRE_BYTES,
                        max_queue=32,
                    ) as socket:
                        archive.append("connected", connection_id)
                        await capture_trade_session(
                            socket, archive, connection_id, stop
                        )
                except IntegrityError:
                    raise
                except Exception as exc:
                    if not isinstance(exc, (OSError, TimeoutError)) and not type(
                        exc
                    ).__module__.startswith("websockets"):
                        raise
                    if any(
                        getattr(getattr(exc, attribute, None), "code", None) == 1009
                        for attribute in ("sent", "rcvd")
                    ):
                        archive.append(
                            "transport_gap",
                            connection_id,
                            reason="SOURCE_FRAME_OVERSIZE",
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
                if not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        pass
            archive.append("process_stop", "", reason="STOP_EVENT")
    finally:
        if timer:
            timer.cancel()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=0)
    parser.add_argument("--max-bytes", type=int, default=4 * 1024**3)
    args = parser.parse_args()
    try:
        asyncio.run(
            run(args.out, max_seconds=args.max_seconds, max_bytes=args.max_bytes)
        )
    except (IntegrityError, ValueError, OSError) as exc:
        print(json.dumps({"state": "HOLD_RAW_SOURCE", "reason": str(exc)}), flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
