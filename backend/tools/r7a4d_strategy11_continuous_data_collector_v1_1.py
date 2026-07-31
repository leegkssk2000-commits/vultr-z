from __future__ import annotations

import json
import math
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.tools import r7a4d_strategy11_continuous_data_collector_v1 as collector

VERSION = "R7A4D_STRATEGY11_CONTINUOUS_DATA_COLLECTOR_V1_1"
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
FUNDING_ENDPOINT = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"
_ORIGINAL_ATOMIC_JSON = collector.atomic_json


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


def atomic_json_preserve_funding_source(path: Path, payload: Mapping[str, Any]) -> None:
    updated = dict(payload)
    if path.parent.name == "funding" and updated.get("source") is None and path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        source = existing.get("source") if isinstance(existing, Mapping) else None
        if source:
            updated["source"] = source
    _ORIGINAL_ATOMIC_JSON(path, updated)


def _argument_value(flag: str) -> str:
    try:
        index = sys.argv.index(flag)
        return sys.argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"ARGUMENT_MISSING:{flag}") from exc


def synchronize_manifest_funding_sources() -> None:
    root = Path(_argument_value("--data-root")).resolve()
    status_out = Path(_argument_value("--status-out")).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("MANIFEST_NOT_OBJECT")
    symbols = manifest.get("symbols")
    if not isinstance(symbols, list):
        raise RuntimeError("MANIFEST_SYMBOLS_NOT_LIST")
    for row in symbols:
        if not isinstance(row, dict):
            raise RuntimeError("MANIFEST_SYMBOL_NOT_OBJECT")
        symbol = str(row.get("symbol") or "")
        funding_path = root / "funding" / f"{symbol}.json"
        funding = json.loads(funding_path.read_text(encoding="utf-8"))
        source = funding.get("source") if isinstance(funding, Mapping) else None
        if not source:
            raise RuntimeError(f"FUNDING_SOURCE_MISSING:{symbol}")
        row["funding_source"] = source
    _ORIGINAL_ATOMIC_JSON(manifest_path, manifest)
    _ORIGINAL_ATOMIC_JSON(status_out, manifest)


def main() -> int:
    collector.VERSION = VERSION
    collector.FUNDING_ENDPOINTS = (FUNDING_ENDPOINT,)
    collector.fetch_funding = fetch_funding_gap_aware
    collector.atomic_json = atomic_json_preserve_funding_source
    result = collector.main()
    if result == 0:
        synchronize_manifest_funding_sources()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
