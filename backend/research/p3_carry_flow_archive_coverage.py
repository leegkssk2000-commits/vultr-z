#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
SEARCH_ROOTS = [ROOT / "runtime", ROOT / "research", ROOT / "backend/research", ROOT / "data"]
W1_START_MS = 1782549000000
W2_END_MS = 1784276940000
MAX_FILES = 20000
MAX_BYTES = 12_000_000
NAME_RE = re.compile(r"(feature|fund|interest|premium|basis|market|liquid|micro|snapshot|telemetry|observation)", re.I)
CATEGORY_KEYS = {
    "funding": re.compile(r"funding(rate)?|funding_rate", re.I),
    "basis": re.compile(r"basis|premium(_?index)?|mark(_?price)?|index(_?price)?", re.I),
    "open_interest": re.compile(r"open_?interest|openinterest", re.I),
    "flow": re.compile(r"long_?short|position_?ratio|taker_?buy|buy_?sell|order_?flow|orderflow", re.I),
}
TIME_KEYS = {"timestamp", "timestamp_ms", "time", "ts", "observed_at", "created_at", "updated_at", "fundingTime", "funding_time", "start_ms", "end_ms"}


def to_ms(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        if isinstance(v, str) and not v.replace(".", "", 1).isdigit():
            s = v.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        x = int(float(v))
        return x * 1000 if x < 10_000_000_000 else x
    except Exception:
        return None


def iter_files() -> Iterable[Path]:
    n = 0
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache"}]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() not in {".json", ".jsonl", ".csv"}:
                    continue
                if not NAME_RE.search(name) and not NAME_RE.search(str(p.parent.name)):
                    continue
                try:
                    if p.stat().st_size <= 0 or p.stat().st_size > MAX_BYTES:
                        continue
                except OSError:
                    continue
                yield p
                n += 1
                if n >= MAX_FILES:
                    return


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except Exception:
        return str(p)


def walk_json(v: Any, categories: set[str], times: list[int], keys: set[str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(v, dict):
        for k, x in v.items():
            ks = str(k)
            keys.add(ks)
            for category, pat in CATEGORY_KEYS.items():
                if pat.search(ks):
                    categories.add(category)
            if ks in TIME_KEYS or ks.lower() in {x.lower() for x in TIME_KEYS}:
                t = to_ms(x)
                if t is not None and 1_500_000_000_000 <= t <= 2_000_000_000_000:
                    times.append(t)
            walk_json(x, categories, times, keys, depth + 1)
    elif isinstance(v, list):
        for x in v[:5000]:
            walk_json(x, categories, times, keys, depth + 1)


def json_probe(p: Path) -> tuple[set[str], list[int], set[str], int | None]:
    categories: set[str] = set(); times: list[int] = []; keys: set[str] = set(); rows = None
    try:
        if p.suffix.lower() == ".jsonl":
            count = 0
            with p.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if count >= 5000:
                        break
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    walk_json(obj, categories, times, keys)
                    count += 1
            rows = count
        else:
            obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            rows = len(obj) if isinstance(obj, list) else None
            walk_json(obj, categories, times, keys)
    except Exception:
        pass
    return categories, times, keys, rows


def csv_probe(p: Path) -> tuple[set[str], list[int], set[str], int | None]:
    categories: set[str] = set(); times: list[int] = []; keys: set[str] = set(); count = 0
    try:
        with p.open(newline="", encoding="utf-8", errors="ignore") as fh:
            r = csv.DictReader(fh)
            headers = [str(x) for x in (r.fieldnames or [])]
            keys.update(headers)
            for h in headers:
                for category, pat in CATEGORY_KEYS.items():
                    if pat.search(h): categories.add(category)
            tcols = [h for h in headers if h in TIME_KEYS or h.lower() in {x.lower() for x in TIME_KEYS}]
            for row in r:
                if count >= 10000: break
                for h in tcols:
                    t = to_ms(row.get(h))
                    if t is not None and 1_500_000_000_000 <= t <= 2_000_000_000_000: times.append(t)
                count += 1
    except Exception:
        pass
    return categories, times, keys, count


def main() -> int:
    rows = []
    for p in iter_files():
        if p.suffix.lower() == ".csv":
            cats, times, keys, count = csv_probe(p)
        else:
            cats, times, keys, count = json_probe(p)
        if not cats:
            continue
        times = sorted(set(times))
        covers = bool(times and times[0] <= W1_START_MS and times[-1] >= W2_END_MS and len(times) > 1)
        rows.append({
            "path": rel(p),
            "size_bytes": p.stat().st_size,
            "categories": sorted(cats),
            "schema_keys": sorted(keys)[:120],
            "sampled_record_count": count,
            "timestamp_count": len(times),
            "min_timestamp_ms": times[0] if times else None,
            "max_timestamp_ms": times[-1] if times else None,
            "covers_W1_W2": covers,
        })
    rows.sort(key=lambda x: (not x["covers_W1_W2"], x["path"]))
    basis_cover = [x for x in rows if x["covers_W1_W2"] and "basis" in x["categories"]]
    oi_cover = [x for x in rows if x["covers_W1_W2"] and "open_interest" in x["categories"]]
    flow_cover = [x for x in rows if x["covers_W1_W2"] and "flow" in x["categories"]]
    state = "PASS_P3_ARCHIVE_HAS_HISTORICAL_BASIS_AND_FLOW" if basis_cover and (oi_cover or flow_cover) else "HOLD_P3_ARCHIVE_HISTORY_GAP"
    out = {
        "schema_version": "zel.p3.carry_flow.archive_coverage.v1",
        "state": state,
        "target_W1_start_ms": W1_START_MS,
        "target_W2_end_ms": W2_END_MS,
        "relevant_file_count": len(rows),
        "basis_W1_W2_candidates": [x["path"] for x in basis_cover],
        "open_interest_W1_W2_candidates": [x["path"] for x in oi_cover],
        "flow_W1_W2_candidates": [x["path"] for x in flow_cover],
        "rows": rows,
        "interpretation": "A file is only a source candidate if its own timestamps span fixed W1 through W2 and its schema contains the required native category. Keyword-only or point-in-time snapshots do not pass.",
        "runtime_mutated": False,
        "service_state_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
