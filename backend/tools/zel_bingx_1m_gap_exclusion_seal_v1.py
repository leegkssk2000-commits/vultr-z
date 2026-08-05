from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import zel_bingx_1m_backfill_stage_v1 as base

VERSION = "ZEL_BINGX_1M_GAP_EXCLUSION_SEAL_V1"
SCHEMA = "zel.bingx.1m_gap_exclusion.seal.v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_policy(policy: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]], int, int]:
    symbols = [str(item) for item in policy.get("symbols", [])]
    if symbols != list(base.SYMBOLS):
        raise RuntimeError("POLICY_SYMBOL_SET_MISMATCH")
    if str(policy.get("interval")) != base.INTERVAL:
        raise RuntimeError("POLICY_INTERVAL_MISMATCH")
    if policy.get("economics_inspected") is not False:
        raise RuntimeError("ECONOMICS_INSPECTION_FORBIDDEN")
    if int(policy.get("protected_mutations", -1)) != 0:
        raise RuntimeError("PROTECTED_MUTATION_POLICY_FAIL")
    if str(policy.get("execution_authority")) != "NONE" or str(policy.get("order_authority")) != "BLOCKED":
        raise RuntimeError("AUTHORITY_POLICY_FAIL")

    exclusion = policy.get("pre_registered_exclusion")
    if not isinstance(exclusion, Mapping):
        raise RuntimeError("EXCLUSION_POLICY_MISSING")
    exclusion_start = base.utc_ms(str(exclusion["start_utc"]))
    exclusion_end = base.utc_ms(str(exclusion["end_exclusive_utc"]))
    if exclusion_end <= exclusion_start or (exclusion_end - exclusion_start) % base.INTERVAL_MS:
        raise RuntimeError("INVALID_EXCLUSION_BOUNDARY")
    if exclusion.get("apply_to_all_symbols") is not True:
        raise RuntimeError("SYNCHRONIZED_EXCLUSION_REQUIRED")

    raw_segments = policy.get("sealed_segments")
    if not isinstance(raw_segments, list) or len(raw_segments) != 2:
        raise RuntimeError("EXACT_TWO_SEGMENTS_REQUIRED")
    segments: list[dict[str, Any]] = []
    for row in raw_segments:
        if not isinstance(row, Mapping):
            raise RuntimeError("SEGMENT_OBJECT_REQUIRED")
        start_ms = base.utc_ms(str(row["start_utc"]))
        end_ms = base.utc_ms(str(row["end_exclusive_utc"]))
        expected = int(row["rows_per_symbol"])
        actual = (end_ms - start_ms) // base.INTERVAL_MS
        if end_ms <= start_ms or (end_ms - start_ms) % base.INTERVAL_MS:
            raise RuntimeError(f"INVALID_SEGMENT_BOUNDARY:{row.get('segment_id')}")
        if actual != expected:
            raise RuntimeError(f"SEGMENT_ROW_COUNT_POLICY_MISMATCH:{row.get('segment_id')}")
        if not (end_ms <= exclusion_start or start_ms >= exclusion_end):
            raise RuntimeError(f"SEGMENT_OVERLAPS_EXCLUSION:{row.get('segment_id')}")
        segments.append(
            {
                "segment_id": str(row["segment_id"]),
                "start_ms": start_ms,
                "end_exclusive_ms": end_ms,
                "start_utc": canonical_utc(str(row["start_utc"])),
                "end_exclusive_utc": canonical_utc(str(row["end_exclusive_utc"])),
                "rows_per_symbol": expected,
            }
        )
    segments.sort(key=lambda item: item["start_ms"])
    if segments[0]["end_exclusive_ms"] != exclusion_start or segments[1]["start_ms"] != exclusion_end:
        raise RuntimeError("SEGMENTS_DO_NOT_BRACKET_EXCLUSION")
    expected_per_symbol = sum(int(row["rows_per_symbol"]) for row in segments)
    expected_total = expected_per_symbol * len(symbols)
    if expected_per_symbol != int(policy["expected_rows_per_symbol"]):
        raise RuntimeError("EXPECTED_ROWS_PER_SYMBOL_POLICY_MISMATCH")
    if expected_total != int(policy["expected_total_rows"]):
        raise RuntimeError("EXPECTED_TOTAL_ROWS_POLICY_MISMATCH")
    return symbols, segments, expected_per_symbol, expected_total


def stage(policy_path: Path, out_dir: Path, manifest_path: Path) -> dict[str, Any]:
    policy = read_json(policy_path)
    symbols, segments, expected_per_symbol, expected_total = validate_policy(policy)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        for segment in segments:
            result = base.collect_symbol(
                symbol,
                out_dir,
                int(segment["start_ms"]),
                int(segment["end_exclusive_ms"]),
            )
            result["segment_id"] = segment["segment_id"]
            results.append(result)

    actual_total = sum(int(row["row_count"]) for row in results)
    if actual_total != expected_total:
        raise RuntimeError("TOTAL_ROW_COUNT_MISMATCH")
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED",
        "policy_path": str(policy_path),
        "policy_sha256": base.file_sha(policy_path),
        "source": {
            "base_url": base.BASE_URL,
            "endpoint": base.ENDPOINT,
            "auth_required": False,
            "interval": base.INTERVAL,
            "safe_chunk_bars": base.SAFE_CHUNK_BARS,
        },
        "symbols": symbols,
        "segments": segments,
        "excluded_range": dict(policy["pre_registered_exclusion"]),
        "confirmed_source_gap": dict(policy["confirmed_source_gap"]),
        "expected_rows_per_symbol": expected_per_symbol,
        "expected_total_rows": expected_total,
        "actual_total_rows": actual_total,
        "results": results,
        "economics_inspected": False,
        "holdout_metrics_inspected": False,
        "strategy_rules_mutated": False,
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
        "next": "INDEPENDENT_VERIFY_AND_SEAL_EXPANDED_PARTITIONS",
    }
    manifest["dataset_sha256"] = base.stable_sha(
        [
            {
                "symbol": row["symbol"],
                "segment_id": row["segment_id"],
                "file_sha256": row["file_sha256"],
            }
            for row in sorted(results, key=lambda item: (item["symbol"], item["segment_id"]))
        ]
    )
    manifest["receipt_sha256"] = base.stable_sha(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify(manifest_path: Path, data_dir: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    if manifest.get("state") != "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_STAGED":
        raise RuntimeError("MANIFEST_STATE_NOT_PASS")
    if int(manifest.get("protected_mutations", -1)) != 0:
        raise RuntimeError("MANIFEST_PROTECTED_MUTATION_FAIL")
    if manifest.get("economics_inspected") is not False or manifest.get("holdout_metrics_inspected") is not False:
        raise RuntimeError("MANIFEST_ECONOMICS_INSPECTION_FAIL")
    results = manifest.get("results")
    if not isinstance(results, list) or len(results) != len(base.SYMBOLS) * 2:
        raise RuntimeError("MANIFEST_RESULT_COUNT_MISMATCH")
    verified: list[dict[str, Any]] = []
    total_rows = 0
    for row in results:
        if not isinstance(row, Mapping):
            raise RuntimeError("MANIFEST_RESULT_OBJECT_REQUIRED")
        path = data_dir / str(row["file"])
        if not path.is_file():
            raise RuntimeError(f"DATA_FILE_MISSING:{path}")
        if base.file_sha(path) != str(row["file_sha256"]):
            raise RuntimeError(f"DATA_FILE_SHA_MISMATCH:{path}")
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_exclusive_ms"])
        expected_count = int(row["expected_row_count"])
        timestamps: list[int] = []
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != base.CSV_FIELDS:
                raise RuntimeError(f"CSV_SCHEMA_MISMATCH:{path}")
            for csv_row in reader:
                normalized = base.normalize_row(
                    [
                        csv_row["timestamp_ms"],
                        csv_row["open"],
                        csv_row["high"],
                        csv_row["low"],
                        csv_row["close"],
                        csv_row["volume"],
                    ]
                )
                timestamps.append(int(normalized["timestamp_ms"]))
        expected_timestamps = list(base.expected_timestamps(start_ms, end_ms))
        if timestamps != expected_timestamps:
            raise RuntimeError(f"TIMESTAMP_CONTINUITY_MISMATCH:{path}")
        if len(timestamps) != expected_count:
            raise RuntimeError(f"ROW_COUNT_MISMATCH:{path}")
        if len(timestamps) != len(set(timestamps)):
            raise RuntimeError(f"DUPLICATE_TIMESTAMP:{path}")
        total_rows += len(timestamps)
        verified.append(
            {
                "symbol": str(row["symbol"]),
                "segment_id": str(row["segment_id"]),
                "row_count": len(timestamps),
                "first_timestamp_ms": timestamps[0],
                "last_timestamp_ms": timestamps[-1],
                "file_sha256": base.file_sha(path),
            }
        )
    if total_rows != int(manifest["expected_total_rows"]):
        raise RuntimeError("VERIFIED_TOTAL_ROW_COUNT_MISMATCH")
    recalculated_dataset_sha = base.stable_sha(
        [
            {
                "symbol": row["symbol"],
                "segment_id": row["segment_id"],
                "file_sha256": row["file_sha256"],
            }
            for row in sorted(verified, key=lambda item: (item["symbol"], item["segment_id"]))
        ]
    )
    if recalculated_dataset_sha != str(manifest["dataset_sha256"]):
        raise RuntimeError("DATASET_SHA_MISMATCH")
    receipt = {
        "schema_version": "zel.bingx.1m_gap_exclusion.verify.v1",
        "version": VERSION,
        "state": "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_VERIFIED",
        "manifest_sha256": base.file_sha(manifest_path),
        "dataset_sha256": recalculated_dataset_sha,
        "verified_file_count": len(verified),
        "verified_total_rows": total_rows,
        "duplicate_timestamp_count": 0,
        "missing_interval_count": 0,
        "unexpected_timestamp_count": 0,
        "economics_inspected": False,
        "holdout_metrics_inspected": False,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = base.stable_sha(receipt)
    return receipt


def self_test() -> int:
    policy = {
        "symbols": list(base.SYMBOLS),
        "interval": "1m",
        "economics_inspected": False,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "pre_registered_exclusion": {
            "start_utc": "2026-02-13T00:00:00Z",
            "end_exclusive_utc": "2026-02-14T00:00:00Z",
            "apply_to_all_symbols": True,
        },
        "sealed_segments": [
            {
                "segment_id": "PRE_GAP",
                "start_utc": "2026-01-28T08:30:00Z",
                "end_exclusive_utc": "2026-02-13T00:00:00Z",
                "rows_per_symbol": 22530,
            },
            {
                "segment_id": "POST_GAP",
                "start_utc": "2026-02-14T00:00:00Z",
                "end_exclusive_utc": "2026-06-27T08:30:00Z",
                "rows_per_symbol": 192030,
            },
        ],
        "expected_rows_per_symbol": 214560,
        "expected_total_rows": 1072800,
    }
    symbols, segments, per_symbol, total = validate_policy(policy)
    assert len(symbols) == 5 and len(segments) == 2
    assert per_symbol == 214560 and total == 1072800
    assert segments[0]["end_exclusive_ms"] == base.utc_ms("2026-02-13T00:00:00Z")
    assert segments[1]["start_ms"] == base.utc_ms("2026-02-14T00:00:00Z")
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.verify:
        if args.manifest is None or args.out_dir is None:
            parser.error("--verify requires --manifest and --out-dir")
        receipt = verify(args.manifest.resolve(), args.out_dir.resolve())
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if args.policy is None or args.out_dir is None or args.manifest is None:
        parser.error("stage requires --policy, --out-dir and --manifest")
    manifest = stage(args.policy.resolve(), args.out_dir.resolve(), args.manifest.resolve())
    print(
        json.dumps(
            {
                "state": manifest["state"],
                "actual_total_rows": manifest["actual_total_rows"],
                "dataset_sha256": manifest["dataset_sha256"],
                "receipt_sha256": manifest["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
