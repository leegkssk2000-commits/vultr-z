from __future__ import annotations

import importlib.util
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("zel_bingx_btc_regime_event_dataset_v1.py")
SPEC = importlib.util.spec_from_file_location("zel_btc_regime_v1", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("COLLECTOR_IMPORT_FAILED")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def request_chunk_source_gap_safe(
    *,
    base_url: str,
    endpoint: str,
    source_header: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    attempts: int = 5,
) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": collector.CHUNK_LIMIT,
    }
    request = urllib.request.Request(
        f"{base_url}{endpoint}?{urllib.parse.urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": f"{collector.VERSION}_SOURCE_GAP_SAFE",
            "X-SOURCE-KEY": source_header,
        },
    )
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read())
            normalized: list[dict[str, Any]] = []
            for raw in collector.extract_rows(payload):
                try:
                    normalized.append(collector.normalize_row(raw))
                except RuntimeError:
                    # Invalid exchange-origin candles are omitted and become explicit
                    # missing intervals in collect_range. They are never repaired,
                    # interpolated, forward-filled, or synthesized.
                    continue
            return sorted(normalized, key=lambda row: int(row["timestamp_ms"]))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            if attempt == attempts:
                break
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(
        f"BINGX_REQUEST_FAILED:{symbol}:{interval}:{start_ms}:{end_ms}:{last_error}"
    )


collector.request_chunk = request_chunk_source_gap_safe

if __name__ == "__main__":
    raise SystemExit(collector.main())
