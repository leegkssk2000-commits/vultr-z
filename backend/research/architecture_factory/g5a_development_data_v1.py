"""Immutable historical acquisition and a separate prospective native epoch. No replay."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from backend.research.architecture_factory.g5a_source_admission_v1 import AUTH, ROOT, file_sha, read, seal
from backend.research.alpha_proof.a1_alpha_proof_gate_v1 import sha
from backend.research.rebuild import g5_clean_runner_v1 as runner
from backend.research.rebuild import a1_rebuilt_bb_revert_evaluator_v1 as costs
from backend.research import p3_prospective_native_feature_collector as native

CONTRACT = "backend/research/contracts/g5a_stage_source_cost_contract_v1.json"
EPOCH = "backend/research/contracts/p3_clean_native_epoch_v1.json"
DATA = "research/data/g5a_stage_v1"


def write_once(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    if path.exists() and path.read_text() != raw:
        raise RuntimeError("IMMUTABLE_FILE_EXISTS:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw)


def validate_history(rows, cutoff, *, archive=False):
    if not rows:
        raise RuntimeError("EMPTY_DEVELOPMENT_HISTORY")
    for row in rows:
        runner.validate_bar(row)
        if row["bar_close_ts"] > cutoff or row["bar_open_ts"] % runner.INTERVAL_MS:
            raise RuntimeError("HISTORICAL_LOOKAHEAD_OR_TIMESTAMP")
    times = [r["bar_open_ts"] for r in rows]
    if len(times) != len(set(times)):
        raise RuntimeError("HISTORICAL_DUPLICATE")
    gaps = [{"previous_open_ms": a, "next_open_ms": b, "missing_bars": (b-a)//runner.INTERVAL_MS-1} for a,b in zip(times,times[1:]) if b-a != runner.INTERVAL_MS]
    if any(b <= a for a,b in zip(times,times[1:])) or (gaps and not archive):
        raise RuntimeError("HISTORICAL_GAP_OR_ORDER")
    return {"bars": len(rows), "first_open_ms": times[0], "last_close_ms": rows[-1]["bar_close_ts"],
            "missing": sum(g["missing_bars"] for g in gaps), "gap": len(gaps), "gaps": gaps, "duplicate": 0, "lookahead": 0}


def collect_symbol(adapter, symbol, cutoff, max_pages):
    end = cutoff - runner.INTERVAL_MS
    by_time, pages = {}, []
    for _ in range(max_pages):
        params = {"symbol": symbol, "interval": "4h", "limit": adapter.config["page_limit"], "endTime": end}
        payload, received = adapter._request(params)
        page = sorted(adapter._decode(payload), key=lambda x: x["bar_open_ts"])
        raw = payload.get("data", []) if isinstance(payload, dict) else payload
        if len(page) != len(raw):
            raise RuntimeError("HISTORICAL_DECODE_DROPPED_ROWS:" + symbol)
        pages.append({"request": params, "received_ms": received, "payload_sha256": sha(payload), "decoded_rows": len(page)})
        if not page:
            return [by_time[k] for k in sorted(by_time)], pages, "EMPTY_OLDER_PAGE"
        if page[0]["bar_open_ts"] > end:
            # Some endpoints clamp older requests to their oldest available page.
            if not all(r["bar_open_ts"] in by_time and by_time[r["bar_open_ts"]] == r for r in page):
                raise RuntimeError("UNVERIFIED_HISTORY_BOUNDARY:" + symbol)
            return [by_time[k] for k in sorted(by_time)], pages, "VERIFIED_ENDPOINT_CLAMP"
        for row in page:
            if row["bar_close_ts"] > cutoff:
                raise RuntimeError("UNREQUESTED_FORMING_OR_FUTURE_BAR")
            key = row["bar_open_ts"]
            if key in by_time and by_time[key] != row:
                raise RuntimeError("HISTORICAL_DUPLICATE_CONFLICT")
            by_time[key] = row
        end = page[0]["bar_open_ts"] - 1
    raise RuntimeError("HOLD_DEVELOPMENT_DATA_AUTHORITY:PAGE_BUDGET_NOT_HISTORY_EXHAUSTION")


def freeze_split(metadata, contract):
    start = max(x["first_open_ms"] for x in metadata.values())
    end = min(x["last_close_ms"] for x in metadata.values())
    count = (end - start) // runner.INTERVAL_MS
    split = contract["split"]
    first = start + int(count * split["development_fraction"]) * runner.INTERVAL_MS
    second = start + int(count * (split["development_fraction"] + split["validation_fraction"])) * runner.INTERVAL_MS
    gap = split["embargo_bars"] * runner.INTERVAL_MS
    if first <= start or second <= first + gap or end <= second + gap:
        raise RuntimeError("HOLD_DEVELOPMENT_DATA_AUTHORITY:EMPTY_PURGED_SPLIT")
    return {"development": [start, first], "validation": [first + gap, second],
            "purged_OOS": [second + gap, end], "interval_semantics": "BAR_OPEN_START_INCLUSIVE_END_EXCLUSIVE; TRADE_EXIT_BEFORE_SPLIT_END",
            "prospective_boundary_ms": contract["prospective_boundary_ms"], "embargo_bars": split["embargo_bars"],
            "frozen_before_outcomes": True, "common_calendar_all_frozen_symbols": True}


def acquire(root, output):
    c = read(CONTRACT, root); effective = read("backend/research/rebuild/g5_clean_runner_contract_effective_v1.json", root)
    if c["receipt_sha256"] != sha({k:v for k,v in c.items() if k != "receipt_sha256"}):
        raise RuntimeError("FROZEN_CONTRACT_HASH")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "development_manifest.json"
    if manifest_path.exists():
        verify_dataset(output, c)
        return json.loads(manifest_path.read_text())
    adapter = runner.BingxSourceAdapter(effective)
    symbols = effective["source"]["symbols"]
    metadata, sources, dataset_files, snapshots, raw_files = {}, {}, {}, {}, {}
    authority = read(c["cost_authority_path"], root)
    for symbol in symbols:
        rows, pages, termination = collect_symbol(adapter, symbol, c["historical_cutoff_close_ms"], c["max_capture_pages_per_symbol"])
        path = output / "raw_ohlcv" / (symbol + ".json")
        write_once(path, rows); raw_files[str(path.relative_to(output))] = file_sha(path)
        gaps = [{"index": i, "previous_open_ms": a["bar_open_ts"], "next_open_ms": b["bar_open_ts"], "gap_ms": b["bar_open_ts"] - a["bar_open_ts"]} for i, (a, b) in enumerate(zip(rows, rows[1:])) if b["bar_open_ts"] - a["bar_open_ts"] != runner.INTERVAL_MS]
        if gaps:
            write_once(output / "raw_gap_audit" / (symbol + ".json"), {"symbol": symbol, "bars": len(rows), "gaps": gaps, "pages": pages})
            print(json.dumps({"HISTORICAL_GAPS": symbol, "bars": len(rows), "gap_count": len(gaps), "first_gaps": gaps[:8]}), flush=True)
        metadata[symbol] = validate_history(rows, c["historical_cutoff_close_ms"], archive=True)
        sources[symbol] = {"pages": pages, "termination": termination, "source_sha256": sha(pages)}
        requests = []; original = costs.request_json
        def capture(url, params):
            started = runner.now_ms(); raw = original(url, params); received = runner.now_ms()
            requests.append({"url": url, "params": params, "requested_ms": started, "received_ms": received,
                             "payload_sha256": sha(raw), "payload": raw})
            return raw
        costs.request_json = capture
        try:
            snapshot = costs.fetch_execution_snapshot(symbol, authority)
        finally:
            costs.request_json = original
        if any(not math.isfinite(float(snapshot[k])) or snapshot[k] < 0 for k in ("pretrade_verified_cost_bps", "funding_p95_abs_bps", "charged_spread_round_trip_bps", "charged_impact_round_trip_bps")):
            raise RuntimeError("HOLD_COST_AUTHORITY:INVALID_COST")
        path = output / "cost" / (symbol + ".json")
        write_once(path, {"snapshot": snapshot, "requests": requests, "scope": c["development_cost_scope"], "formal_credit": 0})
        snapshots[symbol] = {"path": str(path.relative_to(output)), "sha256": file_sha(path),
                             "reference_one_settlement_cost_bps": snapshot["pretrade_verified_cost_bps"]}
    # The precommitted common-calendar split excludes pre-listing tails by date,
    # before any strategy outcomes. Preserve all available raw history separately.
    splits = freeze_split(metadata, c)
    qualified = {}
    for symbol in symbols:
        raw = json.loads((output / "raw_ohlcv" / (symbol + ".json")).read_text())
        rows = [r for r in raw if splits["development"][0] <= r["bar_open_ts"] < splits["purged_OOS"][1]]
        qualified[symbol] = validate_history(rows, c["historical_cutoff_close_ms"])
        path = output / "ohlcv" / (symbol + ".json")
        write_once(path, rows); dataset_files[str(path.relative_to(output))] = file_sha(path)
    receipt = seal({"schema_version": "zel.g5a.immutable_development_dataset.v1", "dataset_id": c["development_dataset_id"],
                    "collection_started_after_freeze": True, "collection_finished_ms": runner.now_ms(),
                    "contract_sha256": c["receipt_sha256"], "dataset_files": dataset_files, "dataset_sha256": sha(dataset_files),
                    "symbols": qualified, "raw_symbols": metadata, "raw_dataset_files": raw_files,
                    "sources": sources, "splits": splits, "pre_common_calendar_rows_role": "AUDIT_ONLY_NEVER_OUTCOME_SELECTED",
                    "cost_snapshots": snapshots, "cost_scope": c["development_cost_scope"],
                    "collection_code_sha256": file_sha(Path(__file__)), "source_adapter_sha256": file_sha(root / "backend/research/rebuild/g5_clean_runner_v1.py"),
                    "cost_authority_sha256": file_sha(root / c["cost_authority_path"]), "cost_ssot_sha256": file_sha(root / c["cost_ssot_path"]),
                    "outcomes_computed": False, "fresh_credit": 0, **AUTH})
    write_once(manifest_path, receipt)
    return receipt


def verify_dataset(output, c):
    m = json.loads((output / "development_manifest.json").read_text())
    if m["receipt_sha256"] != sha({k:v for k,v in m.items() if k != "receipt_sha256"}) or m["contract_sha256"] != c["receipt_sha256"]:
        raise RuntimeError("IMMUTABLE_MANIFEST_DRIFT")
    if sha(m["dataset_files"]) != m["dataset_sha256"]:
        raise RuntimeError("DATASET_SHA_DRIFT")
    if m["collection_finished_ms"] <= c["frozen_at_ms"] or c["historical_cutoff_close_ms"] > c["prospective_boundary_ms"] or any(p["received_ms"] <= c["frozen_at_ms"] for stream in m["sources"].values() for p in stream["pages"]):
        raise RuntimeError("DATA_OR_SPLIT_NOT_FROZEN_BEFORE_COLLECTION")
    for p, h in m["dataset_files"].items():
        if file_sha(output / p) != h:
            raise RuntimeError("DATASET_FILE_DRIFT")
        validate_history(json.loads((output / p).read_text()), c["historical_cutoff_close_ms"])
    for row in m["cost_snapshots"].values():
        if file_sha(output / row["path"]) != row["sha256"]:
            raise RuntimeError("COST_SNAPSHOT_DRIFT")
    for p,h in m["raw_dataset_files"].items():
        if file_sha(output / p) != h:
            raise RuntimeError("RAW_ARCHIVE_DRIFT")
    if freeze_split(m["raw_symbols"], c) != m["splits"] or m["outcomes_computed"] is not False:
        raise RuntimeError("SPLIT_FREEZE_DRIFT")
    return m


def append_native_epoch(output, epoch, records):
    results = []
    for record in records:
        raw = record["raw_payload"]
        if sha(raw) != record["source_payload_sha256"] or record["prospective_only"] is not True:
            raise RuntimeError("NATIVE_PAYLOAD_LINEAGE")
        if not 0 < record["source_timestamp_ms"] <= record["collected_at_ms"] or record["collected_at_ms"] <= epoch["boundary_ms"]:
            raise RuntimeError("NATIVE_EPOCH_CLOCK")
        key = record["feature"] + "__" + record["symbol"].replace("-", "")
        path = output / (key + ".jsonl"); path.parent.mkdir(parents=True, exist_ok=True)
        prior = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
        for i, old in enumerate(prior):
            if old.get("epoch_id") != epoch["epoch_id"] or old.get("prospective_only") is not True or native.canonical_sha(old.get("raw_payload")) != old.get("source_payload_sha256"):
                raise RuntimeError("OLD_NATIVE_ROW_NOT_CLEAN_EPOCH")
            if not 0 < old["source_timestamp_ms"] <= old["collected_at_ms"] or old["collected_at_ms"] <= epoch["boundary_ms"] or (i and old["collected_at_ms"] <= prior[i-1]["collected_at_ms"]):
                raise RuntimeError("OLD_NATIVE_EPOCH_CLOCK")
        ident = (record["source_timestamp_ms"], record["source_payload_sha256"])
        seen = {(x["source_timestamp_ms"], x["source_payload_sha256"]) for x in prior}
        if len(seen) != len(prior):
            raise RuntimeError("NATIVE_EXISTING_DUPLICATE")
        if ident in seen:
            results.append({"stream": key, "rows": len(prior), "added": 0, "sha256": file_sha(path)}); continue
        if prior and record["collected_at_ms"] <= prior[-1]["collected_at_ms"]:
            raise RuntimeError("NATIVE_COLLECTED_NOT_STRICT_MONOTONIC")
        row = {**record, "epoch_id": epoch["epoch_id"], "formal_credit": 0, "funding_role": "STATE_SNAPSHOT_NOT_SETTLEMENT" if record["feature"] == "premium_index" else None}
        with path.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        results.append({"stream": key, "rows": len(prior) + 1, "added": 1, "sha256": file_sha(path)})
    return seal({"schema_version": "zel.p3.clean_native_epoch_receipt.v1", "epoch_id": epoch["epoch_id"], "boundary_ms": epoch["boundary_ms"],
                 "streams": results, "clean_native_rows": sum(r["rows"] for r in results), "legacy_rows_role": "AUDIT_ONLY",
                 "basis_binding": "SAME_PREMIUM_PAYLOAD_MARK_INDEX_TIMESTAMP", "funding_settlement_lineage_bound": False,
                 "candidate_generation_allowed": False, "paid_AI_calls": 0, **AUTH})


def collect_native(output, root=ROOT):
    records = []
    for feature in native.ENDPOINTS:
        for symbol in native.SYMBOLS:
            raw, base, latency = native.get_json(native.ENDPOINTS[feature], {"symbol": symbol})
            records.append({**native.make_record(feature, symbol, raw, base, latency, runner.now_ms()), "raw_payload": raw})
    result = append_native_epoch(output, read(EPOCH, root), records)
    (output / "latest.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument("--output", type=Path, required=True); p.add_argument("--native-only", action="store_true"); a = p.parse_args()
    if not a.native_only:
        result = acquire(ROOT, a.output)
        print(json.dumps({"dataset_sha256": result["dataset_sha256"], "symbols": result["symbols"]}))
    print(json.dumps(collect_native(a.output / "native_epoch")))


if __name__ == "__main__":
    main()
