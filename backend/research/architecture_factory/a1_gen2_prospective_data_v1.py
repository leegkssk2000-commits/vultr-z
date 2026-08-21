#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ

INTERVAL_MS = {"1h": 3600_000, "4h": 4 * 3600_000, "1d": 24 * 3600_000}


def bars(symbol: str, interval: str) -> list[dict[str, float]]:
    """Fetch closed prospective bars without the frozen development cutoff."""
    tf_ms = INTERVAL_MS[interval]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    closed_before = (now_ms // tf_ms) * tf_ms
    all_rows: dict[int, dict[str, float]] = {}
    end = closed_before - 1
    for _ in range(3):
        payload = econ._req({
            "symbol": symbol,
            "interval": econ.INTERVAL_MAP[interval],
            "limit": 1000,
            "endTime": end,
        })
        page = sorted(econ._decode_rows(payload), key=lambda row: row["ts"])
        page = [row for row in page if int(row["ts"]) < closed_before]
        if not page:
            break
        for row in page:
            all_rows[int(row["ts"])] = row
        oldest = int(page[0]["ts"])
        if oldest >= end:
            break
        end = oldest - 1
        if len(page) < 900:
            break
    rows = [all_rows[key] for key in sorted(all_rows)]
    if not rows:
        raise RuntimeError(f"PROSPECTIVE_CLOSED_BARS_MISSING:{symbol}:{interval}")
    if int(rows[-1]["ts"]) >= closed_before:
        raise RuntimeError(f"OPEN_BAR_LEAK:{symbol}:{interval}")
    return rows

