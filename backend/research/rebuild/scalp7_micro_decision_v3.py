"""V3 raw-clock adapter; original Micro15m economic grammar is inherited unchanged."""

from __future__ import annotations

import base64
import math
from typing import Any
from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    decode_message,
    digest,
)
from backend.research.rebuild.scalp7_micro_decision_v2 import (
    INTERVAL_MS,
    MicroDecision,
    MicroSourceError,
    utc_ms,
)


class ClockMicroDecision(MicroDecision):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.initial_prefix_seq = int(kwargs["initial_seq"])
        self.pending_clock: dict[str, Any] | None = None

    def _reset(self, status: str) -> None:
        super()._reset(status)
        self.pending_clock = None

    def update(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        clean = {key: value for key, value in record.items() if key != "record_sha256"}
        if (
            record.get("schema") != "economic7.bingx_raw_capture.v1"
            or record.get("identity_sha256") != self.identity_sha256
            or record.get("local_seq") != self.local_seq + 1
            or record.get("previous_sha256") != self.tail_hash
            or record.get("record_sha256") != digest(clean)
        ):
            self._reset("HOLD_RAW_CHAIN_INTEGRITY")
            raise MicroSourceError("RAW_CHAIN_INTEGRITY")
        self.local_seq = record["local_seq"]
        self.tail_hash = record["record_sha256"]
        recorded = utc_ms(record["recorded_at_utc"])
        if recorded < self.frozen_at_ms:
            self._reset("HOLD_PRE_FREEZE_RECORD")
            return []
        connection = record.get("connection_id", "")
        if connection and connection != self.connection_id:
            self.connection_id = connection
            self._reset("WARMUP_NEW_CONNECTION")
            self.eligible_from_ms = (
                (recorded + INTERVAL_MS - 1) // INTERVAL_MS
            ) * INTERVAL_MS
        if record.get("kind") in {
            "connection_end",
            "process_start",
            "connection_error",
        }:
            self._reset("HOLD_SOURCE_CONNECTION_BOUNDARY")
            return []
        if record.get("kind") == "trade_clock_admitted":
            return self._admit_clock_record(record, recorded)
        if record.get("kind") != "received":
            return []
        received = utc_ms(record["received_at_utc"])
        if received < self.last_received_ms or received > recorded:
            self._reset("HOLD_RECEIPT_ORDER")
            raise MicroSourceError("RECEIPT_TIME_ORDER")
        self.last_received_ms = received
        frame = record["frame"]
        wire = base64.b64decode(frame["wire_base64"], validate=True)
        decoded = decode_message(
            wire if frame["wire_type"] == "binary" else wire.decode()
        )
        if decoded != frame:
            self._reset("HOLD_WIRE_FRAME_MISMATCH")
            raise MicroSourceError("WIRE_FRAME_MISMATCH")
        import json

        try:
            payload = json.loads(decoded["decoded_text"])
        except (KeyError, ValueError):
            return []
        if not isinstance(payload, dict):
            self._reset("HOLD_PAYLOAD_MAPPING_REQUIRED")
            raise MicroSourceError("PAYLOAD_MAPPING_REQUIRED")
        channel = payload.get("dataType", "")
        if not isinstance(channel, str):
            self._reset("HOLD_CHANNEL_STRING_REQUIRED")
            raise MicroSourceError("CHANNEL_STRING_REQUIRED")
        if not channel.endswith("@trade"):
            return []
        symbol = channel.split("@")[0]
        if symbol not in ("BTC-USDT", "ETH-USDT") or str(payload.get("code")) != "0":
            self._reset("HOLD_TRADE_CHANNEL_IDENTITY")
            raise MicroSourceError("TRADE_CHANNEL_IDENTITY")
        events = payload.get("data")
        if not isinstance(events, list):
            self._reset("HOLD_TRADE_SCHEMA")
            raise MicroSourceError("TRADE_SCHEMA")
        if getattr(self, "pending_clock", None) is not None:
            self._reset("HOLD_MISSING_CLOCK_ADMISSION")
            raise MicroSourceError("MISSING_CLOCK_ADMISSION")
        if not events:
            return []
        for event in events:
            if (
                not isinstance(event, dict)
                or event.get("s") != symbol
                or type(event.get("T")) is not int
                or event["T"] < 0
                or isinstance(event.get("p"), bool)
            ):
                raise MicroSourceError("CLOCK_PENDING_TRADE_SCHEMA")
            try:
                price = float(event["p"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MicroSourceError("CLOCK_PENDING_TRADE_PRICE") from exc
            if not math.isfinite(price) or price <= 0:
                raise MicroSourceError("CLOCK_PENDING_TRADE_PRICE")
        self.pending_clock = {
            "raw_record_sha256": record["record_sha256"],
            "raw_local_seq": record["local_seq"],
            "received_at_ms": received,
            "symbol": symbol,
            "events": events,
        }
        self.status = "WAIT_SOURCE_CLOCK_ADMISSION"
        return []

    def _admit_clock_record(
        self, record: dict[str, Any], recorded: int
    ) -> list[dict[str, Any]]:
        pending = self.pending_clock
        if pending is None:
            if int(record.get("raw_local_seq", -1)) <= self.initial_prefix_seq:
                self.status = "IGNORED_CLOCK_ADMISSION_FOR_PRE_FREEZE_PREFIX"
                return []
            raise MicroSourceError("CLOCK_ADMISSION_WITHOUT_RAW_RECORD")
        if (
            record.get("raw_record_sha256") != pending["raw_record_sha256"]
            or record.get("raw_local_seq") != pending["raw_local_seq"]
            or record.get("ack_verified") is not True
        ):
            raise MicroSourceError("CLOCK_ADMISSION_RAW_BINDING")
        proof = record.get("proof", {})
        maximum = max(x["T"] for x in pending["events"])
        for field in (
            "native_ts_ms",
            "received_at_ms",
            "started_at_ms",
            "usable_at_ms",
            "started_monotonic_ns",
            "usable_monotonic_ns",
            "max_wait_ms",
        ):
            if type(proof.get(field)) is not int:
                raise MicroSourceError("CLOCK_PROOF_INTEGER_FIELD")
        samples = proof.get("clock_samples")
        if not isinstance(samples, list) or not samples:
            raise MicroSourceError("CLOCK_PROOF_SAMPLES")
        if any(
            not isinstance(x, dict)
            or type(x.get("wall_ms")) is not int
            or type(x.get("monotonic_ns")) is not int
            for x in samples
        ):
            raise MicroSourceError("CLOCK_PROOF_SAMPLE_SCHEMA")
        usable = proof["usable_at_ms"]
        elapsed = proof["usable_monotonic_ns"] - proof["started_monotonic_ns"]
        if (
            proof.get("schema") != "scalp7.actual_source_clock_barrier.v3"
            or proof.get("state") != "USABLE_AFTER_ACTUAL_CLOCK_BARRIER"
            or proof["native_ts_ms"] != maximum
            or proof["received_at_ms"] != pending["received_at_ms"]
            or proof["max_wait_ms"] != 5000
            or proof["started_at_ms"] < pending["received_at_ms"]
            or maximum - proof["started_at_ms"] > 5000
            or not max(maximum, pending["received_at_ms"], proof["started_at_ms"])
            <= usable
            <= recorded
            or not 0 <= elapsed <= 5_000_000_000
            or not isinstance(proof.get("waited_ms"), (int, float))
            or not math.isclose(
                float(proof["waited_ms"]), elapsed / 1_000_000, abs_tol=1e-9
            )
            or samples[0]
            != {
                "wall_ms": proof["started_at_ms"],
                "monotonic_ns": proof["started_monotonic_ns"],
            }
            or samples[-1]
            != {"wall_ms": usable, "monotonic_ns": proof["usable_monotonic_ns"]}
            or any(
                b["wall_ms"] < a["wall_ms"] or b["monotonic_ns"] < a["monotonic_ns"]
                for a, b in zip(samples, samples[1:])
            )
            or any(
                proof.get(k) is not False
                for k in (
                    "native_timestamp_rewritten",
                    "receipt_timestamp_rewritten",
                    "clock_offset_or_tolerance_applied",
                )
            )
        ):
            raise MicroSourceError("CLOCK_PROOF_INVALID")
        signals = []
        symbol = pending["symbol"]
        for event in pending["events"]:
            timestamp = event["T"]
            if timestamp < self.frozen_at_ms:
                continue
            if timestamp < self.last_source_ms.get(symbol, self.frozen_at_ms):
                raise MicroSourceError("TRADE_NATIVE_TIME_REVERSED")
            self.last_source_ms[symbol] = timestamp
            signal = self._observe(
                symbol,
                timestamp,
                float(event["p"]),
                usable,
                pending["raw_record_sha256"],
            )
            if signal:
                signal["source_evidence"].update(
                    clock_admission_record_sha256=record["record_sha256"],
                    clock_proof=proof,
                    actual_transport_received_at_ms=pending["received_at_ms"],
                    source_clock_revision="V3_ACTUAL_BARRIER",
                )
                signals.append(signal)
        self.pending_clock = None
        self.last_clock_usable_ms = usable
        self.status = (
            "VALID_FRESH_PRICE_SEQUENCE"
            if signals
            else "OBSERVED_CLOCK_ADMITTED_NO_SIGNAL"
        )
        return signals
