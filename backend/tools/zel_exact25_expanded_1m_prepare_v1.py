from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_EXACT25_EXPANDED_1M_PREPARE_V1"
SCHEMA = "zel.exact25.expanded_1m.prepare.v1"
INTERVAL_MS = 60_000
CSV_FIELDS = ("timestamp_ms", "open", "high", "low", "close", "volume")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT")
WINDOWS = (
    ("1m_w1", "W1_PRE", 1769589000000, 1770940800000),
    ("1m_w1", "W1_POST", 1771027200000, 1774773000000),
    ("1m_w2", "W2", 1774773000000, 1779957000000),
    ("1m_w3", "W3", 1779957000000, 1785141000000),
)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_no_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeError(f"SYMLINK_ROOT_FORBIDDEN:{root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"SYMLINK_INPUT_FORBIDDEN:{path}")


def rows_from_csv(path: Path) -> Iterable[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise RuntimeError(f"CSV_SCHEMA_MISMATCH:{path}:{reader.fieldnames}")
        for row in reader:
            yield {key: str(row[key]) for key in CSV_FIELDS}


def load_symbol_rows(base_root: Path, sealed_root: Path, symbol: str) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    candidates = sorted((sealed_root / "data").glob(f"{symbol}_1m_*.csv.gz"))
    candidates += [base_root / "market" / "1m" / window / f"{symbol}.csv" for window in ("1m_w1", "1m_w2", "1m_w3")]
    for path in candidates:
        if not path.is_file():
            raise RuntimeError(f"MARKET_FILE_MISSING:{path}")
        for row in rows_from_csv(path):
            timestamp = int(row["timestamp_ms"])
            prior = rows.get(timestamp)
            if prior is not None and prior != row:
                raise RuntimeError(f"CONFLICTING_DUPLICATE:{symbol}:{timestamp}")
            rows[timestamp] = row
    return rows


def write_segment(path: Path, rows: Mapping[int, Mapping[str, str]], start_ms: int, end_ms: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    prior: int | None = None
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for timestamp in range(start_ms, end_ms, INTERVAL_MS):
            row = rows.get(timestamp)
            if row is None:
                raise RuntimeError(f"EXPANDED_SEGMENT_GAP:{path}:{timestamp}")
            if prior is not None and timestamp - prior != INTERVAL_MS:
                raise RuntimeError(f"EXPANDED_SEGMENT_NONCONTIGUOUS:{path}:{prior}:{timestamp}")
            writer.writerow(row)
            prior = timestamp
            count += 1
    expected = (end_ms - start_ms) // INTERVAL_MS
    if count != expected:
        raise RuntimeError(f"EXPANDED_SEGMENT_COUNT_MISMATCH:{path}:{count}:{expected}")
    return {
        "row_count": count,
        "sha256": file_sha(path),
        "start_ms": start_ms,
        "end_exclusive_ms": end_ms,
        "first_timestamp_ms": start_ms,
        "last_timestamp_ms": end_ms - INTERVAL_MS,
        "missing_interval_count": 0,
        "duplicate_timestamp_count": 0,
    }


def choose_template(entries: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    for row in entries:
        if str(row.get("symbol") or "").replace("-", "") == symbol:
            return copy.deepcopy(row)
    if entries:
        return copy.deepcopy(entries[0])
    return {"kind": "market", "interval": "1m"}


def manifest_row(template: Mapping[str, Any], *, symbol: str, window_id: str, relative_path: str, result: Mapping[str, Any], source_dataset_sha: str) -> dict[str, Any]:
    row = copy.deepcopy(dict(template))
    row.update({
        "kind": "market",
        "interval": "1m",
        "data_interval": "1m",
        "window_id": window_id,
        "window": window_id.replace("1m_", ""),
        "symbol": symbol,
        "path": relative_path,
        "sha256": result["sha256"],
        "file_sha256": result["sha256"],
        "data_source_sha256": result["sha256"],
        "row_count": result["row_count"],
        "start_ms": result["start_ms"],
        "end_exclusive_ms": result["end_exclusive_ms"],
        "source_dataset_sha256": source_dataset_sha,
    })
    return row


def run(base_root: Path, sealed_root: Path, out_root: Path, receipt_out: Path) -> dict[str, Any]:
    validate_no_symlinks(base_root)
    validate_no_symlinks(sealed_root)
    sealed_manifest = read_json(sealed_root / "manifest.json")
    sealed_verify = read_json(sealed_root / "verification_receipt.json")
    expected_dataset_sha = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
    expected_verify_sha = "b7d04a66c9088803521daf8f9063e032fda20dd3b541ab6e0159ce720c68ba39"
    if sealed_manifest.get("dataset_sha256") != expected_dataset_sha or sealed_verify.get("dataset_sha256") != expected_dataset_sha:
        raise RuntimeError("SEALED_DATASET_SHA_MISMATCH")
    if sealed_verify.get("receipt_sha256") != expected_verify_sha or sealed_verify.get("state") != "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_VERIFIED":
        raise RuntimeError("SEALED_DATASET_NOT_PASS")
    if int(sealed_verify.get("verified_total_rows") or 0) != 1_072_800 or int(sealed_verify.get("verified_file_count") or 0) != 10:
        raise RuntimeError("SEALED_DATASET_COUNT_MISMATCH")
    if any(int(sealed_verify.get(key) or 0) != 0 for key in ("duplicate_timestamp_count", "missing_interval_count", "unexpected_timestamp_count")):
        raise RuntimeError("SEALED_DATASET_INTEGRITY_FAIL")
    if out_root.exists():
        shutil.rmtree(out_root)
    shutil.copytree(base_root, out_root, symlinks=False)
    one_minute_root = out_root / "market" / "1m"
    if one_minute_root.exists():
        shutil.rmtree(one_minute_root)
    one_minute_root.mkdir(parents=True)
    manifest_path = out_root / "manifest.json"
    manifest = read_json(manifest_path)
    old_files = manifest.get("files")
    if not isinstance(old_files, list):
        raise RuntimeError("BASE_MANIFEST_FILES_MISSING")
    removed_1m = [dict(row) for row in old_files if isinstance(row, Mapping) and row.get("kind") == "market" and str(row.get("interval")) == "1m"]
    if len(removed_1m) != 15:
        raise RuntimeError(f"BASE_1M_TEMPLATE_COUNT_MISMATCH:{len(removed_1m)}")
    preserved = [row for row in old_files if not (isinstance(row, Mapping) and row.get("kind") == "market" and str(row.get("interval")) == "1m")]
    outputs: list[dict[str, Any]] = []
    new_manifest_rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        rows = load_symbol_rows(base_root, sealed_root, symbol)
        template = choose_template(removed_1m, symbol)
        for window_id, segment_id, start_ms, end_ms in WINDOWS:
            relative = Path("market") / "1m" / window_id / f"{symbol}_{segment_id}.csv"
            result = write_segment(out_root / relative, rows, start_ms, end_ms)
            output = {
                "symbol": symbol,
                "window_id": window_id,
                "segment_id": segment_id,
                "relative_path": relative.as_posix(),
                **result,
            }
            outputs.append(output)
            new_manifest_rows.append(manifest_row(template, symbol=symbol, window_id=window_id, relative_path=relative.as_posix(), result=result, source_dataset_sha=expected_dataset_sha))
    manifest["files"] = preserved + new_manifest_rows
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["expanded_1m"] = {
        "version": VERSION,
        "source_pr": 575,
        "source_artifact_id": 8916685107,
        "source_artifact_digest": "sha256:d90e5c6a790b8ac42ea084648b14631d397794d3a312f3bd639ef470e4fb0621",
        "source_dataset_sha256": expected_dataset_sha,
        "source_verification_receipt_sha256": expected_verify_sha,
        "excluded_utc_day": ["2026-02-13T00:00:00Z", "2026-02-14T00:00:00Z"],
        "window_boundaries": {
            "1m_w1": ["2026-01-28T08:30:00Z", "2026-03-29T08:30:00Z"],
            "1m_w2": ["2026-03-29T08:30:00Z", "2026-05-28T08:30:00Z"],
            "1m_w3": ["2026-05-28T08:30:00Z", "2026-07-27T08:30:00Z"],
        },
        "segment_count": len(outputs),
        "row_count": sum(int(row["row_count"]) for row in outputs),
    }
    manifest["expanded_1m"]["partition_sha256"] = stable_sha([
        {key: row[key] for key in ("symbol", "window_id", "segment_id", "relative_path", "row_count", "sha256", "start_ms", "end_exclusive_ms")}
        for row in outputs
    ])
    atomic_json(manifest_path, manifest)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EXPANDED_1M_PARTITIONS_PREPARED",
        "base_root": str(base_root),
        "out_root": str(out_root),
        "source_dataset_sha256": expected_dataset_sha,
        "source_verification_receipt_sha256": expected_verify_sha,
        "manifest_sha256": file_sha(manifest_path),
        "partition_sha256": manifest["expanded_1m"]["partition_sha256"],
        "market_file_count": len(outputs),
        "total_1m_rows": sum(int(row["row_count"]) for row in outputs),
        "outputs": outputs,
        "duplicate_timestamp_count": 0,
        "missing_interval_count": 0,
        "unexpected_timestamp_count": 0,
        "economics_inspected": False,
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
        "next": "RUN_SCALP_GEN3_COST_RATIO_REPLAY",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    atomic_json(receipt_out, receipt)
    return receipt


def self_test() -> int:
    assert (1770940800000 - 1769589000000) // INTERVAL_MS == 22_530
    assert (1774773000000 - 1771027200000) // INTERVAL_MS == 62_430
    assert (1779957000000 - 1774773000000) // INTERVAL_MS == 86_400
    assert (1785141000000 - 1779957000000) // INTERVAL_MS == 86_400
    assert sum((end - start) // INTERVAL_MS for _, _, start, end in WINDOWS) == 257_760
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", type=Path)
    parser.add_argument("--sealed-root", type=Path)
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.base_root, args.sealed_root, args.out_root, args.receipt_out)):
        parser.error("base-root, sealed-root, out-root, receipt-out required")
    receipt = run(args.base_root.resolve(), args.sealed_root.resolve(), args.out_root.resolve(), args.receipt_out.resolve())
    print(json.dumps({"state": receipt["state"], "partition_sha256": receipt["partition_sha256"], "total_1m_rows": receipt["total_1m_rows"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
