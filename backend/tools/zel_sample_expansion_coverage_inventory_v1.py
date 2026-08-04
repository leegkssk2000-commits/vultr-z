from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_SAMPLE_EXPANSION_COVERAGE_INVENTORY_V1"
SCHEMA = "zel.sample_expansion.coverage_inventory.v1"
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
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})[-_]([01]\d)(?!\d)"),
)
LINEAGE_KEYWORDS = {
    "funding": ("funding", "fund_rate"),
    "depth": ("depth", "orderbook", "order_book", "book"),
    "slippage": ("slippage", "impact"),
    "fee": ("fee", "commission"),
    "bars": ("bar", "kline", "ohlcv", "candle"),
    "trades": ("trade", "fills"),
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


def inventory_root(root: Path) -> dict[str, Any]:
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
        dates = infer_date_tokens(relative)
        tags = lineage_tags(relative)
        extension_counts[suffix] += 1
        if symbol:
            symbol_counts[symbol] += 1
        if timeframe:
            timeframe_counts[timeframe] += 1
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
                "date_tokens": dates,
                "lineage_tags": tags,
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
        "lineage_file_counts": dict(sorted(lineage_counts.items())),
        "date_token_min": min(date_tokens) if date_tokens else None,
        "date_token_max": max(date_tokens) if date_tokens else None,
        "date_token_count": len(date_tokens),
        "duplicate_content_groups": duplicate_content_groups,
        "unknown_symbol_file_count": sum(1 for row in rows if row["symbol"] is None),
        "unknown_timeframe_file_count": sum(1 for row in rows if row["timeframe"] is None),
        "errors": errors,
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    roots = [inventory_root(root) for root in args.root]
    root_states = [row["state"] for row in roots]
    all_files = sum(int(row["file_count"]) for row in roots)
    all_bytes = sum(int(row["total_bytes"]) for row in roots)
    passed = bool(roots) and all(state.startswith("PASS_") for state in root_states)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": utc_now(),
        "state": "PASS_SAMPLE_EXPANSION_COVERAGE_INVENTORY" if passed else "HOLD_SAMPLE_EXPANSION_COVERAGE_INVENTORY",
        "root_count": len(roots),
        "total_file_count": all_files,
        "total_bytes": all_bytes,
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
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
