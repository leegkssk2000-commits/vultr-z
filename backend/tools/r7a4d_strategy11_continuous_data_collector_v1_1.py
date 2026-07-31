from __future__ import annotations

import json
import math
import urllib.parse
from typing import Any

from backend.tools import r7a4d_strategy11_continuous_data_collector_v1 as collector

VERSION = "R7A4D_STRATEGY11_CONTINUOUS_DATA_COLLECTOR_V1_1"
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
FUNDING_ENDPOINT = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"


def first_expected_funding_ms(start_ms: int) -> int:
    return int(math.ceil(start_ms / FUNDING_INTERVAL_MS) * FUNDING_INTERVAL_MS)


def funding_event_expected(start_ms: int, end_ms: int) -> bool:
    return first_expected_funding_ms(start_ms) <= end_ms


def fetch_funding_gap_aware(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict[str, Any]], str]:
    query = urllib.parse.urlencode({
        "symbol": symbol[:-4] + "-USDT",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    })
    payload = collector.request_json(FUNDING_ENDPOINT + "?" + query)
    if payload.get("code") not in (None, 0, "0"):
        raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
    rows = [
        item
        for item in (collector.parse_funding(row) for row in collector.payload_rows(payload))
        if item is not None
    ]
    rows = sorted(
        {int(row["timestamp_ms"]): row for row in rows}.values(),
        key=lambda row: int(row["timestamp_ms"]),
    )
    rows = [row for row in rows if start_ms <= int(row["timestamp_ms"]) <= end_ms]
    if not rows and funding_event_expected(start_ms, end_ms):
        raise RuntimeError(
            "EXPECTED_FUNDING_EVENT_MISSING:"
            f"{symbol}:{first_expected_funding_ms(start_ms)}:{end_ms}"
        )
    return rows, FUNDING_ENDPOINT


def main() -> int:
    collector.VERSION = VERSION
    collector.FUNDING_ENDPOINTS = (FUNDING_ENDPOINT,)
    collector.fetch_funding = fetch_funding_gap_aware
    return collector.main()


if __name__ == "__main__":
    raise SystemExit(main())
