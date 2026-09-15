"""Frozen observed-trade-price micro sleeve on 15m decisions.

This child uses actual wire-preserved trade prices only. It makes no L2,
quantity, aggressor-side, full-tape, or legacy Micro5m performance claim.
"""

from __future__ import annotations

import base64
import math
from datetime import datetime
from typing import Any

from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    decode_message,
    digest,
)

INTERVAL_MS = 900_000
IDENTITY = "MICRO_OBSERVED_TRADE_RECLAIM_15M_V2"


class MicroSourceError(RuntimeError):
    """The observed source is ineligible; no signal may be emitted."""


def utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise MicroSourceError("SOURCE_UTC_TIME_REQUIRED")
    return int(parsed.timestamp() * 1000)


class MicroDecision:
    """Verify the exact raw chain after a frozen checkpoint and observe prices.

    A valid sequence is previous-window-high break -> retest -> reclaim in the
    next 15m window, without previous-window-low invalidation. The signal is
    emitted only after that window closes and a subsequent observed trade arrives.
    Resetting a connection discards setup/context; no cross-connection sequence.
    """

    def __init__(
        self,
        *,
        frozen_at_ms: int,
        initial_seq: int,
        initial_hash: str,
        identity_sha256: str,
    ):
        self.frozen_at_ms = frozen_at_ms
        self.local_seq = initial_seq
        self.tail_hash = initial_hash
        self.identity_sha256 = identity_sha256
        self.connection_id: str | None = None
        self.windows: dict[str, dict[str, Any]] = {}
        self.previous: dict[str, dict[str, Any]] = {}
        self.last_source_ms: dict[str, int] = {}
        self.last_received_ms = frozen_at_ms
        self.eligible_from_ms = (
            (frozen_at_ms + INTERVAL_MS - 1) // INTERVAL_MS
        ) * INTERVAL_MS
        self.segment_id = 0
        self.status = "WARMUP_FRESH_OBSERVED_WINDOWS"
        self.emitted: set[str] = set()

    def _reset(self, status: str) -> None:
        self.windows.clear()
        self.previous.clear()
        self.last_source_ms.clear()
        self.segment_id += 1
        self.status = status

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
        signals = []
        for event in events:
            if not isinstance(event, dict):
                self._reset("HOLD_TRADE_MAPPING_REQUIRED")
                raise MicroSourceError("TRADE_MAPPING_REQUIRED")
            if event.get("s") != symbol or type(event.get("T")) is not int:
                self._reset("HOLD_TRADE_IDENTITY")
                raise MicroSourceError("TRADE_IDENTITY")
            timestamp = event["T"]
            if timestamp < self.frozen_at_ms:
                continue
            try:
                if isinstance(event.get("p"), bool):
                    raise ValueError("boolean price")
                price = float(event["p"])
            except (KeyError, TypeError, ValueError) as exc:
                self._reset("HOLD_INVALID_TRADE_PRICE")
                raise MicroSourceError("INVALID_TRADE_PRICE") from exc
            if (
                not math.isfinite(price)
                or price <= 0
                or timestamp > received
                or timestamp < self.last_source_ms.get(symbol, self.frozen_at_ms)
            ):
                self._reset("HOLD_TRADE_TIME_OR_PRICE")
                raise MicroSourceError("TRADE_TIME_OR_PRICE")
            self.last_source_ms[symbol] = timestamp
            signal = self._observe(
                symbol, timestamp, price, received, record["record_sha256"]
            )
            if signal:
                signals.append(signal)
        return signals

    def _observe(
        self, symbol: str, timestamp: int, price: float, received: int, source_hash: str
    ) -> dict[str, Any] | None:
        opening = timestamp // INTERVAL_MS * INTERVAL_MS
        current = self.windows.get(symbol)
        signal = None
        if current and opening > current["open_ts_ms"]:
            if opening == current["open_ts_ms"] + INTERVAL_MS:
                signal = self._finish(symbol, current, received, source_hash)
                if current["eligible_context"]:
                    self.previous[symbol] = current
                else:
                    self.previous.pop(symbol, None)
            else:
                self.previous.pop(symbol, None)
                self.status = "HOLD_MISSING_OBSERVED_WINDOW"
                self.segment_id += 1
                self.eligible_from_ms = opening + INTERVAL_MS
            current = None
        if current is None:
            prior = self.previous.get(symbol)
            current = {
                "open_ts_ms": opening,
                "high": price,
                "low": price,
                "last": price,
                "samples": 0,
                "state": "WAIT_BREAK",
                "retest_low": None,
                "prior_high": prior["high"] if prior else None,
                "prior_low": prior["low"] if prior else None,
                "rail": None,
                "direction": 0,
                "invalidation": None,
                "eligible_context": opening >= self.eligible_from_ms,
                "first_source_hash": source_hash,
                "last_source_hash": source_hash,
            }
            self.windows[symbol] = current
        current["samples"] += 1
        current["high"] = max(current["high"], price)
        current["low"] = min(current["low"], price)
        current["last"] = price
        current["last_source_hash"] = source_hash
        upper, lower = current["prior_high"], current["prior_low"]
        if upper is None or lower is None or upper <= lower:
            return signal
        if current["state"] == "WAIT_BREAK":
            if price > upper:
                current.update(
                    direction=1, rail=upper, invalidation=lower, state="BROKEN"
                )
            elif price < lower:
                current.update(
                    direction=-1, rail=lower, invalidation=upper, state="BROKEN"
                )
            return signal
        side, rail = current["direction"], current["rail"]
        if side * (price - current["invalidation"]) <= 0:
            current["state"] = "INVALIDATED"
        elif current["state"] == "BROKEN" and side * (price - rail) <= 0:
            current["state"] = "RETESTED"
            current["retest_low"] = price
        elif current["state"] in ("RETESTED", "RECLAIMED"):
            current["retest_low"] = (
                min(current["retest_low"], price)
                if side == 1
                else max(current["retest_low"], price)
            )
            current["state"] = "RECLAIMED" if side * (price - rail) > 0 else "RETESTED"
        return signal

    def _finish(
        self,
        symbol: str,
        current: dict[str, Any],
        received: int,
        boundary_source_hash: str,
    ) -> dict[str, Any] | None:
        if (
            not current["eligible_context"]
            or current["state"] != "RECLAIMED"
            or current["retest_low"] is None
            or current["direction"] * (current["last"] - current["retest_low"]) <= 0
        ):
            return None
        signal_ts = current["open_ts_ms"] + INTERVAL_MS
        setup_id = digest(
            {
                "identity": IDENTITY,
                "symbol": symbol,
                "open_ts_ms": current["open_ts_ms"],
                "rail": current["rail"],
                "frozen_at_ms": self.frozen_at_ms,
            }
        )
        if setup_id in self.emitted:
            return None
        self.emitted.add(setup_id)
        self.status = "VALID_FRESH_PRICE_SEQUENCE"
        return {
            "lane_id": "micro_edge",
            "lane": "micro_edge",
            "identity": IDENTITY,
            "timeframe_min": 15,
            "tf": 15,
            "symbol": symbol,
            "side": current["direction"],
            "setup_id": setup_id,
            "signal_open_ts_ms": current["open_ts_ms"],
            "decision_boundary_ts_ms": signal_ts,
            "signal_ts_ms": max(signal_ts, received),
            "available_ts_ms": max(signal_ts, received),
            "entry_rule": "FIRST_OBSERVED_QUOTE_AFTER_DECISION",
            "earliest_entry_ts_ms": max(signal_ts, received) + 1,
            "stop_price": current["retest_low"],
            "take_profit_price": None,
            "max_hold_bars": 4,
            "segment_id": self.segment_id,
            "invalidation": "OBSERVED_RETEST_EXTREME_FAILURE",
            "source_evidence": {
                "first_record_sha256": current["first_source_hash"],
                "last_record_sha256": current["last_source_hash"],
                "boundary_record_sha256": boundary_source_hash,
                "raw_identity_sha256": self.identity_sha256,
                "samples": current["samples"],
            },
            "source_scope": "OBSERVED_TRADE_PRICES_NOT_COMPLETE_TAPE",
            "l2_used": False,
            "l2_state": "UNUSED_SCHEMA_UNBOUND",
            "maker_flag_used": False,
            "quantity_units_used": False,
            "historical_or_legacy_credit": False,
            "order_authority": "BLOCKED",
        }
