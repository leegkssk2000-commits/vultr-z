"""Read an existing BingX WS BBO strictly AFTER a 4h signal decision.

Proof of a quote mark, NOT proof of original next-open fill or NAV PnL.
No exchange client, new WS connection, collector, credentials or orders.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BOOK = Path("/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl")
HEARTBEAT = Path(
    "/home/z/z/ledger/production_bingx_ws_microstructure_heartbeat_v2.json"
)
SUPPORTED = frozenset(("BTC-USDT", "ETH-USDT"))


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def observe(
    symbol: str,
    *,
    decision_ts_ms: int,
    read_at_ms: int,
    history: Path = BOOK,
    heartbeat: Path = HEARTBEAT,
) -> dict[str, Any]:
    """At most one already-recorded quote; fail closed on missing/stale inputs."""
    if symbol not in SUPPORTED:
        return {"state": "HOLD_NO_EXISTING_WS_QUOTE_FOR_SYMBOL", "symbol": symbol}
    if decision_ts_ms <= 0 or read_at_ms < decision_ts_ms:
        return {"state": "HOLD_INVALID_DECISION_CLOCK", "symbol": symbol}
    try:
        hb_raw = heartbeat.read_bytes()
        hb = json.loads(hb_raw)
        heartbeat_ms = int(hb["updated_at_ms"])
        if (
            hb.get("order_authority") != "BLOCKED"
            or hb.get("execution_authority") != "NONE"
            or hb.get("exchange_order_submitted") is not False
            or sorted(hb.get("symbols", [])) != sorted(SUPPORTED)
            or not 0 <= read_at_ms - heartbeat_ms <= 10_000
            or hb.get("streams", {}).get("depth", {}).get("connected") is not True
        ):
            return {
                "state": "HOLD_WS_NOT_LIVE_OR_ORDER_ISOLATION_UNKNOWN",
                "symbol": symbol,
            }
        with history.open("rb") as f:
            length = f.seek(0, 2)
            off = max(0, length - 65536)
            f.seek(off)
            blob = f.read()
        lines = blob.splitlines()
        if off:
            lines = lines[1:]
        eligible = []
        for line in lines:
            try:
                x = json.loads(line)
                ts = int(x.get("bucket_end_ms", 0))
                if (
                    x.get("symbol") != symbol
                    or not decision_ts_ms <= ts <= read_at_ms
                    or read_at_ms - ts > 15_000
                    or x.get("order_authority") != "BLOCKED"
                    or x.get("execution_authority") != "NONE"
                    or x.get("exchange_order_submitted") is not False
                    or int(x.get("depth_messages", 0)) < 1
                ):
                    continue
                bid = float(x["best_bid_last"])
                ask = float(x["best_ask_last"])
                if not 0 < bid <= ask:
                    continue
                eligible.append((ts, bid, ask, line))
            except (TypeError, ValueError, KeyError, OverflowError):
                continue
        if not eligible:
            return {"state": "HOLD_NO_POST_DECISION_QUOTE", "symbol": symbol}
        ts, bid, ask, quoted_raw = max(eligible, key=lambda y: y[0])
        return {
            "state": "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL",
            "symbol": symbol,
            "source_quote_ts_ms": ts,
            "native_signal_decision_ts_ms": decision_ts_ms,
            "observed_at_ms": read_at_ms,
            "best_bid": bid,
            "best_ask": ask,
            "spread_bps": (ask - bid) / ((ask + bid) / 2) * 10000,
            "original_next_open_fill_verified": False,
            "real_trade": False,
            "virtual_fill": False,
            "order_calls": 0,
            "source_quote_sha256": digest(quoted_raw),
            "source_heartbeat_sha256": digest(hb_raw),
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {"state": "HOLD_WS_SOURCE_UNAVAILABLE_OR_MALFORMED", "symbol": symbol}
