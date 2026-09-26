"""Immutable canonical inputs, without signals, economics, caches or gap filling.

The runner must admit genuine FULL execution before calling load. Unknown
volume units remain unknown; last prices never become observed exchange marks.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from numbers import Integral
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_source_data_v2 as source

SCHEMA = "zel.scalp7.exact25_model_data.v1"
INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
MINUTE = 60_000
SNAPSHOT_POLICY = "DECISION_GRID_NEXT_OPEN_RETROSPECTIVE_PLUS_TERMINAL_CLOSE_V1"
SEGMENT_POLICY = "PREFIXED_CONTIGUOUS_MINUTE_SEGMENTS_WITH_CANONICAL_NUMERIC_IDS_V1"


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": source.sha_file(path)}


def _check(artifact: Mapping[str, Any]) -> Path:
    path = Path(artifact["path"]).resolve()
    if source.sha_file(path) != artifact["sha256"]:
        raise ValueError("MODEL_DATA_HASH_MISMATCH:" + str(path))
    return path


def _within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("MODEL_DATA_PATH_ESCAPE")
    return path


def canonical_manifest(
    *,
    canonical_root: str | Path,
    source_inventory_path: str | Path,
    time_authority_directory: str | Path,
    symbols: list[str],
    timeframe_min: int = 30,
) -> dict[str, Any]:
    """Read/hash existing metadata only; never load price rows or run models."""
    root = Path(canonical_root).resolve()
    witness = Path(time_authority_directory).resolve()
    inventory = _artifact(Path(source_inventory_path))
    if inventory["sha256"] != INVENTORY_SHA256:
        raise ValueError("UNRECOGNIZED_CANONICAL_INVENTORY")
    artifacts = [inventory]
    for relative, expected in source.MANIFEST_HASHES.items():
        artifact = _artifact(root / relative)
        if artifact["sha256"] != expected:
            raise ValueError("CANONICAL_MANIFEST_CHANGED")
        artifacts.append(artifact)
    witness_files: dict[str, str] = {}
    for symbol in source.SYMBOLS:
        for phase in ("first", "closed"):
            path = witness / f"{symbol}_live_1m_{phase}.receipt.json"
            receipt = json.loads(path.read_bytes())
            body = _within(witness, receipt["body_path"])
            for p in (path, body):
                a = _artifact(p)
                if p == body and a["sha256"] != receipt["body_sha256"]:
                    raise ValueError("TIME_WITNESS_BODY_CHANGED")
                witness_files[str(p.relative_to(witness))] = a["sha256"]
                artifacts.append(a)
    manifest = {
        "schema": SCHEMA,
        "data_kind": "GENUINE_RAW_HISTORY",
        "canonical_root": str(root),
        "canonical_roots": [
            str(root / x)
            for x in (
                "canonical_12m",
                "canonical_gapday_prefix",
                "canonical_postgap_20260213",
            )
        ],
        "source_inventory": inventory,
        "time_authority": {"directory": str(witness), "files": witness_files},
        "symbols": list(symbols),
        "timeframe_min": timeframe_min,
        "artifacts": artifacts,
        "loader": {"module": __name__, "function": "load"},
        "volume_units": "UNKNOWN",
        "price_basis": "LAST_PRICE",
        "availability_basis": "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "synthetic_fill": False,
        "fresh_evidence": False,
        "snapshot_policy": SNAPSHOT_POLICY,
        "segment_id_policy": SEGMENT_POLICY,
    }
    _contract(manifest, {})
    return manifest


def _contract(manifest: Mapping[str, Any], config: Mapping[str, Any]) -> list[str]:
    if manifest.get("schema") != SCHEMA:
        raise ValueError("MODEL_DATA_SCHEMA_REQUIRED")
    if manifest.get("data_kind") not in {"GENUINE_RAW_HISTORY", "SYNTHETIC_FIXTURE"}:
        raise ValueError("MODEL_DATA_KIND_REQUIRED")
    tf = manifest.get("timeframe_min")
    if type(tf) is not int or tf not in (15, 30):
        raise ValueError("MODEL_DATA_15M_OR_30M_REQUIRED")
    symbols = manifest.get("symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(s, str) for s in symbols)
        or len(set(symbols)) != len(symbols)
        or not set(symbols).issubset(source.SYMBOLS)
    ):
        raise ValueError("MODEL_DATA_SYMBOLS_REQUIRED")
    if "symbol" in config and symbols != [config["symbol"]]:
        raise ValueError("MODEL_DATA_CONFIG_SYMBOL_MISMATCH")
    if "symbols" in config and set(config["symbols"]) != set(symbols):
        raise ValueError("MODEL_DATA_CONFIG_UNIVERSE_MISMATCH")
    if manifest.get("volume_units") != "UNKNOWN":
        raise ValueError("CANONICAL_VOLUME_UNIT_UPGRADE_FORBIDDEN")
    if manifest.get("synthetic_fill") is not False:
        raise ValueError("GAP_FILL_FORBIDDEN")
    if manifest.get("fresh_evidence") is not False:
        raise ValueError("HISTORICAL_FRESH_CLAIM_FORBIDDEN")
    if (
        manifest.get("availability_basis")
        != "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY"
    ):
        raise ValueError("HISTORICAL_RECEIPT_CLOCK_UNPROVEN")
    if manifest.get("price_basis") != "LAST_PRICE":
        raise ValueError("CANONICAL_MARK_PRICE_UNAVAILABLE")
    if manifest.get("snapshot_policy") != SNAPSHOT_POLICY:
        raise ValueError("BOUNDARY_SNAPSHOT_POLICY_REQUIRED")
    if manifest.get("segment_id_policy") != SEGMENT_POLICY:
        raise ValueError("BOUND_SEGMENT_ID_POLICY_REQUIRED")
    return symbols


def _verify_artifacts(manifest: Mapping[str, Any]) -> dict[str, str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("IMMUTABLE_INPUT_ARTIFACTS_REQUIRED")
    pinned: dict[str, str] = {}
    for artifact in artifacts:
        path = str(_check(artifact))
        if path in pinned and pinned[path] != artifact["sha256"]:
            raise ValueError("CONFLICTING_ARTIFACT_BINDING")
        pinned[path] = artifact["sha256"]
    return pinned


def _pin(pinned: Mapping[str, str], path: Path, expected: str) -> None:
    if pinned.get(str(path.resolve())) != expected:
        raise ValueError("MISSING_INPUT_ARTIFACT_BINDING:" + str(path))


def _genuine(
    manifest: Mapping[str, Any], pinned: Mapping[str, str]
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    root = Path(manifest["canonical_root"]).resolve()
    item = manifest["source_inventory"]
    inventory_path = _check(item)
    if item["sha256"] != INVENTORY_SHA256:
        raise ValueError("UNRECOGNIZED_CANONICAL_INVENTORY")
    _pin(pinned, inventory_path, item["sha256"])
    expected = json.loads(inventory_path.read_bytes())
    actual = source._inventory(root, source.MANIFEST_HASHES)
    if actual != expected:
        raise ValueError("CANONICAL_SOURCE_INVENTORY_CHANGED")
    for relative, expected_sha in source.MANIFEST_HASHES.items():
        _pin(pinned, root / relative, expected_sha)
    authority = manifest["time_authority"]
    directory = Path(authority["directory"]).resolve()
    files = authority["files"]
    for relative, expected_sha in files.items():
        _pin(pinned, _within(directory, relative), expected_sha)
    for symbol in source.SYMBOLS:
        for phase in ("first", "closed"):
            receipt_path = directory / f"{symbol}_live_1m_{phase}.receipt.json"
            if str(receipt_path.relative_to(directory)) not in files:
                raise ValueError("UNPINNED_TIME_WITNESS_RECEIPT")
            receipt = json.loads(receipt_path.read_bytes())
            body = _within(directory, receipt["body_path"])
            if files.get(str(body.relative_to(directory))) != receipt["body_sha256"]:
                raise ValueError("UNPINNED_TIME_WITNESS_BODY")
    witness = source.verify_time_witness(directory)
    return source._load_verified_minutes(root), witness


def _fixture(
    manifest: Mapping[str, Any], pinned: Mapping[str, str]
) -> dict[str, pd.DataFrame]:
    if manifest.get("fixture_label") != "SYNTHETIC_UNIT_TEST_ONLY":
        raise ValueError("EXPLICIT_SYNTHETIC_FIXTURE_LABEL_REQUIRED")
    supplied = manifest.get("minute_artifacts", {})
    if set(supplied) != set(manifest["symbols"]):
        raise ValueError("FIXTURE_UNIVERSE_MISMATCH")
    result = {}
    for symbol, item in supplied.items():
        path = _check(item)
        _pin(pinned, path, item["sha256"])
        result[symbol] = pd.read_csv(path, float_precision="round_trip")
    return result


def _detail(raw: pd.DataFrame, attrs: Mapping[str, Any]) -> pd.DataFrame:
    # aggregate_minutes validates numeric ranges, UTC grid and chronology first.
    result = raw[["timestamp_ms", "open", "high", "low", "close", "volume"]].copy()
    result = result.rename(columns={"timestamp_ms": "open_ts_ms"})
    result["open_ts_ms"] = result["open_ts_ms"].astype("int64")
    for name in ("open", "high", "low", "close", "volume"):
        result[name] = pd.to_numeric(result[name], errors="raise")
    result["close_ts_ms"] = result["open_ts_ms"] + MINUTE
    result["available_ts_ms"] = result["close_ts_ms"]
    result["segment_id"] = (
        result["open_ts_ms"].diff().ne(MINUTE).cumsum().astype("int64") - 1
    )
    result = result[source.COLS]
    result.attrs = {**attrs, "timeframe_minutes": 1}
    return result


def _source_ref(manifest: Mapping[str, Any], symbol: str, opening: int) -> str:
    if manifest["data_kind"] == "SYNTHETIC_FIXTURE":
        item = manifest["minute_artifacts"][symbol]
        return (
            f"SYNTHETIC_FIXTURE:{item['path']}#sha256={item['sha256']};minute={opening}"
        )
    item = manifest["source_inventory"]
    return (
        f"{manifest['canonical_root']}#source_inventory={item['path']};"
        f"sha256={item['sha256']};symbol={symbol};minute={opening}"
    )


def _adapt_segments(frame: pd.DataFrame, execution_ids: list[Any]) -> pd.DataFrame:
    """Keep native aggregate IDs; execution IDs share actual minute continuity."""
    if len(execution_ids) != len(frame) or any(
        isinstance(value, bool) or not isinstance(value, Integral) or value < 0
        for value in execution_ids
    ):
        raise ValueError("INVALID_CANONICAL_EXECUTION_SEGMENT")
    result = frame.copy()
    result["price_type"] = "last"
    result["canonical_segment_id"] = frame["segment_id"]
    result["execution_segment_number"] = [int(value) for value in execution_ids]
    result["segment_id"] = ["canonical:" + str(int(value)) for value in execution_ids]
    result.attrs = {**frame.attrs, "segment_id_policy": SEGMENT_POLICY}
    return result


def load(manifest: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Load verified inputs only; caller admits genuine FULL before calling."""
    symbols = _contract(manifest, config)
    pinned = _verify_artifacts(manifest)
    genuine = manifest["data_kind"] == "GENUINE_RAW_HISTORY"
    if genuine:
        minutes, witness = _genuine(manifest, pinned)
    else:
        minutes, witness = _fixture(manifest, pinned), None
    frames, details = {}, {}
    for symbol in symbols:
        raw = minutes[symbol]
        frame = source.aggregate_minutes(raw, manifest["timeframe_min"])
        attrs = {
            **frame.attrs,
            "symbol": symbol,
            "source_rows_are_genuine": genuine,
            "source": source.SOURCE if genuine else "SYNTHETIC_UNIT_TEST_FIXTURE",
            "data_kind": manifest["data_kind"],
            "fresh_evidence": False,
            "order_authority": "BLOCKED",
            "live_authority": "BLOCKED",
            "source_inventory_sha256": manifest.get("source_inventory", {}).get(
                "sha256"
            ),
            "time_witness": witness,
            "price_basis": "LAST_PRICE",
        }
        frame.attrs = copy.deepcopy(attrs)
        detail = _detail(raw, attrs)
        execution_ids = (
            detail.set_index("open_ts_ms")["segment_id"]
            .reindex(frame["open_ts_ms"])
            .tolist()
        )
        frames[symbol] = _adapt_segments(frame, execution_ids)
        details[symbol] = _adapt_segments(detail, detail["segment_id"].tolist())
    first = min(int(f.iloc[0]["open_ts_ms"]) for f in details.values())
    last = max(int(f.iloc[-1]["close_ts_ms"]) for f in details.values())
    step = manifest["timeframe_min"] * MINUTE
    times = sorted(
        {first, last, *range(((first + step - 1) // step) * step, last + 1, step)}
    )
    indexes = {
        symbol: {
            int(row.open_ts_ms): (float(row.open), int(row.available_ts_ms))
            for row in frame.loc[
                frame["open_ts_ms"].isin(times),
                ["open_ts_ms", "open", "available_ts_ms"],
            ].itertuples(index=False)
        }
        for symbol, frame in details.items()
    }
    terminal = {symbol: frame.iloc[-1] for symbol, frame in details.items()}
    snapshots = []
    for stamp in times:
        prices = {}
        for symbol in symbols:
            value = indexes[symbol].get(stamp)
            if value is not None:
                price, available = value
                opening, phase = stamp, "OPEN_AFTER_BOUNDARY_FILLS"
            elif stamp == int(terminal[symbol]["close_ts_ms"]):
                price = float(terminal[symbol]["close"])
                available = stamp
                opening = int(terminal[symbol]["open_ts_ms"])
                phase = "TERMINAL_CLOSE_WITHOUT_LATER_OPEN"
            else:
                continue  # A missing grid open is never replaced with an old close.
            prices[symbol] = {
                "ts_ms": stamp,
                "price": price,
                "price_basis": "LAST_PRICE",
                "price_available_ts_ms": available,
                "price_event_phase": phase,
                "source_ref": _source_ref(manifest, symbol, opening)
                + ";phase="
                + phase,
            }
        snapshots.append({"ts_ms": stamp, "prices": prices})
    return {
        "frames": frames,
        "detail_frames": details,
        "price_snapshots": snapshots,
        "data_audit": {
            "schema": SCHEMA,
            "data_kind": manifest["data_kind"],
            "source_volume_units": "UNKNOWN",
            "segment_id_policy": SEGMENT_POLICY,
            "price_basis": "LAST_PRICE",
            "price_snapshot_sampling": SNAPSHOT_POLICY,
            "snapshot_clock": "RETROSPECTIVE_EVENT_TIME_NOT_CAUSAL_FEATURE",
            "snapshot_dd_limit": "SAMPLED_LAST_PRICE_ONLY; NOT_INTRAMINUTE_OR_EXCHANGE_MARK_DD",
            "fresh_evidence": False,
            "synthetic_fill": False,
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
