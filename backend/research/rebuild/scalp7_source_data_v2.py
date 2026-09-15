"""Gap-preserving Scalp7 source loader; no economic or execution authority.

Only complete UTC 15m/30m buckets are emitted. Historical availability is a
bar-boundary model, not evidence of historical network receipt. Unknown volume
units stay unknown; callers must not turn them into size/notional features.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.research.rebuild.economic7_canonical_history_v1 import (
    csv_gzip,
    immutable_bytes,
    json_bytes,
    normalize_row,
    verify_daily_receipt,
)

MINUTE_MS = 60_000
SOURCE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
MANIFEST_HASHES = {
    "canonical_12m/MANIFEST.json": "fc7787854399348856ba13df5961c29af2ddc8655e162135cd44603b20a562c3",
    "canonical_gapday_prefix/MANIFEST.json": "9ffef229544bdc7ec78c54dda6545565e64ba6757970844458538eadc2b4515c",
    "canonical_postgap_20260213/MANIFEST.json": "bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7",
}
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
COLS = [
    "open_ts_ms",
    "close_ts_ms",
    "available_ts_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "segment_id",
]


class SourceDataError(RuntimeError):
    """Source or cache evidence violates its frozen contract."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise SourceDataError("SOURCE_PATH_OUTSIDE_ROOT")
    return path


def _check_hash(path: Path, expected: str) -> None:
    if sha_file(path) != expected:
        raise SourceDataError(f"SOURCE_HASH_MISMATCH:{path.name}")


def verify_time_witness(directory: str | Path) -> dict[str, Any]:
    """Require actual within-minute and after-close responses for all symbols.

    This establishes observed endpoint semantics on the witness date. Extension
    to historical responses is explicitly an inference, not a provider guarantee.
    """
    directory = Path(directory)
    summaries = []
    for symbol in SYMBOLS:
        rows = []
        receipts = []
        for phase in ("first", "closed"):
            stem = f"{symbol}_live_1m_{phase}"
            receipt_path = directory / (stem + ".receipt.json")
            receipt = json.loads(receipt_path.read_bytes())
            if receipt.get("http_status") != 200:
                raise SourceDataError("TIME_WITNESS_HTTP")
            query = receipt["query"]
            if (
                query.get("symbol") != symbol
                or query.get("interval") != "1m"
                or query.get("timeZone") != 0
                or receipt["url"].split("?")[0] != SOURCE
            ):
                raise SourceDataError("TIME_WITNESS_IDENTITY")
            body_path = _safe_path(directory, receipt["body_path"])
            _check_hash(body_path, receipt["body_sha256"])
            payload = json.loads(body_path.read_bytes())
            if str(payload.get("code")) != "0" or not payload.get("data"):
                raise SourceDataError("TIME_WITNESS_RESPONSE")
            rows.append([normalize_row(row) for row in payload["data"]])
            receipts.append(receipt)
        first = max(rows[0], key=lambda row: row["timestamp_ms"])
        opening = first["timestamp_ms"]
        before = receipts[0]
        if (
            not opening
            <= before["requested_at_ms"]
            <= before["received_at_ms"]
            < opening + MINUTE_MS
        ):
            raise SourceDataError("TIME_WITNESS_NOT_WITHIN_OPEN_MINUTE")
        finals = [row for row in rows[1] if row["timestamp_ms"] == opening]
        if len(finals) != 1 or receipts[1]["requested_at_ms"] < opening + MINUTE_MS:
            raise SourceDataError("TIME_WITNESS_NOT_AFTER_CLOSE")
        final = finals[0]
        if (
            first["open"] != final["open"]
            or float(first["high"]) > float(final["high"])
            or float(first["low"]) < float(final["low"])
            or all(first[field] == final[field] for field in ("high", "low", "close"))
        ):
            raise SourceDataError("TIME_WITNESS_PREFIX_FINAL_MISMATCH")
        summaries.append(
            {
                "symbol": symbol,
                "open_ts_ms": opening,
                "first_received_at_ms": before["received_at_ms"],
                "final_received_at_ms": receipts[1]["received_at_ms"],
                "body_hashes": [r["body_sha256"] for r in receipts],
            }
        )
    return {
        "state": "OBSERVED_OBJECT_TIME_OPEN",
        "source": SOURCE,
        "interval": "1m",
        "witnesses": summaries,
        "historical_extension": "SAME_ENDPOINT_SCHEMA_CONTINUITY_INFERENCE",
        "historical_delivery_latency": "UNOBSERVED",
        "volume_units": "UNKNOWN",
    }


def aggregate_minutes(
    frame: pd.DataFrame, tf_min: int, *, observed: bool = False
) -> pd.DataFrame:
    """Aggregate each complete UTC bucket; omit partials and reset after gaps.

    For fresh observed rows, received_at_ms is mandatory and actual availability
    is max(bar boundary, all constituent receipt times). Out-of-order/duplicate
    input is rejected instead of silently sorting or deduplicating it.
    """
    if tf_min not in (15, 30):
        raise SourceDataError("CURRENT_SCALP7_REQUIRES_15M_OR_30M")
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns) or frame.empty:
        raise SourceDataError("EMPTY_OR_INCOMPLETE_MINUTE_SOURCE")
    raw = frame.copy()
    numeric = raw[list(required)].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise SourceDataError("NONFINITE_SOURCE")
    ts = numeric["timestamp_ms"].to_numpy(dtype=float)
    if np.any(ts != np.floor(ts)) or np.any(ts < 0) or np.any(ts % MINUTE_MS):
        raise SourceDataError("SOURCE_OFF_UTC_MINUTE_GRID")
    if np.any(np.diff(ts) <= 0):
        raise SourceDataError("SOURCE_DUPLICATE_OR_OUT_OF_ORDER")
    if (
        (numeric[["open", "high", "low", "close"]] <= 0).any().any()
        or (numeric["volume"] < 0).any()
        or (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()
        or (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise SourceDataError("SOURCE_OHLC_OR_VOLUME_RANGE")
    raw[list(required)] = numeric
    interval = tf_min * MINUTE_MS
    raw["_bucket"] = (numeric["timestamp_ms"].astype("int64") // interval) * interval
    grouped = raw.groupby("_bucket", sort=True)
    counts = grouped["timestamp_ms"].count()
    opens = grouped["timestamp_ms"].min()
    ends = grouped["timestamp_ms"].max()
    complete = (
        (counts == tf_min)
        & (opens == counts.index)
        & (ends == counts.index + interval - MINUTE_MS)
    )
    out = (
        grouped.agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .loc[complete]
        .reset_index()
    )
    out = out.rename(columns={"_bucket": "open_ts_ms"})
    out["open_ts_ms"] = out["open_ts_ms"].astype("int64")
    out["close_ts_ms"] = out["open_ts_ms"] + interval
    out["available_ts_ms"] = out["close_ts_ms"]
    if observed:
        if "received_at_ms" not in raw:
            raise SourceDataError("FRESH_RECEIPT_TIME_REQUIRED")
        received = pd.to_numeric(raw["received_at_ms"], errors="raise")
        if (
            not np.isfinite(received.to_numpy(dtype=float)).all()
            or (received < raw["timestamp_ms"] + MINUTE_MS).any()
            or (received % 1 != 0).any()
        ):
            raise SourceDataError("FRESH_UNCLOSED_OR_INVALID_RECEIPT")
        raw["received_at_ms"] = received.astype("int64")
        actual = raw.groupby("_bucket")["received_at_ms"].max()
        out["available_ts_ms"] = np.maximum(
            out["close_ts_ms"].to_numpy(), actual.loc[out["open_ts_ms"]].to_numpy()
        )
    out["segment_id"] = (
        out["open_ts_ms"].diff().ne(interval).cumsum().astype("int64") - 1
    )
    out = out[COLS]
    gap_rows = np.flatnonzero(np.diff(ts) != MINUTE_MS)
    out.attrs = {
        "timeframe_minutes": tf_min,
        "source": SOURCE,
        "availability_basis": (
            "ACTUAL_CONSTITUENT_RECEIPTS"
            if observed
            else "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY"
        ),
        "volume_units": "UNKNOWN",
        "synthetic_fill": False,
        "incomplete_buckets": [int(x) for x in counts.index[~complete]],
        "minute_gaps": [
            {
                "start_ms": int(ts[i] + MINUTE_MS),
                "end_exclusive_ms": int(ts[i + 1]),
                "missing_minutes": int((ts[i + 1] - ts[i]) / MINUTE_MS - 1),
            }
            for i in gap_rows
        ],
        "source_minutes": len(raw),
    }
    return out


def _inventory(root: Path, expected: Mapping[str, str]) -> dict[str, str]:
    inventory = {}
    for name, digest in expected.items():
        path = _safe_path(root, name)
        _check_hash(path, digest)
        inventory[name] = digest
    for segment in ("canonical_12m", "canonical_postgap_20260213"):
        base = root / segment
        for sub, pattern in (
            ("daily_receipts", "*.json"),
            ("requests", "*.receipt.json"),
            ("requests", "*.body"),
            ("normalized_chunks", "*.csv.gz"),
            ("1m", "*.csv.gz"),
        ):
            for path in sorted((base / sub).rglob(pattern)):
                inventory[str(path.relative_to(root))] = sha_file(path)
    for path in sorted((root / "canonical_gapday_prefix").glob("*/1m.csv.gz")):
        inventory[str(path.relative_to(root))] = sha_file(path)
    return inventory


def _load_verified_minutes(root: Path) -> dict[str, pd.DataFrame]:
    parts: dict[str, list[pd.DataFrame]] = {s: [] for s in SYMBOLS}
    for segment in ("canonical_12m", "canonical_postgap_20260213"):
        base = root / segment
        manifest = json.loads((base / "MANIFEST.json").read_bytes())
        if manifest["source"] != SOURCE or manifest["source_interval"] != "1m":
            raise SourceDataError("MANIFEST_SOURCE_IDENTITY")
        for symbol in SYMBOLS:
            receipts = sorted((base / "daily_receipts" / symbol).glob("*.json"))
            expected_coverage = next(
                x for x in manifest["symbols_coverage"] if x["symbol"] == symbol
            )
            if len(receipts) != expected_coverage["completed_days_or_boundary_parts"]:
                raise SourceDataError("DAILY_RECEIPT_COUNT_MISMATCH")
            count = 0
            for path in receipts:
                receipt = json.loads(path.read_bytes())
                verify_daily_receipt(
                    base,
                    receipt,
                    symbol,
                    receipt["start_ms"],
                    receipt["end_exclusive_ms"],
                )
                artifact = receipt["artifacts"][0]
                frame = pd.read_csv(
                    _safe_path(base, artifact["path"]), float_precision="round_trip"
                )
                count += len(frame)
                parts[symbol].append(frame)
            if count != expected_coverage["rows_1m"]:
                raise SourceDataError("MANIFEST_ROW_COUNT_MISMATCH")
    prefix = root / "canonical_gapday_prefix"
    manifest = json.loads((prefix / "MANIFEST.json").read_bytes())
    for info in manifest["symbols"]:
        rows: list[dict[str, Any]] = []
        for source in info["sources"]:
            source_path = _safe_path(root, source["receipt"])
            _check_hash(source_path, source["receipt_sha256"])
            receipt = json.loads(source_path.read_bytes())
            if receipt["source"] != SOURCE or receipt["symbol"] != info["symbol"]:
                raise SourceDataError("PREFIX_SOURCE_IDENTITY")
            body = _safe_path(root / "canonical_12m", receipt["body_path"])
            _check_hash(body, source["body_sha256"])
            payload = json.loads(body.read_bytes())
            if str(payload.get("code")) != "0":
                raise SourceDataError("PREFIX_SOURCE_REJECTED")
            rows.extend(
                normalize_row(row)
                for row in payload["data"]
                if manifest["start_ms"]
                <= int(row["time"])
                < manifest["end_exclusive_ms"]
            )
        rows.sort(key=lambda row: row["timestamp_ms"])
        artifact = info["artifacts"][0]
        path = _safe_path(root, artifact["file"])
        _check_hash(path, artifact["sha256"])
        if path.read_bytes() != csv_gzip(rows):
            raise SourceDataError("PREFIX_RAW_BINDING_MISMATCH")
        if len(rows) != info["rows_1m"] or [r["timestamp_ms"] for r in rows] != list(
            range(manifest["start_ms"], manifest["end_exclusive_ms"], MINUTE_MS)
        ):
            raise SourceDataError("PREFIX_GAP_OR_DUPLICATE")
        parts[info["symbol"]].append(pd.read_csv(path, float_precision="round_trip"))
    return {
        symbol: pd.concat(frames, ignore_index=True)
        .sort_values("timestamp_ms")
        .reset_index(drop=True)
        for symbol, frames in parts.items()
    }


def load_candles(
    root: str | Path,
    tf_min: int,
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
    time_authority: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load exact preserved archives, verify evidence, then cache validated bars.

    time_authority is the directory holding the twelve raw 1m time witnesses.
    Default discovery is the committed campaign directory next to this module.
    An optional expected_source_hashes map may additionally pin the full inventory.
    """
    if tf_min not in (15, 30):
        raise SourceDataError("CURRENT_SCALP7_REQUIRES_15M_OR_30M")
    root = Path(root).resolve()
    witness_dir = (
        Path(time_authority)
        if time_authority
        else Path(__file__).resolve().parents[3]
        / "research/campaigns/scalp7_20260915/source_time_v2"
    )
    witness = verify_time_witness(witness_dir)
    inventory = _inventory(root, MANIFEST_HASHES)
    if expected_source_hashes:
        for name, digest in expected_source_hashes.items():
            if inventory.get(name) != digest:
                raise SourceDataError("EXPECTED_SOURCE_INVENTORY_MISMATCH")
    key_data = {
        "source_inventory": inventory,
        "time_witness": witness,
        "code_sha256": sha_file(Path(__file__)),
        "timeframe_minutes": tf_min,
    }
    key = hashlib.sha256(json_bytes(key_data)).hexdigest()
    cache = Path(cache_dir) / key if cache_dir else None
    if cache and (cache / "RECEIPT.json").exists():
        receipt = json.loads((cache / "RECEIPT.json").read_bytes())
        if receipt["key"] != key:
            raise SourceDataError("CACHE_IDENTITY_MISMATCH")
        output = {}
        for symbol in SYMBOLS:
            path = cache / (symbol + ".csv.gz")
            _check_hash(path, receipt["outputs"][symbol]["sha256"])
            frame = pd.read_csv(path, float_precision="round_trip")
            frame.attrs = receipt["outputs"][symbol]["attrs"]
            output[symbol] = frame
        return output
    minutes = _load_verified_minutes(root)
    output = {}
    receipts = {}
    for symbol, frame in minutes.items():
        candle = aggregate_minutes(frame, tf_min)
        candle.attrs.update(
            {
                "source_inventory_sha256": hashlib.sha256(
                    json_bytes(inventory)
                ).hexdigest(),
                "time_witness": witness,
                "symbol": symbol,
                "source_rows_are_genuine": True,
                "price_only_history_research": "ELIGIBLE_WITH_EXPLICIT_TIME_INFERENCE",
                "fresh_evidence": False,
                "order_authority": "BLOCKED",
            }
        )
        output[symbol] = candle
        if cache:
            raw = gzip.compress(candle.to_csv(index=False).encode(), mtime=0)
            immutable_bytes(cache / (symbol + ".csv.gz"), raw)
            receipts[symbol] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "attrs": candle.attrs,
            }
    if cache:
        immutable_bytes(cache / "SOURCE_INVENTORY.json", json_bytes(inventory))
        immutable_bytes(
            cache / "RECEIPT.json", json_bytes({"key": key, "outputs": receipts})
        )
    return output
