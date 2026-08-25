#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "backend/research/g4_bingx_1m_gap_exclusion_policy_v1.json"
DEFAULT_OUT = ROOT / "backend/research/g4_bingx_1m_gap_exclusion_seal_latest.json"
SCHEMA = "zel.g4.bingx.1m_gap_exclusion.seal.v1"
INTERVAL_MS = 60_000
EXPECTED_SYMBOLS = ["BTC-USDT", "ETH-USDT", "LINK-USDT", "SOL-USDT", "XRP-USDT"]


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def utc_ms(text: str) -> int:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("POLICY_OBJECT_REQUIRED")
    return value


def seal(policy_path: Path, out: Path) -> dict[str, Any]:
    p = read(policy_path)
    if p.get("schema_version") != "zel.g4.bingx.1m_gap_exclusion.policy.v1":
        raise RuntimeError("POLICY_SCHEMA_MISMATCH")
    if p.get("symbols") != EXPECTED_SYMBOLS or p.get("interval") != "1m":
        raise RuntimeError("FROZEN_SOURCE_IDENTITY_MISMATCH")
    if p.get("economics_inspected_before_exclusion") is not False or p.get("holdout_metrics_inspected_before_exclusion") is not False:
        raise RuntimeError("EXCLUSION_NOT_PREREGISTERED_BEFORE_ECONOMICS")
    if p.get("synthetic_interpolation_allowed") is not False:
        raise RuntimeError("SYNTHETIC_FILL_FORBIDDEN")
    if int(p.get("protected_mutations", -1)) != 0:
        raise RuntimeError("PROTECTED_MUTATION_POLICY_FAIL")
    if p.get("execution_authority") != "NONE" or p.get("order_authority") != "BLOCKED":
        raise RuntimeError("AUTHORITY_POLICY_FAIL")

    original = p["frozen_original_range"]
    start = utc_ms(original["start_utc"])
    end = utc_ms(original["end_exclusive_utc"])
    if (end - start) // INTERVAL_MS != int(original["rows_per_symbol"]):
        raise RuntimeError("ORIGINAL_ROW_GEOMETRY_MISMATCH")
    if int(original["total_rows"]) != int(original["rows_per_symbol"]) * len(EXPECTED_SYMBOLS):
        raise RuntimeError("ORIGINAL_TOTAL_MISMATCH")

    gap = p["confirmed_source_gap"]
    missing = [int(x) for x in gap["timestamps_ms"]]
    if gap.get("symbol") != "BTC-USDT" or len(missing) != 4:
        raise RuntimeError("CONFIRMED_GAP_IDENTITY_MISMATCH")
    if missing != list(range(missing[0], missing[0] + 4 * INTERVAL_MS, INTERVAL_MS)):
        raise RuntimeError("CONFIRMED_GAP_NOT_EXACT_FOUR_CONTIGUOUS_MINUTES")
    if int(gap.get("official_endpoint_reconciliation_requests", 0)) < 3 or int(gap.get("recovered_rows", -1)) != 0:
        raise RuntimeError("SOURCE_RECONCILIATION_EVIDENCE_MISMATCH")
    if gap.get("synthetic_fill_allowed") is not False:
        raise RuntimeError("GAP_SYNTHETIC_FILL_NOT_BLOCKED")

    ex = p["pre_registered_exclusion"]
    ex_start = utc_ms(ex["start_utc"])
    ex_end = utc_ms(ex["end_exclusive_utc"])
    if ex.get("apply_to_all_symbols") is not True or ex.get("alignment") != "UTC_DAY":
        raise RuntimeError("SYNCHRONIZED_UTC_DAY_EXCLUSION_REQUIRED")
    if ex_end - ex_start != 1440 * INTERVAL_MS:
        raise RuntimeError("EXCLUSION_MUST_BE_ONE_UTC_DAY")
    if not all(ex_start <= ts < ex_end for ts in missing):
        raise RuntimeError("GAP_NOT_CONTAINED_BY_EXCLUSION")

    segments = p["sealed_segments"]
    if not isinstance(segments, list) or len(segments) != 2:
        raise RuntimeError("EXACT_TWO_SEALED_SEGMENTS_REQUIRED")
    rows = 0
    for seg in segments:
        a = utc_ms(seg["start_utc"])
        b = utc_ms(seg["end_exclusive_utc"])
        n = (b - a) // INTERVAL_MS
        if n != int(seg["rows_per_symbol"]):
            raise RuntimeError(f"SEGMENT_ROW_MISMATCH:{seg.get('segment_id')}")
        if not (b <= ex_start or a >= ex_end):
            raise RuntimeError(f"SEGMENT_OVERLAPS_EXCLUSION:{seg.get('segment_id')}")
        rows += n
    if rows != int(p["expected_rows_per_symbol"]):
        raise RuntimeError("SEALED_ROWS_PER_SYMBOL_MISMATCH")
    if rows * len(EXPECTED_SYMBOLS) != int(p["expected_total_rows"]):
        raise RuntimeError("SEALED_TOTAL_ROWS_MISMATCH")

    result = {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_G4_BINGX_GAP_EXCLUSION_SEALED",
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "source_reconciliation_run_id": p["source_reconciliation_run_id"],
        "source_gap_minutes": len(missing),
        "excluded_utc_day": [ex["start_utc"], ex["end_exclusive_utc"]],
        "sealed_segment_ids": [x["segment_id"] for x in segments],
        "usable_rows_per_symbol": rows,
        "usable_total_rows": rows * len(EXPECTED_SYMBOLS),
        "coverage_retained_pct": 100.0 * rows / int(original["rows_per_symbol"]),
        "synthetic_rows_added": 0,
        "economics_inspected": False,
        "holdout_metrics_inspected": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "G4_H5_ROUTE_USING_GAP_EXCLUDED_COVERAGE_POLICY",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    p = read(DEFAULT_POLICY)
    assert p["expected_rows_per_symbol"] == 214560
    assert p["expected_total_rows"] == 1072800
    assert p["confirmed_source_gap"]["timestamps_ms"] == [1771014720000, 1771014780000, 1771014840000, 1771014900000]
    assert utc_ms("2026-02-13T20:32:00Z") == 1771014720000
    print("PASS_G4_BINGX_GAP_EXCLUSION_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = seal(args.policy.resolve(), args.out.resolve())
    print(json.dumps({"state": r["state"], "usable_total_rows": r["usable_total_rows"], "coverage_retained_pct": r["coverage_retained_pct"], "receipt": r["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
