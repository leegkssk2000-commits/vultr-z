#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
ROOTS = [ROOT / x for x in ("backend", "config", "policies", "research", "runtime", "scripts", "tools")]
W1_START_MS = 1782549000000
W2_END_MS = 1784276940000
MAX_FILES = 8000
MAX_TEXT_BYTES = 750_000
MAX_DATA_BYTES = 8_000_000
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "archive", "artifacts", "cache", ".cache"}
TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".md", ".txt", ".csv", ".sh"}
DATA_SUFFIXES = {".csv", ".json", ".jsonl"}
ENDPOINT_RE = re.compile(r"/openApi/[A-Za-z0-9_./-]+")
TIME_KEYS = ("timestamp_ms", "timestamp", "time", "ts", "fundingTime", "funding_time", "createTime", "updateTime", "openTime", "closeTime")
CATEGORY_PATTERNS = {
    "funding": re.compile(r"funding(?:Rate|_rate|Time|_time|history)?", re.I),
    "basis": re.compile(r"\bbasis\b|premium(?:Index|_index)?|mark(?:Price|_price)|index(?:Price|_price)", re.I),
    "open_interest": re.compile(r"openInterest|open_interest|open interest", re.I),
    "flow": re.compile(r"longShort|long_short|positionRatio|position_ratio|takerBuy|taker_buy|buySell|buy_sell|order[_ ]?flow", re.I),
}
NAME_RE = re.compile(r"fund|premium|basis|open.?interest|long.?short|position.?ratio|order.?flow|taker", re.I)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return str(path)


def iter_files() -> Iterable[Path]:
    emitted = 0
    for root in ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                yield Path(dirpath) / name
                emitted += 1
                if emitted >= MAX_FILES:
                    return


def read_bounded(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    try:
        with path.open("rb") as fh:
            return fh.read(limit).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def to_ms(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = int(float(v))
        if x < 0:
            return None
        return x * 1000 if x < 10_000_000_000 else x
    except Exception:
        return None


def row_timestamp(row: dict[str, Any]) -> tuple[int | None, str | None]:
    for key in TIME_KEYS:
        if key in row:
            ts = to_ms(row.get(key))
            if ts is not None:
                return ts, key
    return None, None


def categories_from_keys(keys: Iterable[str]) -> list[str]:
    joined = " ".join(str(k) for k in keys)
    return sorted(k for k, pat in CATEGORY_PATTERNS.items() if pat.search(joined))


def summarize_rows(rows: list[dict[str, Any]], path: Path) -> dict[str, Any] | None:
    if not rows:
        return None
    keys = sorted({str(k) for r in rows[:200] for k in r.keys()})
    cats = categories_from_keys(keys)
    if not cats:
        return None
    ts_rows: list[int] = []
    ts_keys: set[str] = set()
    for row in rows:
        ts, key = row_timestamp(row)
        if ts is not None:
            ts_rows.append(ts)
            if key:
                ts_keys.add(key)
    ts_rows.sort()
    return {
        "path": safe_rel(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "suffix": path.suffix.lower(),
        "categories": cats,
        "schema_keys": keys[:120],
        "parsed_rows": len(rows),
        "timestamp_count": len(ts_rows),
        "timestamp_keys": sorted(ts_keys),
        "min_timestamp_ms": ts_rows[0] if ts_rows else None,
        "max_timestamp_ms": ts_rows[-1] if ts_rows else None,
        "coverage_days": ((ts_rows[-1] - ts_rows[0]) / 86400000.0) if len(ts_rows) >= 2 else 0.0,
        "covers_W1_start": bool(ts_rows and ts_rows[0] <= W1_START_MS),
        "covers_W2_end": bool(ts_rows and ts_rows[-1] >= W2_END_MS),
        "covers_W1_W2": bool(ts_rows and ts_rows[0] <= W1_START_MS and ts_rows[-1] >= W2_END_MS and len(ts_rows) > 1),
        "raw_values_emitted": False,
    }


def parse_csv(path: Path) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="", encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or not categories_from_keys(reader.fieldnames):
                return None
            for i, row in enumerate(reader):
                rows.append(dict(row))
                if i >= 19999:
                    break
    except Exception:
        return None
    return summarize_rows(rows, path)


def extract_json_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for key in ("rows", "data", "list", "result", "fundingRates", "history", "items", "records"):
            value = obj.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return [obj]
    return []


def parse_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    rows = extract_json_rows(obj)
    return summarize_rows(rows[:20000], path)


def parse_jsonl(path: Path) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                if i >= 19999:
                    break
    except Exception:
        return None
    return summarize_rows(rows, path)


def parse_data(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > MAX_DATA_BYTES:
            return None
    except OSError:
        return None
    if path.suffix.lower() == ".csv":
        return parse_csv(path)
    if path.suffix.lower() == ".json":
        return parse_json(path)
    if path.suffix.lower() == ".jsonl":
        return parse_jsonl(path)
    return None


def main() -> int:
    endpoint_rows: list[dict[str, Any]] = []
    named_files: list[dict[str, Any]] = []
    data_candidates: list[dict[str, Any]] = []
    category_paths: dict[str, set[str]] = {k: set() for k in CATEGORY_PATTERNS}
    scanned = 0

    for path in iter_files():
        scanned += 1
        rel = safe_rel(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue

        if NAME_RE.search(path.name):
            named_files.append({"path": rel, "suffix": path.suffix.lower(), "size_bytes": size})

        if path.suffix.lower() in DATA_SUFFIXES:
            candidate = parse_data(path)
            if candidate is not None:
                data_candidates.append(candidate)
                for cat in candidate["categories"]:
                    category_paths[cat].add(rel)

        if path.suffix.lower() not in TEXT_SUFFIXES or size > MAX_TEXT_BYTES:
            continue
        text = read_bounded(path)
        if not text:
            continue
        cats = sorted(k for k, pat in CATEGORY_PATTERNS.items() if pat.search(text))
        for cat in cats:
            category_paths[cat].add(rel)
        endpoints = sorted(set(ENDPOINT_RE.findall(text)))
        relevant = [e for e in endpoints if any(x in e.lower() for x in ("fund", "premium", "interest", "ratio", "position", "ticker", "depth", "price", "mark", "index"))]
        if relevant:
            endpoint_rows.append({
                "path": rel,
                "sha256": sha256_file(path),
                "categories": cats,
                "endpoints": relevant,
            })

    strong = [x for x in data_candidates if x["covers_W1_W2"]]
    strong_by_category = {
        cat: [x["path"] for x in strong if cat in x["categories"]]
        for cat in CATEGORY_PATTERNS
    }
    unique_endpoints = sorted({e for row in endpoint_rows for e in row["endpoints"]})
    receipt: dict[str, Any] = {
        "schema_version": "zel.p3.runtime_historical_source_inventory.v1",
        "state": "PASS_P3_RUNTIME_SOURCE_INVENTORY_READ_ONLY",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(ROOT),
        "target_W1_start_ms": W1_START_MS,
        "target_W2_end_ms": W2_END_MS,
        "files_scanned_bounded": scanned,
        "scan_cap": MAX_FILES,
        "category_path_counts": {k: len(v) for k, v in category_paths.items()},
        "unique_relevant_endpoint_literals": unique_endpoints,
        "endpoint_source_rows": endpoint_rows[:500],
        "name_candidate_files": named_files[:500],
        "timestamped_data_candidates": data_candidates[:500],
        "strong_W1_W2_data_candidates": strong,
        "strong_W1_W2_by_category": strong_by_category,
        "historical_candidate_flags": {
            "funding": bool(strong_by_category["funding"]),
            "basis": bool(strong_by_category["basis"]),
            "open_interest": bool(strong_by_category["open_interest"]),
            "flow": bool(strong_by_category["flow"]),
        },
        "interpretation": "This is discovery only. A filename, keyword, endpoint literal, or timestamped local table is not source authority until lineage, schema and causal alignment are separately bound.",
        "raw_market_values_emitted": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
