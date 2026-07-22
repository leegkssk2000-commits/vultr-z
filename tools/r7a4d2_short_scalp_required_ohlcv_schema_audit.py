#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


MINIMUM_SOURCE_ROWS = 640
MAX_JSON_BYTES = 268_435_456
SAMPLE_ROW_LIMIT = 64

FIELD_ALIASES = {
    "timestamp": ("timestamp", "ts", "time", "datetime", "date", "open_time", "opentime", "start_time", "starttime"),
    "open": ("open", "o", "open_price", "openprice"),
    "high": ("high", "h", "high_price", "highprice"),
    "low": ("low", "l", "low_price", "lowprice"),
    "close": ("close", "c", "close_price", "closeprice"),
    "volume": ("volume", "v", "vol", "base_volume", "basevolume", "qty", "quantity"),
}
REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close")
ROW_CONTAINER_KEYS = ("data", "rows", "candles", "klines", "records", "items", "result", "list", "values", "ohlcv", "bars")
COLUMN_KEYS = ("columns", "fields", "header", "headers", "schema")


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


NORMALIZED_ALIASES = {
    field: {normalize_key(alias) for alias in aliases}
    for field, aliases in FIELD_ALIASES.items()
}


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        raise ValueError(f"JSON_FILE_TOO_LARGE:{size}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def infer_mapping(keys: Iterable[Any]) -> dict[str, str]:
    normalized_to_original: dict[str, str] = {}
    for key in keys:
        normalized_to_original.setdefault(normalize_key(key), str(key))
    mapping: dict[str, str] = {}
    for field, aliases in NORMALIZED_ALIASES.items():
        matches = [normalized_to_original[alias] for alias in aliases if alias in normalized_to_original]
        if len(matches) == 1:
            mapping[field] = matches[0]
        elif len(matches) > 1:
            exact = [item for item in matches if normalize_key(item) == normalize_key(field)]
            mapping[field] = sorted(exact or matches)[0]
    return mapping


def scalar_metadata(root: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if not isinstance(root, dict):
        return metadata
    for raw_key, value in root.items():
        key = normalize_key(raw_key)
        if isinstance(value, (dict, list)):
            continue
        if key in {"symbol", "ticker", "market", "instrument"} and "symbol" not in metadata:
            metadata["symbol"] = value
        if key in {"timeframe", "interval", "tf"} and "timeframe" not in metadata:
            metadata["timeframe"] = value
        if key in {"schema", "version", "source"} and key not in metadata:
            metadata[key] = value
    return metadata


def path_join(parent: str, key: Any) -> str:
    text = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return f"{parent}.{text}"
    return f"{parent}[{json.dumps(text)}]"


def find_column_names(container: dict[str, Any]) -> list[str] | None:
    for key in COLUMN_KEYS:
        for actual, value in container.items():
            if normalize_key(actual) == normalize_key(key) and isinstance(value, list) and value:
                if all(isinstance(item, (str, int, float)) for item in value):
                    return [str(item) for item in value]
    return None


def row_dict_candidate(rows: list[Any], container_path: str) -> dict[str, Any] | None:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return None
    key_histogram = Counter(str(key) for row in dict_rows[:SAMPLE_ROW_LIMIT] for key in row.keys())
    mapping = infer_mapping(key_histogram.keys())
    return {
        "adapter_class": "RECORD_LIST",
        "container_path": container_path,
        "row_count": len(rows),
        "mapping": mapping,
        "first_row_keys": sorted(str(key) for key in dict_rows[0].keys()),
        "sample_rows": dict_rows[:SAMPLE_ROW_LIMIT],
        "score": 100 * sum(field in mapping for field in REQUIRED_FIELDS) + min(len(rows), 99),
    }


def matrix_candidate(rows: list[Any], columns: list[str] | None, container_path: str) -> dict[str, Any] | None:
    matrix_rows = [row for row in rows if isinstance(row, (list, tuple))]
    if not matrix_rows or not columns:
        return None
    mapping_by_name = infer_mapping(columns)
    index_mapping = {field: columns.index(name) for field, name in mapping_by_name.items() if name in columns}
    return {
        "adapter_class": "COLUMN_MATRIX",
        "container_path": container_path,
        "row_count": len(rows),
        "columns": columns,
        "mapping": mapping_by_name,
        "index_mapping": index_mapping,
        "first_row_length": len(matrix_rows[0]),
        "sample_rows": matrix_rows[:SAMPLE_ROW_LIMIT],
        "score": 100 * sum(field in mapping_by_name for field in REQUIRED_FIELDS) + min(len(rows), 99),
    }


def columnar_candidate(value: dict[str, Any], container_path: str) -> dict[str, Any] | None:
    mapping = infer_mapping(value.keys())
    if not all(field in mapping for field in ("open", "high", "low", "close")):
        return None
    arrays = {field: value.get(name) for field, name in mapping.items()}
    if not all(isinstance(arrays.get(field), list) for field in ("open", "high", "low", "close")):
        return None
    lengths = [len(arrays[field]) for field in ("open", "high", "low", "close")]
    if not lengths or len(set(lengths)) != 1:
        return None
    row_count = lengths[0]
    sample_rows = []
    for index in range(min(row_count, SAMPLE_ROW_LIMIT)):
        sample_rows.append({field: arrays[field][index] for field in arrays if isinstance(arrays[field], list) and index < len(arrays[field])})
    return {
        "adapter_class": "COLUMNAR_ARRAYS",
        "container_path": container_path,
        "row_count": row_count,
        "mapping": mapping,
        "first_row_keys": sorted(mapping),
        "sample_rows": sample_rows,
        "score": 100 * sum(field in mapping for field in REQUIRED_FIELDS) + min(row_count, 99),
    }


def row_map_candidate(value: dict[str, Any], container_path: str) -> dict[str, Any] | None:
    items = list(value.items())
    dict_values = [(key, row) for key, row in items if isinstance(row, dict)]
    if not dict_values or len(dict_values) < max(1, len(items) // 2):
        return None
    first_key, first_row = dict_values[0]
    mapping = infer_mapping(first_row.keys())
    timestamp_from_key = "timestamp" not in mapping
    if timestamp_from_key:
        mapping["timestamp"] = "__row_key__"
    sample_rows = []
    for key, row in dict_values[:SAMPLE_ROW_LIMIT]:
        sample = dict(row)
        if timestamp_from_key:
            sample["__row_key__"] = key
        sample_rows.append(sample)
    return {
        "adapter_class": "TIMESTAMP_KEYED_ROW_MAP" if timestamp_from_key else "ROW_MAP",
        "container_path": container_path,
        "row_count": len(dict_values),
        "mapping": mapping,
        "first_row_keys": sorted(str(key) for key in first_row.keys()),
        "sample_rows": sample_rows,
        "score": 100 * sum(field in mapping for field in REQUIRED_FIELDS) + min(len(dict_values), 99),
    }


def collect_candidates(value: Any, path: str = "$", parent: dict[str, Any] | None = None, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 5:
        return []
    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        record = row_dict_candidate(value, path)
        if record:
            candidates.append(record)
        matrix = matrix_candidate(value, find_column_names(parent or {}), path)
        if matrix:
            candidates.append(matrix)
        for index, item in enumerate(value[:8]):
            if isinstance(item, (dict, list)):
                candidates.extend(collect_candidates(item, f"{path}[{index}]", None, depth + 1))
    elif isinstance(value, dict):
        columnar = columnar_candidate(value, path)
        if columnar:
            candidates.append(columnar)
        row_map = row_map_candidate(value, path)
        if row_map:
            candidates.append(row_map)
        preferred = sorted(
            value.items(),
            key=lambda item: (normalize_key(item[0]) not in {normalize_key(key) for key in ROW_CONTAINER_KEYS}, str(item[0])),
        )
        for key, child in preferred:
            if isinstance(child, (dict, list)):
                candidates.extend(collect_candidates(child, path_join(path, key), value, depth + 1))
    return candidates


def sample_quality(candidate: dict[str, Any]) -> dict[str, Any]:
    mapping = candidate.get("mapping") if isinstance(candidate.get("mapping"), dict) else {}
    samples = candidate.get("sample_rows") if isinstance(candidate.get("sample_rows"), list) else []
    index_mapping = candidate.get("index_mapping") if isinstance(candidate.get("index_mapping"), dict) else {}
    total = 0
    valid_ohlc = 0
    valid_timestamp = 0
    positive_close = 0
    geometry_valid = 0
    for row in samples:
        values: dict[str, Any] = {}
        if isinstance(row, dict):
            for field, source in mapping.items():
                values[field] = row.get(source)
        elif isinstance(row, (list, tuple)):
            for field, index in index_mapping.items():
                if isinstance(index, int) and 0 <= index < len(row):
                    values[field] = row[index]
        total += 1
        if all(finite_number(values.get(field)) for field in ("open", "high", "low", "close")):
            valid_ohlc += 1
            open_value = float(values["open"])
            high_value = float(values["high"])
            low_value = float(values["low"])
            close_value = float(values["close"])
            if close_value > 0:
                positive_close += 1
            if high_value >= max(open_value, close_value) and low_value <= min(open_value, close_value):
                geometry_valid += 1
        timestamp_value = values.get("timestamp")
        if timestamp_value not in (None, ""):
            valid_timestamp += 1
    divisor = max(total, 1)
    return {
        "sample_count": total,
        "numeric_ohlc_ratio": round(valid_ohlc / divisor, 6),
        "timestamp_present_ratio": round(valid_timestamp / divisor, 6),
        "positive_close_ratio": round(positive_close / divisor, 6),
        "ohlc_geometry_valid_ratio": round(geometry_valid / divisor, 6),
    }


def schema_signature(candidate: dict[str, Any]) -> str:
    mapping = candidate.get("mapping") if isinstance(candidate.get("mapping"), dict) else {}
    parts = [str(candidate.get("adapter_class") or ""), str(candidate.get("container_path") or "")]
    parts.extend(f"{field}:{mapping.get(field, '')}" for field in sorted(mapping))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def inspect_required_file(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    repo_path = safe_repo_path(str(entry.get("path") or ""))
    path = root / repo_path
    expected_sha = str(entry.get("sha256") or "")
    actual_sha = sha256_file(path)
    if actual_sha is None:
        raise ValueError("SOURCE_FILE_MISSING_OR_SYMLINK")
    if actual_sha != expected_sha:
        raise ValueError("FROZEN_SHA_MISMATCH")
    root_value = load_json(path)
    candidates = collect_candidates(root_value)
    candidates.sort(key=lambda row: (-int(row.get("score", 0)), str(row.get("container_path") or ""), str(row.get("adapter_class") or "")))
    selected = candidates[0] if candidates else None
    if selected is None:
        return {
            "path": repo_path,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "file_size_bytes": path.stat().st_size,
            "top_level_type": type(root_value).__name__,
            "top_level_keys": sorted(str(key) for key in root_value.keys()) if isinstance(root_value, dict) else [],
            "adapter_ready": False,
            "classification": "SCHEMA_UNRESOLVED",
            "candidate_count": 0,
        }
    quality = sample_quality(selected)
    mapping = selected.get("mapping") if isinstance(selected.get("mapping"), dict) else {}
    required_mapping_ready = all(field in mapping for field in REQUIRED_FIELDS)
    row_count = int(selected.get("row_count", 0))
    adapter_ready = (
        required_mapping_ready
        and row_count >= MINIMUM_SOURCE_ROWS
        and quality["numeric_ohlc_ratio"] >= 0.95
        and quality["timestamp_present_ratio"] >= 0.95
        and quality["positive_close_ratio"] >= 0.95
        and quality["ohlc_geometry_valid_ratio"] >= 0.95
    )
    output = {
        "path": repo_path,
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "file_size_bytes": path.stat().st_size,
        "top_level_type": type(root_value).__name__,
        "top_level_keys": sorted(str(key) for key in root_value.keys())[:100] if isinstance(root_value, dict) else [],
        "top_level_metadata": scalar_metadata(root_value),
        "candidate_count": len(candidates),
        "adapter_ready": adapter_ready,
        "classification": "DETERMINISTIC_ADAPTER_READY" if adapter_ready else "SCHEMA_FOUND_BUT_VALIDATION_FAILED",
        "adapter_class": selected.get("adapter_class"),
        "container_path": selected.get("container_path"),
        "row_count": row_count,
        "mapping": mapping,
        "index_mapping": selected.get("index_mapping", {}),
        "columns": selected.get("columns", []),
        "first_row_keys": selected.get("first_row_keys", []),
        "first_row_length": selected.get("first_row_length"),
        "sample_quality": quality,
        "schema_signature": schema_signature(selected),
        "alternate_candidates": [
            {
                "adapter_class": row.get("adapter_class"),
                "container_path": row.get("container_path"),
                "row_count": row.get("row_count"),
                "mapping": row.get("mapping", {}),
                "score": row.get("score", 0),
            }
            for row in candidates[1:6]
        ],
    }
    return output


def build_audit(
    frozen_manifest: dict[str, Any],
    selected_manifest: dict[str, Any],
    inspected: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_MANIFEST_NOT_PASS")
    if selected_manifest.get("state") != "PASS":
        blockers.append("SELECTED_MANIFEST_NOT_PASS")
    selected_segments = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = sorted({str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")})
    ready = [row for row in inspected if bool(row.get("adapter_ready"))]
    unresolved = [row for row in inspected if not bool(row.get("adapter_ready"))]
    if failures:
        blockers.append(f"REQUIRED_SCHEMA_AUDIT_FAILURE:{len(failures)}")
    if unresolved:
        blockers.append(f"REQUIRED_SCHEMA_UNRESOLVED:{len(unresolved)}")
    if len(ready) != len(required_paths):
        blockers.append(f"REQUIRED_ADAPTER_READY_COUNT_MISMATCH:{len(ready)}:{len(required_paths)}")
    signatures = sorted({str(row.get("schema_signature") or "") for row in ready if row.get("schema_signature")})
    classes = sorted({str(row.get("adapter_class") or "") for row in ready if row.get("adapter_class")})
    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT" if not blockers else "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT_INPUT"
    next_stage = (
        "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"
        if not blockers
        else "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT"
    )
    audit = {
        "schema": "r7a4d2_short_scalp_required_ohlcv_schema_audit_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "selected_segment_count": len(selected_segments),
        "required_source_count": len(required_paths),
        "required_source_paths": required_paths,
        "inspected_source_count": len(inspected),
        "adapter_ready_source_count": len(ready),
        "unresolved_source_count": len(unresolved),
        "audit_failure_count": len(failures),
        "schema_signature_count": len(signatures),
        "schema_signatures": signatures,
        "adapter_classes": classes,
        "single_shared_schema": len(signatures) == 1 and len(ready) == len(required_paths),
        "per_source_adapter_allowed": len(signatures) > 1 and len(ready) == len(required_paths),
        "source_audits": inspected,
        "audit_failures": failures,
        "adapter_contract": {
            "frozen_sha_required": True,
            "minimum_source_rows": MINIMUM_SOURCE_ROWS,
            "required_fields": list(REQUIRED_FIELDS),
            "numeric_ohlc_sample_ratio_gte": 0.95,
            "timestamp_sample_ratio_gte": 0.95,
            "positive_close_sample_ratio_gte": 0.95,
            "ohlc_geometry_sample_ratio_gte": 0.95,
            "source_specific_mapping_allowed": True,
            "heuristic_runtime_guessing_allowed": False,
        },
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "next_stage": next_stage,
    }
    return audit, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract_path = Path(args.contract).resolve()
    contract = load_json(contract_path)
    frozen_path = root / str(contract["frozen_manifest_path"])
    selected_path = root / str(contract["selected_manifest_path"])
    frozen_manifest = load_json(frozen_path)
    selected_manifest = load_json(selected_path)

    selected_segments = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = sorted({str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")})
    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    entry_by_path = {str(row.get("path") or ""): row for row in market_entries}

    protected_paths = [frozen_path, selected_path, contract_path]
    before = {str(path): sha256_file(path) for path in protected_paths}
    inspected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for repo_path in required_paths:
        entry = entry_by_path.get(repo_path)
        if entry is None:
            failures.append({"path": repo_path, "reason": "FROZEN_MARKET_ENTRY_MISSING"})
            continue
        try:
            inspected.append(inspect_required_file(root, entry))
        except Exception as exc:
            failures.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})
    inspected.sort(key=lambda row: str(row.get("path") or ""))
    failures.sort(key=lambda row: str(row.get("path") or ""))

    audit, blockers = build_audit(frozen_manifest, selected_manifest, inspected, failures)
    after = {str(path): sha256_file(path) for path in protected_paths}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        blockers = list(dict.fromkeys(blockers))
        audit["blockers"] = blockers
        audit["blocker_count"] = len(blockers)
        audit["state"] = "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT_INPUT"
        audit["next_stage"] = "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_AUDIT"
    audit["protected_mutation_path_count"] = len(mutation_paths)
    audit["protected_mutation_paths"] = mutation_paths

    output = root / "runtime/r7a4d2_short_scalp_required_ohlcv_schema_audit/schema_audit_v1.json"
    atomic_json(output, audit)

    print("STATE=" + str(audit["state"]))
    print("BLOCKER_COUNT=" + str(audit["blocker_count"]))
    print("REQUIRED_SOURCE_COUNT=" + str(audit["required_source_count"]))
    print("INSPECTED_SOURCE_COUNT=" + str(audit["inspected_source_count"]))
    print("ADAPTER_READY_SOURCE_COUNT=" + str(audit["adapter_ready_source_count"]))
    print("UNRESOLVED_SOURCE_COUNT=" + str(audit["unresolved_source_count"]))
    print("AUDIT_FAILURE_COUNT=" + str(audit["audit_failure_count"]))
    print("SCHEMA_SIGNATURE_COUNT=" + str(audit["schema_signature_count"]))
    print("SINGLE_SHARED_SCHEMA=" + str(audit["single_shared_schema"]).lower())
    print("PER_SOURCE_ADAPTER_ALLOWED=" + str(audit["per_source_adapter_allowed"]).lower())
    print("ADAPTER_CLASSES=" + json.dumps(audit["adapter_classes"], ensure_ascii=False))
    print("SOURCE_AUDITS=" + json.dumps(audit["source_audits"], ensure_ascii=False, sort_keys=True))
    print("AUDIT_FAILURES=" + json.dumps(audit["audit_failures"], ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(audit["protected_mutation_path_count"]))
    print("AUDIT_JSON=" + str(output))
    print("NEXT_STAGE=" + str(audit["next_stage"]))
    print("BLOCKERS=" + json.dumps(audit["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(audit["blocker_count"]) == 0 else "2"))
    return 0 if int(audit["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
