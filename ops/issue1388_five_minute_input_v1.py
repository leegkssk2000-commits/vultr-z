"""Gap-safe five-minute research input adapter for Issue 1388.

This module deliberately leaves the hash-sealed Scalp7 15m/30m loader
unchanged.  It reuses that loader's verified immutable minute archive and
receipt checks, then emits complete UTC 5m buckets only.  It has no signal,
PnL, order, live, paper, or deployment authority.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild import scalp7_source_data_v2 as source
from backend.research.rebuild.economic7_canonical_history_v1 import json_bytes

FIVE_MINUTES = 5
INTERVAL_MS = FIVE_MINUTES * source.MINUTE_MS


def aggregate_five_minute(frame: pd.DataFrame) -> pd.DataFrame:
    """Return complete UTC 5m buckets and preserve every minute gap."""
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns) or frame.empty:
        raise source.SourceDataError("EMPTY_OR_INCOMPLETE_MINUTE_SOURCE")
    raw = frame.copy()
    numeric = raw[list(required)].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise source.SourceDataError("NONFINITE_SOURCE")
    timestamps = numeric["timestamp_ms"].to_numpy(dtype=float)
    if (
        np.any(timestamps != np.floor(timestamps))
        or np.any(timestamps < 0)
        or np.any(timestamps % source.MINUTE_MS)
    ):
        raise source.SourceDataError("SOURCE_OFF_UTC_MINUTE_GRID")
    if np.any(np.diff(timestamps) <= 0):
        raise source.SourceDataError("SOURCE_DUPLICATE_OR_OUT_OF_ORDER")
    if (
        (numeric[["open", "high", "low", "close"]] <= 0).any().any()
        or (numeric["volume"] < 0).any()
        or (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()
        or (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise source.SourceDataError("SOURCE_OHLC_OR_VOLUME_RANGE")
    raw[list(required)] = numeric
    raw["_bucket"] = (
        numeric["timestamp_ms"].astype("int64") // INTERVAL_MS
    ) * INTERVAL_MS
    grouped = raw.groupby("_bucket", sort=True)
    counts = grouped["timestamp_ms"].count()
    opens = grouped["timestamp_ms"].min()
    ends = grouped["timestamp_ms"].max()
    complete = (
        (counts == FIVE_MINUTES)
        & (opens == counts.index)
        & (ends == counts.index + INTERVAL_MS - source.MINUTE_MS)
    )
    result = (
        grouped.agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .loc[complete]
        .reset_index()
        .rename(columns={"_bucket": "open_ts_ms"})
    )
    result["open_ts_ms"] = result["open_ts_ms"].astype("int64")
    result["close_ts_ms"] = result["open_ts_ms"] + INTERVAL_MS
    result["available_ts_ms"] = result["close_ts_ms"]
    result["segment_id"] = (
        result["open_ts_ms"].diff().ne(INTERVAL_MS).cumsum().astype("int64") - 1
    )
    result = result[source.COLS]
    gap_rows = np.flatnonzero(np.diff(timestamps) != source.MINUTE_MS)
    result.attrs = {
        "timeframe_minutes": FIVE_MINUTES,
        "source": source.SOURCE,
        "availability_basis": "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "volume_units": "UNKNOWN",
        "synthetic_fill": False,
        "incomplete_buckets": [int(value) for value in counts.index[~complete]],
        "minute_gaps": [
            {
                "start_ms": int(timestamps[index] + source.MINUTE_MS),
                "end_exclusive_ms": int(timestamps[index + 1]),
                "missing_minutes": int(
                    (timestamps[index + 1] - timestamps[index]) / source.MINUTE_MS - 1
                ),
            }
            for index in gap_rows
        ],
        "source_minutes": len(raw),
    }
    return result


def load_five_minute_candles(
    root: str | Path,
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
    time_authority: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Verify the canonical archive and return all six symbols as 5m candles."""
    root = Path(root).resolve()
    witness_dir = (
        Path(time_authority)
        if time_authority
        else Path(__file__).resolve().parents[1]
        / "research/campaigns/scalp7_20260915/source_time_v2"
    )
    witness = source.verify_time_witness(witness_dir)
    inventory = source._inventory(root, source.MANIFEST_HASHES)
    if expected_source_hashes:
        for name, digest in expected_source_hashes.items():
            if inventory.get(name) != digest:
                raise source.SourceDataError("EXPECTED_SOURCE_INVENTORY_MISMATCH")
    inventory_sha256 = hashlib.sha256(json_bytes(inventory)).hexdigest()
    minutes = source._load_verified_minutes(root)
    output = {}
    for symbol, frame in minutes.items():
        candle = aggregate_five_minute(frame)
        candle.attrs.update(
            {
                "source_inventory_sha256": inventory_sha256,
                "time_witness": witness,
                "symbol": symbol,
                "source_rows_are_genuine": True,
                "price_only_history_research": "ELIGIBLE_WITH_EXPLICIT_TIME_INFERENCE",
                "fresh_evidence": False,
                "order_authority": "BLOCKED",
            }
        )
        output[symbol] = candle
    return output
