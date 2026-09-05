"""Independent development, fresh-source and production-cost admission views."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

from backend.research.architecture_factory.g5a_source_admission_v1 import ROOT, AUTH, read, seal, file_sha, STATE_PATH, require_development
from backend.research.architecture_factory import g5a_development_data_v1 as data
from backend.research.alpha_proof.a1_alpha_proof_gate_v1 import sha
from backend.research.rebuild import g5_clean_runner_v1 as runner

OUT = "backend/research/architecture_factory/g5a_stage_admission_latest_v1.json"


def fresh_readiness(events, symbols, as_of_ms, stale):
    expected = as_of_ms // runner.INTERVAL_MS * runner.INTERVAL_MS
    latest = {s: 0 for s in symbols}; keys = set(); defects = []
    for event in events:
        p = event["payload"]
        if event["status"] == "NEW":
            runner.validate_bar(p)
            if p["bar_close_ts"] > as_of_ms:
                defects.append("FUTURE_BAR")
            if p.get("symbol") in latest:
                latest[p["symbol"]] = max(latest[p["symbol"]], p["bar_close_ts"])
        if event["status"] == "EVALUATED":
            key = event["state_key"]
            if key in keys:
                defects.append("DUPLICATE_EVALUATION")
            keys.add(key)
            if p.get("duplicate") != 0 or p.get("lookahead") != 0 or p.get("closed_bar") is not True:
                defects.append("EVALUATION_INTEGRITY")
    authority = stale.get("authority_created") is True and stale.get("authority_value") == runner.INTERVAL_MS and stale.get("authority_unit") == "ms"
    fresh = authority and not defects and all(t == expected and 0 <= as_of_ms - t < runner.INTERVAL_MS for t in latest.values())
    return {"G5B_FRESH_READY": bool(fresh), "expected_latest_closed_ms": expected,
            "last_persisted_bar_by_symbol": latest, "stale_threshold_ms": runner.INTERVAL_MS,
            "stale_authority_bound": authority, "duplicate": defects.count("DUPLICATE_EVALUATION"),
            "integrity_defects": defects, "closed_bar_integrity": not defects,
            "exactly_once_state": not defects and bool(keys), "decision": "PASS" if fresh else "HOLD_G5B_SOURCE_FRESHNESS"}


def production_ready(receipt):
    required = ("point_in_time_entry_depth", "point_in_time_exit_depth", "signed_funding_settlement_lineage",
                "fee_authority_lineage", "intrabar_execution_order_observed", "durable_ledger_parity")
    return all(receipt.get(k) is True for k in required) and receipt.get("duplicate") == 0 and receipt.get("lookahead") == 0


def development_binding(dataset_dir, root=ROOT):
    c = read(data.CONTRACT, root)
    m = data.verify_dataset(dataset_dir, c)
    expected = read("backend/research/rebuild/g5_clean_runner_contract_effective_v1.json", root)["source"]["symbols"]
    if set(m["symbols"]) != set(expected) or set(m["cost_snapshots"]) != set(expected):
        raise RuntimeError("DEVELOPMENT_UNIVERSE_PARITY")
    paths = [data.CONTRACT, c["cost_authority_path"], c["cost_ssot_path"]]
    if m["cost_authority_sha256"] != file_sha(root / c["cost_authority_path"]) or m["cost_ssot_sha256"] != file_sha(root / c["cost_ssot_path"]):
        raise RuntimeError("HOLD_COST_AUTHORITY:SSOT_DRIFT")
    costs = {}
    for symbol, row in m["cost_snapshots"].items():
        snap = json.loads((dataset_dir / row["path"]).read_text())["snapshot"]
        if snap["snapshot_sha256"] != sha({k:v for k,v in snap.items() if k != "snapshot_sha256"}):
            raise RuntimeError("HOLD_COST_AUTHORITY:SNAPSHOT_HASH")
        value = float(snap["pretrade_verified_cost_bps"])
        if not math.isfinite(value) or value <= 0:
            raise RuntimeError("HOLD_COST_AUTHORITY:INVALID_COST")
        costs[symbol] = {"fee_bps": read(c["cost_authority_path"], root)["fee"]["round_trip_fee_bps"],
                         "spread_bps": snap["charged_spread_round_trip_bps"], "impact_bps": snap["charged_impact_round_trip_bps"],
                         "funding_p95_per_settlement_bps": snap["funding_p95_abs_bps"], "reference_one_settlement_cost_bps": value,
                         "snapshot_sha256": snap["snapshot_sha256"]}
    settlements = math.ceil(c["candidate_spec"]["max_hold_bars"] * runner.INTERVAL_MS / (8 * 60 * 60 * 1000))
    hold_cost = max(x["fee_bps"]+x["spread_bps"]+x["impact_bps"]+settlements*x["funding_p95_per_settlement_bps"] for x in costs.values())
    return seal({"G5A_DEVELOPMENT_READY": True, "decision": "G5A_DEVELOPMENT_READY", "allowed_sources": ["ohlcv", "volume"],
                 "dataset_sha256": m["dataset_sha256"], "manifest_sha256": m["receipt_sha256"], "dataset_files": m["dataset_files"],
                 "symbols": m["symbols"], "splits": m["splits"], "immutable_history_verified": True,
                 "semantic_valid": True, "development_cost_model_bound": True, "development_cost_model": c["development_cost_scope"],
                 "cost_by_symbol": costs, "reference_round_trip_cost_bps": hold_cost,
                 "funding_settlements_reserved_for_frozen_hold": settlements,
                 "source_files_sha256": {p: file_sha(root / p) for p in paths}, "formal_production_credit": 0, **AUTH})



def derive(dataset_dir, data_ref, *, as_of_ms, root=ROOT):
    development = development_binding(dataset_dir, root)
    events = runner.HashChainLog(root / STATE_PATH).records()
    effective_path = "backend/research/rebuild/g5_clean_runner_contract_effective_v1.json"
    stale_path = "backend/research/rebuild/g5_data_stale_evidence_v1.json"
    fresh = fresh_readiness(events, read(effective_path, root)["source"]["symbols"], as_of_ms, read(stale_path, root))
    epoch = read(data.EPOCH, root)
    native_receipt = json.loads((dataset_dir / "native_epoch/latest.json").read_text())
    if native_receipt["receipt_sha256"] != sha({k:v for k,v in native_receipt.items() if k != "receipt_sha256"}) or native_receipt["epoch_id"] != epoch["epoch_id"] or native_receipt["boundary_ms"] != epoch["boundary_ms"]:
        raise RuntimeError("CLEAN_NATIVE_EPOCH_RECEIPT_PARITY")
    for stream in native_receipt["streams"]:
        path=dataset_dir/"native_epoch"/(stream["stream"]+".jsonl")
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        if file_sha(path)!=stream["sha256"] or len(rows)!=stream["rows"]:
            raise RuntimeError("CLEAN_NATIVE_EPOCH_LEDGER_PARITY")
        identities=set()
        for i,row in enumerate(rows):
            if row["epoch_id"]!=epoch["epoch_id"] or row["prospective_only"] is not True or data.native.canonical_sha(row["raw_payload"])!=row["source_payload_sha256"]:
                raise RuntimeError("CLEAN_NATIVE_EPOCH_LINEAGE")
            if not 0 < row["source_timestamp_ms"] <= row["collected_at_ms"] or row["collected_at_ms"] <= epoch["boundary_ms"] or (i and row["collected_at_ms"]<=rows[i-1]["collected_at_ms"]):
                raise RuntimeError("CLEAN_NATIVE_EPOCH_CLOCK")
            ident=(row["source_timestamp_ms"],row["source_payload_sha256"])
            if ident in identities: raise RuntimeError("CLEAN_NATIVE_EPOCH_DUPLICATE")
            identities.add(ident)
    return seal({"schema_version": "zel.g5a.stage_scoped_admission.v1", "as_of_ms": as_of_ms, "data_ref": data_ref,
                 "development": development, "fresh": fresh, "PRODUCTION_GRADE_READY": False,
                 "native_clean_epoch": native_receipt,
                 "production_cost_lineage": "REQUIRES_TRADE_TIME_ENTRY_EXIT_DEPTH_SIGNED_FUNDING_EXECUTION_AND_DURABLE_LEDGER",
                 "new_candidate_production_lineage_bound": False, "fresh_threshold_changed": False,
                 "source_files_sha256": {p: file_sha(root / p) for p in [STATE_PATH, effective_path, stale_path, data.CONTRACT]},
                 "historical_dataset_fresh_credit": 0, **AUTH})


def main():
    p=argparse.ArgumentParser(); p.add_argument("--data-dir",type=Path,required=True); p.add_argument("--data-ref",required=True)
    p.add_argument("--as-of-ms",type=int); p.add_argument("--output",type=Path,default=ROOT/OUT); a=p.parse_args()
    r=derive(a.data_dir,a.data_ref,as_of_ms=a.as_of_ms or runner.now_ms())
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"G5A_DEVELOPMENT_READY":r["development"]["G5A_DEVELOPMENT_READY"],"G5B_FRESH_READY":r["fresh"]["G5B_FRESH_READY"],"receipt_sha256":r["receipt_sha256"]}))


if __name__ == "__main__":
    main()
