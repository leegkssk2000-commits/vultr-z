#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

EXPECTED_DATA_ZIP_SHA = "d90e5c6a790b8ac42ea084648b14631d397794d3a312f3bd639ef470e4fb0621"
EXPECTED_COST_ZIP_SHA = "45fc8e5bd72bfdeb9fa1cdd8999074f9b3ea6a930f6140bf7b75ddb64d76aec4"
EXPECTED_DATASET_SHA = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
EXPECTED_VERIFY_SHA = "b7d04a66c9088803521daf8f9063e032fda20dd3b541ab6e0159ce720c68ba39"
EXPECTED_SCREEN_STATE = "PASS_SCALP_GEN3_COST_RATIO_COMPLETE"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"]
TIMEFRAMES_MS = {3: 180_000, 5: 300_000, 15: 900_000}
WINDOWS_MS = {
    "research": (1769589000000, 1773619200000),
    "W1": (1773705600000, 1776384000000),
    "W2": (1776470400000, 1779062400000),
    "W3": (1779148800000, 1782549000000),
}
EXCLUDED_INTERVAL_MS = (1770940800000, 1771027200000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def safe_extract(zip_path: Path, output: Path) -> None:
    output_resolved = output.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (output / member.filename).resolve()
            if target != output_resolved and output_resolved not in target.parents:
                raise ValueError(f"zip path traversal: {member.filename}")
        archive.extractall(output)


def read_one_minute_rows(path: Path) -> list[tuple[int, float, float, float, float, float]]:
    rows: list[tuple[int, float, float, float, float, float]] = []
    previous_timestamp: int | None = None
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
        if set(reader.fieldnames or []) != required:
            raise ValueError(f"unexpected CSV header for {path}: {reader.fieldnames}")
        for source in reader:
            timestamp = int(source["timestamp_ms"])
            values = [float(source[key]) for key in ("open", "high", "low", "close", "volume")]
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"non-finite OHLCV in {path}")
            open_, high, low, close, volume = values
            if low > min(open_, close) or high < max(open_, close) or low > high or volume < 0:
                raise ValueError(f"invalid OHLCV envelope in {path} at {timestamp}")
            if previous_timestamp is not None and timestamp - previous_timestamp != 60_000:
                raise ValueError(f"1m discontinuity in {path}: {previous_timestamp}->{timestamp}")
            previous_timestamp = timestamp
            rows.append((timestamp, open_, high, low, close, volume))
    return rows


def aggregate_rows(
    rows: list[tuple[int, float, float, float, float, float]], minutes: int
) -> list[tuple[int, float, float, float, float, float]]:
    step_ms = minutes * 60_000
    aggregated: list[tuple[int, float, float, float, float, float]] = []
    bucket: list[tuple[int, float, float, float, float, float]] = []
    bucket_key: int | None = None

    def flush(current: list[tuple[int, float, float, float, float, float]]) -> None:
        if not current:
            return
        if len(current) != minutes:
            raise ValueError(f"partial {minutes}m bucket at {current[0][0]}: {len(current)} rows")
        if any(current[index][0] - current[index - 1][0] != 60_000 for index in range(1, len(current))):
            raise ValueError(f"gap inside {minutes}m bucket at {current[0][0]}")
        timestamp = current[0][0]
        if timestamp % step_ms:
            raise ValueError(f"misaligned {minutes}m bucket at {timestamp}")
        aggregated.append(
            (
                timestamp,
                current[0][1],
                max(row[2] for row in current),
                min(row[3] for row in current),
                current[-1][4],
                sum(row[5] for row in current),
            )
        )

    for row in rows:
        current_key = row[0] // step_ms
        if bucket_key is None:
            bucket_key = current_key
        if current_key != bucket_key:
            flush(bucket)
            bucket = []
            bucket_key = current_key
        bucket.append(row)
    flush(bucket)
    return aggregated


def write_deterministic_gzip(
    path: Path, rows: list[tuple[int, float, float, float, float, float]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.writer(text)
                writer.writerow(["timestamp_ms", "open", "high", "low", "close", "volume"])
                writer.writerows(rows)


def continuity_receipt(
    rows: list[tuple[int, float, float, float, float, float]], step_ms: int, allow_excluded_gap: bool
) -> tuple[int, list[tuple[int, int]], list[tuple[int, int]]]:
    duplicate_count = sum(1 for left, right in zip(rows, rows[1:]) if right[0] == left[0])
    gaps = [
        (left[0] + step_ms, right[0])
        for left, right in zip(rows, rows[1:])
        if right[0] - left[0] != step_ms
    ]
    invalid_gaps = [gap for gap in gaps if not allow_excluded_gap or gap != EXCLUDED_INTERVAL_MS]
    return duplicate_count, gaps, invalid_gaps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-zip", type=Path, required=True)
    parser.add_argument("--cost-zip", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if sha256_file(args.dataset_zip) != EXPECTED_DATA_ZIP_SHA:
        raise SystemExit("PR #575 dataset artifact ZIP SHA mismatch")
    if sha256_file(args.cost_zip) != EXPECTED_COST_ZIP_SHA:
        raise SystemExit("PR #576 terminal artifact ZIP SHA mismatch")

    shutil.rmtree(args.output, ignore_errors=True)
    args.output.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        dataset_root = temporary_root / "dataset"
        cost_root = temporary_root / "cost"
        dataset_root.mkdir()
        cost_root.mkdir()
        safe_extract(args.dataset_zip, dataset_root)
        safe_extract(args.cost_zip, cost_root)

        parent_manifest = json.loads((dataset_root / "manifest.json").read_text())
        parent_verification = json.loads((dataset_root / "verification_receipt.json").read_text())
        if parent_manifest["dataset_sha256"] != EXPECTED_DATASET_SHA:
            raise ValueError("parent dataset SHA mismatch")
        if parent_verification["receipt_sha256"] != EXPECTED_VERIFY_SHA:
            raise ValueError("parent verification receipt SHA mismatch")

        files_by_symbol: dict[str, list[tuple[int, int, Path]]] = defaultdict(list)
        for path in sorted((dataset_root / "data").glob("*.csv.gz")):
            match = re.fullmatch(r"([A-Z]+)_1m_(\d+)_(\d+)\.csv\.gz", path.name)
            if match is None:
                raise ValueError(f"unexpected parent market filename: {path.name}")
            files_by_symbol[match.group(1)].append((int(match.group(2)), int(match.group(3)), path))
        if set(files_by_symbol) != set(SYMBOLS):
            raise ValueError(f"parent symbol set mismatch: {sorted(files_by_symbol)}")

        materialized_files: list[dict[str, object]] = []
        for symbol in SYMBOLS:
            source_segments: list[tuple[int, int, list[tuple[int, float, float, float, float, float]]]] = []
            for start_ms, end_ms, path in sorted(files_by_symbol[symbol]):
                source_rows = read_one_minute_rows(path)
                if source_rows[0][0] != start_ms or source_rows[-1][0] + 60_000 != end_ms:
                    raise ValueError(f"parent boundary mismatch: {path.name}")
                source_segments.append((start_ms, end_ms, source_rows))

            for minutes, step_ms in TIMEFRAMES_MS.items():
                aggregated: list[tuple[int, float, float, float, float, float]] = []
                for _, _, source_rows in source_segments:
                    aggregated.extend(aggregate_rows(source_rows, minutes))
                for window, (window_start, window_end) in WINDOWS_MS.items():
                    window_rows = [row for row in aggregated if window_start <= row[0] < window_end]
                    if not window_rows:
                        raise ValueError(f"empty window: {symbol}/{minutes}m/{window}")
                    duplicate_count, gaps, invalid_gaps = continuity_receipt(
                        window_rows, step_ms, allow_excluded_gap=window == "research"
                    )
                    if duplicate_count or invalid_gaps:
                        raise ValueError(
                            f"continuity failure {symbol}/{minutes}m/{window}: "
                            f"duplicates={duplicate_count}, invalid_gaps={invalid_gaps[:3]}"
                        )
                    output_path = args.output / "market" / f"{minutes}m" / window / f"{symbol}.csv.gz"
                    write_deterministic_gzip(output_path, window_rows)
                    materialized_files.append(
                        {
                            "symbol": symbol,
                            "timeframe": f"{minutes}m",
                            "window": window,
                            "row_count": len(window_rows),
                            "first_timestamp_ms": window_rows[0][0],
                            "last_timestamp_ms": window_rows[-1][0],
                            "duplicate_count": duplicate_count,
                            "gaps": gaps,
                            "sha256": sha256_file(output_path),
                            "relative_path": str(output_path.relative_to(args.output)),
                        }
                    )

        screen = json.loads((cost_root / "screen.json").read_text())
        expanded = json.loads((cost_root / "expanded_receipt.json").read_text())
        baseline = json.loads((cost_root / "checkpoints/baseline-a.json").read_text())
        if screen.get("state") != EXPECTED_SCREEN_STATE:
            raise ValueError("accepted Gen3 screen state mismatch")
        all_in_cost_pct = float(baseline["body"]["h3_cost_stress"]["all_in_cost_pct"])
        if abs(all_in_cost_pct - 0.1316910918) > 1e-12:
            raise ValueError("accepted all-in cost mismatch")
        if baseline["body"]["h3_cost_stress"]["stress_lineage_complete"] is not True:
            raise ValueError("accepted cost stress lineage incomplete")
        if baseline["body"]["integrity"]["cost_lineage_complete"] is not True:
            raise ValueError("accepted trade cost lineage incomplete")

        observed_funding = {
            window: metrics["funding_pnl_estimate_usdt"]
            for window, metrics in baseline["body"]["metrics"].items()
            if window != "all"
        }
        cost_binding = {
            "artifact_id": 8950849008,
            "artifact_zip_sha256": EXPECTED_COST_ZIP_SHA,
            "input_fingerprint": baseline["input_fingerprint"],
            "screen_receipt_sha256": screen["receipt_sha256"],
            "screen_state": screen["state"],
            "expanded_manifest_sha256": expanded["manifest_sha256"],
            "all_in_cost_pct": all_in_cost_pct,
            "round_trip_fee_pct": 0.10,
            "slippage_stress_pct": 0.0216910918,
            "funding_horizon_pct": 0.01,
            "stress_lineage_complete": True,
        }
        funding_binding = {
            "artifact_id": 8950849008,
            "artifact_zip_sha256": EXPECTED_COST_ZIP_SHA,
            "funding_horizon_pct": 0.01,
            "baseline_observed_funding_pnl_estimate_usdt": observed_funding,
            "cost_lineage_complete": True,
        }
        cost_receipt_sha = canonical_sha256(cost_binding)
        funding_receipt_sha = canonical_sha256(funding_binding)
        (args.output / "cost_binding.json").write_text(
            json.dumps({**cost_binding, "receipt_sha256": cost_receipt_sha}, indent=2, sort_keys=True) + "\n"
        )
        (args.output / "funding_binding.json").write_text(
            json.dumps({**funding_binding, "receipt_sha256": funding_receipt_sha}, indent=2, sort_keys=True)
            + "\n"
        )

        references = {
            "candidate_source_sha256": sha256_file(
                args.repo_root / "backend/research/intraday_pullback_reclaim_v1.py"
            ),
            "design_receipt_sha256": sha256_file(
                args.repo_root / "backend/research/zel_scalp_design_selection_receipt_v1.json"
            ),
            "trial_plan_sha256": sha256_file(
                args.repo_root / "backend/research/zel_scalp_generation1_trial_plan_v1.json"
            ),
            "cost_receipt_sha256": cost_receipt_sha,
            "funding_receipt_sha256": funding_receipt_sha,
        }
        manifest = {
            "schema_version": "zel.scalp.materialized_dataset.v1",
            "state": "PASS_MATERIALIZED_REPLAY_INPUTS",
            "strategy_id": "intraday_pullback_reclaim_v1",
            "parent_dataset_artifact_id": 8916685107,
            "parent_dataset_zip_sha256": EXPECTED_DATA_ZIP_SHA,
            "parent_dataset_sha256": EXPECTED_DATASET_SHA,
            "parent_verification_receipt_sha256": EXPECTED_VERIFY_SHA,
            "references": references,
            "windows_ms": WINDOWS_MS,
            "excluded_interval_ms": EXCLUDED_INTERVAL_MS,
            "files": materialized_files,
            "file_count": len(materialized_files),
            "total_rows": sum(int(item["row_count"]) for item in materialized_files),
            "protected_mutations": 0,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
        manifest["manifest_receipt_sha256"] = canonical_sha256(manifest)
        (args.output / "materialized_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        print(
            json.dumps(
                {
                    "state": manifest["state"],
                    "file_count": manifest["file_count"],
                    "total_rows": manifest["total_rows"],
                    "manifest_receipt_sha256": manifest["manifest_receipt_sha256"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
