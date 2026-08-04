from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_SAMPLE_EXPANSION_COVERAGE_INVENTORY_V3_TIMESTAMP_MS"
SCHEMA = "zel.sample_expansion.coverage_inventory.v3"
ALLOWED_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".gz",
    ".parquet",
    ".feather",
    ".npy",
    ".npz",
    ".pkl",
}
SYMBOL_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{2,15}(?:USDT|USDC|USD|BTC|ETH))(?![A-Z0-9])")
TIMEFRAME_RE = re.compile(r"(?<![A-Za-z0-9])(1m|3m|5m|15m|30m|1h|2h|4h|6h|8h|12h|1d|1w)(?![A-Za-z0-9])", re.I)
WINDOW_RE = re.compile(r"(?<![A-Za-z0-9])(w1|w2|w3)(?![A-Za-z0-9])", re.I)
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})[-_]([01]\d)(?!\d)"),
)
LINEAGE_KEYWORDS = {
    "funding": ("funding", "fund_rate"),
    "depth": ("depth", "orderbook", "order_book", "book"),
    "slippage": ("slippage", "impact"),
    "fee": ("fee", "commission"),
    "bars": ("bar", "kline", "ohlcv", "candle", "market/"),
    "trades": ("trade", "fills"),
}
TIMESTAMP_COLUMNS = (
    "timestamp_ms",
    "time_ms",
    "open_time_ms",
    "open_timestamp_ms",
    "timestamp",
    "ts",
    "time",
    "open_time",
    "open_timestamp",
    "datetime",
    "date",
)
TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_date_token(match: re.Match[str]) -> str | None:
    groups = match.groups()
    if len(groups) == 3:
        year, month, day = groups
    else:
        year, month = groups
        day = "01"
    try:
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc).date().isoformat()
    except ValueError:
        return None


def infer_date_tokens(text: str) -> list[str]:
    values: set[str] = set()
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            token = normalize_date_token(match)
            if token:
                values.add(token)
    return sorted(values)


def infer_symbol(text: str) -> str | None:
    upper = text.upper().replace("-", "_").replace("/", "_")
    match = SYMBOL_RE.search(upper)
    return match.group(1) if match else None


def infer_timeframe(text: str) -> str | None:
    match = TIMEFRAME_RE.search(text)
    return match.group(1).lower() if match else None


def infer_window(text: str) -> str | None:
    match = WINDOW_RE.search(text)
    return match.group(1).lower() if match else None


def lineage_tags(text: str) -> list[str]:
    low = text.lower()
    return sorted(
        name
        for name, keywords in LINEAGE_KEYWORDS.items()
        if any(keyword in low for keyword in keywords)
    )


def iter_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".cache", "tmp"})
        for filename in sorted(files):
            path = Path(current) / filename
            if path.suffix.lower() in ALLOWED_SUFFIXES or any(
                path.name.lower().endswith(suffix)
                for suffix in (".jsonl.gz", ".json.gz", ".csv.gz")
            ):
                yield path


def parse_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        if number > 1e14:
            return number / 1_000_000.0
        if number > 1e11:
            return number / 1000.0
        if number > 1e9:
            return number
    except ValueError:
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def choose_timestamp_column(columns: Iterable[str]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in TIMESTAMP_COLUMNS:
        if candidate in normalized:
            return normalized[candidate]
    return None


def coverage_from_timestamps(values: list[float], expected_seconds: int | None) -> dict[str, Any]:
    if not values:
        return {
            "timestamp_count": 0,
            "timestamp_min_utc": None,
            "timestamp_max_utc": None,
            "duplicate_timestamp_count": 0,
            "monotonic_violation_count": 0,
            "missing_interval_count": None,
            "largest_gap_seconds": None,
        }
    duplicates = len(values) - len(set(values))
    monotonic = sum(1 for left, right in zip(values, values[1:]) if right <= left)
    ordered = sorted(set(values))
    gaps = [right - left for left, right in zip(ordered, ordered[1:])]
    missing = None
    if expected_seconds:
        missing = sum(max(int(round(gap / expected_seconds)) - 1, 0) for gap in gaps if gap > expected_seconds * 1.5)
    return {
        "timestamp_count": len(values),
        "timestamp_min_utc": datetime.fromtimestamp(min(values), tz=timezone.utc).isoformat(),
        "timestamp_max_utc": datetime.fromtimestamp(max(values), tz=timezone.utc).isoformat(),
        "duplicate_timestamp_count": duplicates,
        "monotonic_violation_count": monotonic,
        "missing_interval_count": missing,
        "largest_gap_seconds": max(gaps) if gaps else 0.0,
    }


def inspect_csv(path: Path, timeframe: str | None) -> dict[str, Any]:
    row_count = 0
    null_cell_count = 0
    timestamps: list[float] = []
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        timestamp_column = choose_timestamp_column(columns)
        for row in reader:
            row_count += 1
            null_cell_count += sum(1 for value in row.values() if value is None or not str(value).strip())
            if timestamp_column:
                parsed = parse_timestamp(row.get(timestamp_column))
                if parsed is not None:
                    timestamps.append(parsed)
    coverage = coverage_from_timestamps(timestamps, TIMEFRAME_SECONDS.get(timeframe or ""))
    return {
        "content_kind": "csv",
        "row_count": row_count,
        "columns": columns,
        "column_schema_sha256": stable_sha(columns),
        "timestamp_column": timestamp_column,
        "unparsed_timestamp_count": row_count - len(timestamps) if timestamp_column else row_count,
        "null_cell_count": null_cell_count,
        **coverage,
    }


def flatten_json_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "rows", "items", "funding", "records"):
            child = value.get(key)
            if isinstance(child, list):
                return [row for row in child if isinstance(row, Mapping)]
    return []


def inspect_json(path: Path, timeframe: str | None) -> dict[str, Any]:
    if path.stat().st_size > 8 * 1024 * 1024:
        return {"content_kind": "json", "content_scan_skipped": "FILE_TOO_LARGE"}
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = flatten_json_rows(value)
    top_keys = sorted(str(key) for key in value.keys()) if isinstance(value, Mapping) else []
    if not rows:
        return {
            "content_kind": "json",
            "row_count": 0,
            "top_level_keys": top_keys,
            "top_level_schema_sha256": stable_sha(top_keys),
        }
    columns = sorted({str(key) for row in rows for key in row.keys()})
    timestamp_column = choose_timestamp_column(columns)
    timestamps = [
        parsed
        for row in rows
        if timestamp_column
        for parsed in [parse_timestamp(row.get(timestamp_column))]
        if parsed is not None
    ]
    coverage = coverage_from_timestamps(timestamps, TIMEFRAME_SECONDS.get(timeframe or ""))
    return {
        "content_kind": "json",
        "row_count": len(rows),
        "columns": columns,
        "column_schema_sha256": stable_sha(columns),
        "timestamp_column": timestamp_column,
        "unparsed_timestamp_count": len(rows) - len(timestamps) if timestamp_column else len(rows),
        "top_level_keys": top_keys,
        **coverage,
    }


def inspect_content(path: Path, relative: str, timeframe: str | None) -> dict[str, Any] | None:
    low = relative.lower()
    if "/market/" not in f"/{low}" and not low.startswith("market/") and not low.startswith("funding/"):
        return None
    try:
        if path.suffix.lower() == ".csv":
            return inspect_csv(path, timeframe)
        if path.suffix.lower() == ".json":
            return inspect_json(path, timeframe)
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        return {"content_scan_error": f"{type(exc).__name__}:{exc}"}
    return {"content_scan_skipped": "UNSUPPORTED_FORMAT"}


def inventory_root(root: Path, *, inspect_market_content: bool) -> dict[str, Any]:
    if not root.is_dir():
        return {
            "root": str(root),
            "state": "HOLD_ROOT_MISSING",
            "file_count": 0,
            "total_bytes": 0,
            "tree_sha256": None,
            "files": [],
            "errors": ["ROOT_MISSING"],
        }

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    extension_counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    timeframe_counts: Counter[str] = Counter()
    window_counts: Counter[str] = Counter()
    lineage_counts: Counter[str] = Counter()
    date_tokens: set[str] = set()
    sha_to_paths: dict[str, list[str]] = defaultdict(list)
    total_bytes = 0

    for path in iter_files(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"SYMLINK_FILE:{relative}")
            continue
        try:
            stat = path.stat()
            digest = sha256_path(path)
        except (OSError, PermissionError) as exc:
            errors.append(f"UNREADABLE:{relative}:{type(exc).__name__}")
            continue
        if stat.st_size <= 0:
            errors.append(f"EMPTY_FILE:{relative}")
        suffix = "".join(path.suffixes[-2:]).lower() if path.name.lower().endswith((".jsonl.gz", ".json.gz", ".csv.gz")) else path.suffix.lower()
        symbol = infer_symbol(relative)
        timeframe = infer_timeframe(relative)
        window = infer_window(relative)
        dates = infer_date_tokens(relative)
        tags = lineage_tags(relative)
        content = inspect_content(path, relative, timeframe) if inspect_market_content else None
        if content and content.get("content_scan_error"):
            errors.append(f"CONTENT_SCAN:{relative}:{content['content_scan_error']}")
        extension_counts[suffix] += 1
        if symbol:
            symbol_counts[symbol] += 1
        if timeframe:
            timeframe_counts[timeframe] += 1
        if window:
            window_counts[window] += 1
        for tag in tags:
            lineage_counts[tag] += 1
        date_tokens.update(dates)
        sha_to_paths[digest].append(relative)
        total_bytes += stat.st_size
        rows.append(
            {
                "path": relative,
                "bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "sha256": digest,
                "suffix": suffix,
                "symbol": symbol,
                "timeframe": timeframe,
                "window": window,
                "date_tokens": dates,
                "lineage_tags": tags,
                "content_coverage": content,
            }
        )

    duplicate_content_groups = [
        {"sha256": digest, "paths": paths}
        for digest, paths in sorted(sha_to_paths.items())
        if len(paths) > 1
    ]
    rows.sort(key=lambda row: row["path"])
    tree_material = [
        {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in rows
    ]
    content_rows = [row["content_coverage"] for row in rows if isinstance(row.get("content_coverage"), Mapping)]
    duplicate_timestamps = sum(int(row.get("duplicate_timestamp_count") or 0) for row in content_rows)
    monotonic_violations = sum(int(row.get("monotonic_violation_count") or 0) for row in content_rows)
    missing_intervals = sum(int(row.get("missing_interval_count") or 0) for row in content_rows)
    unparsed_timestamps = sum(int(row.get("unparsed_timestamp_count") or 0) for row in content_rows)
    state = "PASS_COVERAGE_ROOT_INVENTORIED" if rows and not errors else "HOLD_COVERAGE_ROOT_INTEGRITY"
    return {
        "root": str(root.resolve()),
        "state": state,
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "tree_sha256": stable_sha(tree_material) if rows else None,
        "extension_counts": dict(sorted(extension_counts.items())),
        "symbol_counts": dict(sorted(symbol_counts.items())),
        "timeframe_counts": dict(sorted(timeframe_counts.items())),
        "window_counts": dict(sorted(window_counts.items())),
        "lineage_file_counts": dict(sorted(lineage_counts.items())),
        "date_token_min": min(date_tokens) if date_tokens else None,
        "date_token_max": max(date_tokens) if date_tokens else None,
        "date_token_count": len(date_tokens),
        "duplicate_content_groups": duplicate_content_groups,
        "unknown_symbol_file_count": sum(1 for row in rows if row["symbol"] is None),
        "unknown_timeframe_file_count": sum(1 for row in rows if row["timeframe"] is None),
        "content_scanned_file_count": len(content_rows),
        "duplicate_timestamp_count": duplicate_timestamps,
        "monotonic_violation_count": monotonic_violations,
        "missing_interval_count": missing_intervals,
        "unparsed_timestamp_count": unparsed_timestamps,
        "coverage_quality_pass": not errors and duplicate_timestamps == 0 and monotonic_violations == 0 and unparsed_timestamps == 0,
        "errors": errors,
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--content-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    content_root = args.content_root.resolve() if args.content_root else None
    roots = [
        inventory_root(root, inspect_market_content=bool(content_root and root.resolve() == content_root))
        for root in args.root
    ]
    root_states = [row["state"] for row in roots]
    all_files = sum(int(row["file_count"]) for row in roots)
    all_bytes = sum(int(row["total_bytes"]) for row in roots)
    passed = bool(roots) and all(state.startswith("PASS_") for state in root_states)
    content_quality = all(
        bool(row.get("coverage_quality_pass", True))
        for row in roots
        if content_root and row["root"] == str(content_root)
    )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": utc_now(),
        "state": "PASS_SAMPLE_EXPANSION_COVERAGE_INVENTORY" if passed else "HOLD_SAMPLE_EXPANSION_COVERAGE_INVENTORY",
        "root_count": len(roots),
        "total_file_count": all_files,
        "total_bytes": all_bytes,
        "content_root": str(content_root) if content_root else None,
        "content_coverage_quality_pass": content_quality,
        "roots": roots,
        "economics_inspected": False,
        "strategy_rules_inspected": False,
        "holdout_metrics_inspected": False,
        "synthetic_observations_created": False,
        "real_trade_count_mutated": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "PRE_REGISTER_REAL_DATA_EXPANSION_PARTITIONS" if passed else "REPAIR_COVERAGE_INTEGRITY_ONLY",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "root_count": receipt["root_count"],
                "total_file_count": receipt["total_file_count"],
                "total_bytes": receipt["total_bytes"],
                "content_coverage_quality_pass": receipt["content_coverage_quality_pass"],
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
