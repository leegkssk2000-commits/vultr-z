#!/usr/bin/env python3
"""Timestamp-only canonical inspection and saved-result ownership diagnosis; no replay."""
from __future__ import annotations

import csv
import gc
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.research.rebuild.scalp7_measurement_repair_v1 import (  # noqa: E402
    MINUTE,
    clock_coverage,
    continuous_contract,
    followup_admission,
    sampled_nav_dd,
    unknown_executions,
    window_measurement_status,
)

OLD = ROOT / "research/campaigns/scalp7_20261001/exact25_five_v1"
OUT = (
    ROOT
    / "research/campaigns/scalp7_20261001/measurement_exact25_closure_v1/measurement"
)
FREEZES = ROOT / "research/campaigns/scalp7_20260920/model_closure_v1/freezes"
LABELS = ["ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE"]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(name, data):
    (OUT / name).write_text(
        json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def stamps(path):
    with gzip.open(path, "rt") as handle:
        for row in csv.DictReader(handle):
            yield int(row["timestamp_ms"])


def source_contract(freeze):
    manifest = freeze["data_manifest"]
    source = manifest["source_inventory"]
    assert sha(source["path"]) == source["sha256"], "SOURCE_INVENTORY_CHANGED"
    inventory = json.loads(Path(source["path"]).read_text())
    base = Path(manifest["canonical_root"])
    hashes, coverage = {}, []
    for symbol in manifest["symbols"]:
        paths = [
            base / p
            for p in inventory
            if ("/1m/" + symbol + "/") in p or p.endswith("/" + symbol + "/1m.csv.gz")
        ]
        paths.sort(key=lambda p: next(stamps(p)))
        assert paths, "SOURCE_SYMBOL_MISSING"
        for path in paths:
            expected = inventory[str(path.relative_to(base))]
            assert sha(path) == expected, "ORIGINAL_CANONICAL_BYTES_CHANGED"
            hashes[str(path)] = expected

        def all_stamps():
            for path in paths:
                yield from stamps(path)

        coverage.append(
            clock_coverage(symbol, all_stamps(), 1757894400000, 1789430400000)
        )
    refs = [
        source,
        *[a for a in manifest["artifacts"] if a["path"].endswith("/MANIFEST.json")],
    ]
    for ref in refs:
        assert sha(ref["path"]) == ref["sha256"]
    contract = continuous_contract(coverage, refs)
    return contract, hashes


def one_result(label):
    path = OLD / "results" / (label + ".json.gz")
    result_hash = sha(path)
    with gzip.open(path, "rt") as handle:
        raw = json.load(handle)
    execution = raw["execution"]
    unknown = unknown_executions(execution["executions"])
    statuses = execution["statuses"]
    owners = []
    for item in unknown:
        order = item.get("order", {})
        position = item.get("position") or item.get("unclosed_position") or {}
        symbol = (
            order.get("symbol")
            or item.get("symbol")
            or position["episode"].split(":")[-2]
        )
        cutoff = item.get("unresolved_observed_ts_ms")
        retained = [
            s
            for s in statuses
            if s.get("symbol") == symbol
            and s.get("ts_ms", 0) >= cutoff
            and s.get("status") == "EXISTING_OWNERSHIP"
        ]
        later = [
            r
            for r in execution["ledger"]
            if r.get("symbol") == symbol and r["ts_ms"] >= cutoff
        ]
        owners.append(
            {
                "symbol": symbol,
                "state": item.get("state", item.get("status")),
                "unresolved_from_ts_ms": item.get("unresolved_from_ts_ms"),
                "unresolved_observed_ts_ms": cutoff,
                "gap_resume_or_detection_ts_ms": item.get(
                    "gap_resume_or_detection_ts_ms"
                ),
                "order_identity": order.get("identity"),
                "position": position,
                "reserved_notional": item.get("reserved_notional"),
                "preserved_ledger": item.get("ledger", []),
                "last_events": item.get("events", [])[-3:],
                "subsequent_existing_ownership_count": len(retained),
                "first_subsequent_existing_ownership": (
                    retained[0] if retained else None
                ),
                "last_subsequent_existing_ownership": (
                    retained[-1] if retained else None
                ),
                "same_symbol_later_fill_count": len(later),
                "followup_measurement_admission": followup_admission([item], symbol),
            }
        )
    scenarios = {}
    for cost, report in raw["cost_scenarios"].items():
        account = report["account"]
        times = [r["ts_ms"] for r in account["valuation"]["curve"]] if account else []
        windows = []
        for w in report["windows"]:
            expected = list(range(w["start_ts_ms"], w["end_ts_ms"] + 1, 30 * MINUTE))
            if expected[-1] != w["end_ts_ms"]:
                expected.append(w["end_ts_ms"])
            diagnostic = window_measurement_status(
                w,
                execution["executions"],
                times,
                report["episodes"],
                expected_snapshot_times=expected,
            )
            assert (
                diagnostic["cohort_complete"] == w["complete_window"]
            ), "SAVED_COHORT_RULE_DISAGREEMENT"
            windows.append(
                {
                    "name": w["name"],
                    "start_ts_ms": w["start_ts_ms"],
                    "end_ts_ms": w["end_ts_ms"],
                    "saved_complete_window": w["complete_window"],
                    "saved_DD_pct": w["DD_pct"],
                    "separate_sampled_reference_DD_pct": sampled_nav_dd(
                        account["valuation"]["curve"] if account else [],
                        w,
                        execution["executions"],
                        report["episodes"],
                        expected_snapshot_times=expected,
                    ),
                    "nav_DD_rule": "SAVED_SAMPLES_INCLUSIVE_BOUNDARIES_NO_COHORT_COMPLETENESS_GATE",
                    "saved_T_resolved": w["T_resolved"],
                    "saved_net_resolved_reference_usdt": w[
                        "net_resolved_reference_usdt"
                    ],
                    **diagnostic,
                }
            )
        scenarios[cost] = {
            "saved_account_status": report["account_status"],
            "saved_sample_count": len(times),
            "saved_first_sample_ts_ms": times[0] if times else None,
            "saved_last_sample_ts_ms": times[-1] if times else None,
            "windows": windows,
        }
    result = {
        "saved_result_path": str(path.relative_to(ROOT)),
        "storage_sha256": result_hash,
        "identity_key": raw["identity_key"],
        "binding_sha256": raw["binding_sha256"],
        "unknown_execution_count": raw["unknown_execution_count"],
        "owners": owners,
        "cost_scenarios": scenarios,
        "replay_performed": False,
        "old_result_rewritten": False,
        "new_economic_metrics": None,
    }
    del raw
    gc.collect()
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    freeze = json.loads((FREEZES / "ST_CONTROL.json").read_text())
    contract, hashes = source_contract(freeze)
    dump("CONTINUOUS_DATA_CONTRACT.json", contract)
    dump("CANONICAL_MINUTE_HASHES.json", hashes)
    print("Timestamp-only source scan completed.", flush=True)
    probe = OUT / "recovery_probe/same_source_gap_20260213_v1/SUMMARY.json"
    inspection = (
        OUT
        / "recovery_probe/same_source_gap_20260213_v1/PRESERVED_SOURCE_INSPECTION.json"
    )
    docs = [
        OLD / name
        for name in [
            "ECONOMIC_REPORT.md",
            "ECONOMIC_COMPARISON.json",
            "REGISTRY_EXPORT.json",
            "TERMINAL_RECEIPT.json",
        ]
    ]
    docs += [FREEZES.parent / "MODEL_CLOSURE.json", FREEZES / "ST_CONTROL.json"]
    preserved = {str(p.relative_to(ROOT)): sha(p) for p in docs}
    results = {}
    for label in LABELS:
        results[label] = one_result(label)
        print(label + " saved-only diagnosis completed.", flush=True)
    assert all(sha(ROOT / p) == digest for p, digest in preserved.items())
    assert all(sha(path) == digest for path, digest in hashes.items())
    audit = {
        "schema": "scalp7.measurement.source_and_ownership_audit.v1",
        "scope_key": "G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1",
        "status": "PASS_DIAGNOSIS_NOT_SOURCE_RECOVERY",
        "new_full_runs": 0,
        "source_strategy_replay": False,
        "strategy_rules_changed": False,
        "old_preserved_document_sha256": preserved,
        "canonical_file_count": len(hashes),
        "canonical_hashes_file_sha256": sha(OUT / "CANONICAL_MINUTE_HASHES.json"),
        "continuous_contract_sha256": contract["contract_sha256"],
        "source_recovery_summary": {
            "path": str(probe.relative_to(ROOT)),
            "sha256": sha(probe),
        },
        "physical_source_inspection": {
            "path": str(inspection.relative_to(ROOT)),
            "sha256": sha(inspection),
        },
        "cause": "PRESERVED_ORIGINAL_RESPONSES_LACK_20260213_2032_TO_2035_UTC_ALL_SIX_SYMBOLS",
        "recovery": "BOUNDED_SAME_PRODUCT_SOURCE_ATTEMPT_RECOVERED_ZERO_OF_24_MINUTES",
        "loader_join": "FOUR_MISSING_MINUTES_EXIST_IN_RAW_SOURCE_NOT_ONLY_LOADER",
        "ownership": "UNKNOWN_HELD_POSITIONS_RETAINED_AND_SAME_SYMBOL_SUBSEQUENT_ADMISSION_BLOCKED",
        "reporting": "COHORT_COMPLETENESS_AND_SAMPLED_NAV_COVERAGE_ARE_SEPARATE_DIAGNOSTICS",
        "funding_status": "UNKNOWN_NOT_ZERO",
        "economic_comparison_status": "UNMEASURED",
        "original_inputs_unchanged": True,
        "results": results,
        "next_execution": "REQUIRES_NEW_HASH_BOUND_IDENTITIES_AND_NEW_FULL_APPROVAL",
    }
    dump("SOURCE_AND_OWNERSHIP_AUDIT.json", audit)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "new_full_runs": 0,
                "canonical_files": len(hashes),
                "segments": contract["segments"],
            }
        )
    )


if __name__ == "__main__":
    main()
