"""One bounded read of existing BTC/ETH public 5s BID/ASK, never a trade fill.

The producer belongs to the preexisting WS v2 service. This module NEVER
creates a socket, order, credential access, network request or new data writer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

WS_V2_HISTORY = Path("/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl")
WS_V2_HEARTBEAT = Path(
    "/home/z/z/ledger/production_bingx_ws_microstructure_heartbeat_v2.json"
)
SUPPORTED = frozenset(("BTC-USDT", "ETH-USDT"))


def observe(
    symbol: str,
    *,
    decision_ts_ms: int,
    read_at_ms: int,
    history: Path = WS_V2_HISTORY,
    heartbeat: Path = WS_V2_HEARTBEAT,
) -> dict[str, Any]:
    if symbol not in SUPPORTED:
        return {
            "state": "HOLD_SYMBOL_HAS_NO_APPROVED_WS_BOOK",
            "symbol": symbol,
            "hypothetical_virtual_fill": False,
        }
    hb_bytes = heartbeat.read_bytes()
    hb = json.loads(hb_bytes)
    if (
        hb.get("order_authority") != "BLOCKED"
        or hb.get("exchange_order_submitted") is not False
        or hb.get("execution_authority") != "NONE"
        or sorted(hb.get("symbols", [])) != sorted(SUPPORTED)
        or read_at_ms - int(hb.get("updated_at_ms", -1)) > 10_000
        or int(hb.get("updated_at_ms", -1)) > read_at_ms
        or hb.get("streams", {}).get("depth", {}).get("connected") is not True
    ):
        return {"state": "HOLD_WS_HEARTBEAT_NOT_LIVE_OR_ORDER_ISOLATED"}
    # Read an appended tail, NOT the existing multi-GB historical ledger.
    with history.open("rb") as source:
        size = source.seek(0, 2)
        seek_from = max(0, size - 64 * 1024)
        source.seek(seek_from)
        raw = source.read()
    lines = raw.splitlines()
    if seek_from > 0:
        lines = lines[1:]  # first line is a partial previous JSONL record
    candidates = []
    for raw_line in lines:
        try:
            row = json.loads(raw_line)
        except (ValueError, UnicodeDecodeError):
            continue
        if row.get("symbol") != symbol:
            continue
        candle_end = int(row.get("bucket_end_ms", 0))
        if not (decision_ts_ms <= candle_end <= read_at_ms):
            continue
        if read_at_ms - candle_end > 15_000:
            continue
        if (
            row.get("order_authority") != "BLOCKED"
            or row.get("execution_authority") != "NONE"
            or row.get("exchange_order_submitted") is not False
            or int(row.get("depth_messages", 0)) < 1
        ):
            continue
        bid, ask = float(row.get("best_bid_last") or 0), float(
            row.get("best_ask_last") or 0
        )
        if not (0 < bid <= ask):
            continue
        candidates.append((candle_end, bid, ask, raw_line))
    if not candidates:
        return {
            "state": "HOLD_NO_TIMESTAMPED_WS_QUOTE_AFTER_NATIVE_SIGNAL",
            "symbol": symbol,
            "hypothetical_virtual_fill": False,
        }
    ts, bid, ask, source_line = max(candidates, key=lambda x: x[0])
    return {
        "schema": "zel.k117.delayed_quote_observation_only.v1",
        "state": "PASS_REAL_EXISTING_WS_BID_ASK_MARK_NOT_ORIGINAL_OPEN_FILL",
        "symbol": symbol,
        "source_bucket_end_ms": ts,
        "native_decision_ts_ms": decision_ts_ms,
        "observed_at_ms": read_at_ms,
        "asof_not_native_next_open": True,
        "best_bid_observed": bid,
        "best_ask_observed": ask,
        "spread_bps": (ask - bid) / ((ask + bid) / 2) * 10_000,
        "quote_line_sha256": hashlib.sha256(source_line).hexdigest(),
        "heartbeat_sha256": hashlib.sha256(hb_bytes).hexdigest(),
        "hypothetical_virtual_fill": False,
        "order_calls": 0,
        "funding_actual": False,
        "live_authority": "BLOCKED",
    }
