#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.tools import zel_bingx_1m_backfill_stage_v1 as backfill

SCHEMA = "zel.six_symbol_5m_180d_shared_cache.v2"
SOURCE_BLOB = "73a1218dfd9427743728fc943f33abef759640e8"
ONE_MIN_MS = 60_000
FIVE_MIN_MS = 300_000
DAYS = 180
ROWS_1M = DAYS * 24 * 60
ROWS_5M = DAYS * 24 * 12
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")


def stable_sha(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def freeze(root: Path) -> dict[str, Any]:
    path = root / "FREEZE.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    end_exclusive = (int(time.time() * 1000) // FIVE_MIN_MS) * FIVE_MIN_MS
    start = end_exclusive - DAYS * 24 * 60 * 60 * 1000
    value = {
        "schema": SCHEMA,
        "state": "FROZEN_BEFORE_FETCH",
        "start_ms": start,
        "end_exclusive_ms": end_exclusive,
        "rows_1m": ROWS_1M,
        "rows_5m": ROWS_5M,
        "symbols": list(SYMBOLS),
        "source_blob": SOURCE_BLOB,
        "created_at_ms": int(time.time() * 1000),
    }
    value["contract_sha256"] = stable_sha(value)
    atomic_json(path, value)
    return value


def load_1m(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != ROWS_1M:
        raise RuntimeError(f"ROWS_1M_MISMATCH:{len(rows)}:{ROWS_1M}")
    return rows


def aggregate_5m(
    rows: list[dict[str, Any]], start_ms: int, expected_rows_5m: int = ROWS_5M
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(rows), 5):
        chunk = rows[i : i + 5]
        if len(chunk) != 5:
            raise RuntimeError("INCOMPLETE_5M_BUCKET")
        expected = [start_ms + (i + j) * ONE_MIN_MS for j in range(5)]
        actual = [int(x["timestamp_ms"]) for x in chunk]
        if actual != expected:
            raise RuntimeError(f"TIMESTAMP_GAP:{i}:{actual[:2]}:{expected[:2]}")
        out.append(
            {
                "timestamp_ms": actual[0],
                "open": float(chunk[0]["open"]),
                "high": max(float(x["high"]) for x in chunk),
                "low": min(float(x["low"]) for x in chunk),
                "close": float(chunk[-1]["close"]),
                "volume": sum(float(x["volume"]) for x in chunk),
            }
        )
    if len(out) != expected_rows_5m:
        raise RuntimeError(f"ROWS_5M_MISMATCH:{len(out)}:{expected_rows_5m}")
    return out


def write_5m(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return file_sha(path)


def fetch_symbol(root: Path, symbol: str, frozen: dict[str, Any]) -> dict[str, Any]:
    receipt_path = root / "receipts" / f"{symbol.replace('-', '')}.json"
    data_path = root / "data" / f"{symbol.replace('-', '')}_5m.jsonl.gz"
    if receipt_path.exists() and data_path.exists():
        old = json.loads(receipt_path.read_text(encoding="utf-8"))
        if old.get("state") == "PASS_EXACT_1M_TO_5M_180D" and old.get(
            "data_sha256"
        ) == file_sha(data_path):
            return old
    raw_dir = root / "raw_1m"
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta = backfill.collect_symbol(
        symbol, raw_dir, int(frozen["start_ms"]), int(frozen["end_exclusive_ms"])
    )
    raw_path = raw_dir / meta["file"]
    rows_1m = load_1m(raw_path)
    rows_5m = aggregate_5m(rows_1m, int(frozen["start_ms"]))
    data_sha = write_5m(data_path, rows_5m)
    receipt = {
        "schema": SCHEMA,
        "state": "PASS_EXACT_1M_TO_5M_180D",
        "symbol": symbol,
        "rows_1m": len(rows_1m),
        "rows_5m": len(rows_5m),
        "request_count": meta["request_count"],
        "start_ms": int(frozen["start_ms"]),
        "end_exclusive_ms": int(frozen["end_exclusive_ms"]),
        "source_file_sha256": meta["file_sha256"],
        "data_path": str(data_path),
        "data_sha256": data_sha,
        "source_blob": SOURCE_BLOB,
        "synthetic_fill": False,
        "forward_fill": False,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    atomic_json(receipt_path, receipt)
    return receipt


def manifest(
    root: Path, frozen: dict[str, Any], receipts: list[dict[str, Any]]
) -> dict[str, Any]:
    ok = len(receipts) == len(SYMBOLS) and all(
        x.get("state") == "PASS_EXACT_1M_TO_5M_180D" for x in receipts
    )
    value = {
        "schema": SCHEMA,
        "state": "PASS_SHARED_CACHE_COMPLETE" if ok else "PARTIAL_SHARED_CACHE",
        "symbols": list(SYMBOLS),
        "completed_symbols": [x["symbol"] for x in receipts],
        "rows_5m_per_symbol": ROWS_5M,
        "total_rows_5m": sum(int(x.get("rows_5m", 0)) for x in receipts),
        "freeze_contract_sha256": frozen["contract_sha256"],
        "source_blob": SOURCE_BLOB,
        "receipts": receipts,
        "updated_at_ms": int(time.time() * 1000),
    }
    value["manifest_sha256"] = stable_sha(value)
    atomic_json(root / "MANIFEST.json", value)
    return value


def self_test() -> int:
    assert ROWS_1M == 259_200 and ROWS_5M == 51_840
    sample = [
        {
            "timestamp_ms": str(i * ONE_MIN_MS),
            "open": "10",
            "high": str(11 + i),
            "low": "9",
            "close": str(10 + i),
            "volume": "2",
        }
        for i in range(5)
    ]
    out = aggregate_5m(sample, 0, expected_rows_5m=1)
    assert (
        len(out) == 1
        and out[0]["open"] == 10
        and out[0]["close"] == 14
        and out[0]["volume"] == 10
    )
    print("PASS_SIX_SYMBOL_5M_180D_SHARED_CACHE_V2_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--root", type=Path, default=Path("out/six_symbol_5m_180d_shared_cache_v2")
    )
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    frozen = freeze(root)
    selected = [x.strip() for x in args.symbols.split(",") if x.strip()]
    receipts: list[dict[str, Any]] = []
    for symbol in selected:
        if symbol not in SYMBOLS:
            raise RuntimeError(f"UNSUPPORTED_SYMBOL:{symbol}")
        receipt = fetch_symbol(root, symbol, frozen)
        receipts.append(receipt)
        current = manifest(root, frozen, receipts)
        print(
            f"CACHE_SYMBOL={symbol} rows_5m={receipt['rows_5m']} requests={receipt['request_count']} state={receipt['state']}",
            flush=True,
        )
    current = manifest(root, frozen, receipts)
    print(
        "SHARED_CACHE="
        + json.dumps(
            {
                "state": current["state"],
                "completed": current["completed_symbols"],
                "total_rows_5m": current["total_rows_5m"],
                "root": str(root),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
