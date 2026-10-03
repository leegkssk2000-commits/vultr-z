"""Offline metadata inspection and an explicitly supplied SYNTHETIC_ONLY caller.

No market/state/trade body is opened by inspection. Export hashes must be pinned
by the caller through its authenticated operator path; hashes alone do not prove
origin. Metadata PASS never certifies unused data or authorizes market execution.
Synthetic bundle hashes are bound in the existing checkpoint, not a side ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

_SPEC = importlib.util.spec_from_file_location("kp30_binding_adapter", Path(__file__).with_name("adapter.py"))
assert _SPEC and _SPEC.loader
adapter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(adapter)

EXPORT_SCHEMA = "kp30.metadata_export.v1"
SYNTHETIC_SCHEMA = "kp30.serialized_synthetic_input.v1"
PINS = {"candidate": adapter.CANDIDATE, "parent_identity": adapter.PARENT_IDENTITY,
        "parent_module_sha256": adapter.PARENT_MODULE_SHA}
FACETS = ("ledger", "reservations", "locks", "processes", "state")
INHERITED_ACCESS_SHA = "fa8f9bc8a97f04c17ad67b275a7337f3a97128fed052a2879fbab0e30ea24746"
SCHEMAS = {"census": "kp30.candidate_census_metadata.v1",
           "usage": "kp30.usage_inventory_metadata.v1",
           "index": "kp30.source_index_metadata.v1",
           "source": "kp30.source_clock_metadata.v1"}


def _exact(item: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(item, dict) or set(item) != keys:
        raise adapter.PrepError("UNSUPPORTED_METADATA_FIELDS:" + label)
    return item


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise adapter.PrepError("INVALID_HASH:" + label)
    return value


def _inherited_seen() -> tuple[list[dict[str, Any]], set[str]]:
    """Preserve pinned known history without opening any of its source refs."""
    path = Path(__file__).with_name("ACCESS_INVENTORY.json")
    if path.is_symlink():
        raise adapter.PrepError("INHERITED_INVENTORY_SYMLINK_FORBIDDEN")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INHERITED_ACCESS_SHA:
        raise adapter.PrepError("INHERITED_ACCESS_INVENTORY_DRIFT")
    doc = _json(raw)
    if doc.get("schema") != "zel.kp30.validation_prep.access_inventory.v1" or doc.get("candidate") != adapter.CANDIDATE:
        raise adapter.PrepError("INHERITED_ACCESS_INVENTORY_PIN_MISMATCH")
    seen, identities = [], set()
    for old in doc["seen_and_availability_inventory"]:
        if old["id"] == "ORIGINAL_SEEN_DEVELOPMENT_HISTORY":
            seen.append({"source_id": "*", "start_ms": old["start_ms"], "end_exclusive_ms": old["end_exclusive_ms"]})
        if old["id"] == "VERIFIED_SOURCE_AND_FORWARD_ALREADY_OBSERVED":
            end = int(datetime.fromisoformat(old["last_saved_observation_utc"]).timestamp() * 1000) + 1
            seen.append({"source_id": "*", "start_ms": old["source_start_ms"], "end_exclusive_ms": end})
        for key in ("identity_sha256", "source_identity_sha256"):
            if old.get(key):
                identities.add(_sha(old[key], "inherited_source_identity"))
    return seen, identities


def _pins(item: Mapping[str, Any]) -> None:
    if any(item.get(key) != value for key, value in PINS.items()):
        raise adapter.PrepError("CANDIDATE_OR_PARENT_PIN_MISMATCH")


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(items: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise adapter.PrepError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs,
                        parse_constant=lambda value: (_ for _ in ()).throw(adapter.PrepError("NONFINITE_JSON:" + value)))
    if not isinstance(result, dict):
        raise adapter.PrepError("JSON_OBJECT_REQUIRED")
    return result


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise adapter.PrepError("METADATA_RELATIVE_PATH_REQUIRED")
    rel = Path(relative)
    if (any(part in (".", "..", "") for part in relative.split("/")) or rel.is_absolute() or not rel.parts
            or any(part in (".", "..") for part in rel.parts)
            or not relative.endswith(".metadata.json")):
        raise adapter.PrepError("METADATA_RELATIVE_PATH_REQUIRED")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise adapter.PrepError("METADATA_SYMLINK_FORBIDDEN")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise adapter.PrepError("METADATA_RECEIPT_MISSING_OR_OUTSIDE_ROOT")
    return path


def _receipt(root: Path, ref: Any, kind: str, opened: list[str]) -> dict[str, Any]:
    _exact(ref, {"path", "sha256"}, "receipt_reference")
    expected = _sha(ref["sha256"], "receipt")
    path = _safe_path(root, ref["path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise adapter.PrepError("METADATA_RECEIPT_HASH_MISMATCH:" + ref["path"])
    doc = _json(raw)
    if doc.get("schema") != SCHEMAS.get(kind, "kp30." + kind + "_metadata.v1"):
        raise adapter.PrepError("UNSUPPORTED_METADATA_SCHEMA:" + kind)
    _pins(doc)
    opened.append(ref["path"])
    return doc


def inspect_metadata_export(export_path: Path | None, *, expected_export_sha256: str | None,
                            pin_origin: str | None, now_ms: int | None = None) -> dict[str, Any]:
    """Inspect one externally pinned metadata export; always returns blocked.

    expected_export_sha256 and pin_origin must be supplied out of band. This
    function verifies bytes and references, not the caller's authentication.
    No source body hash is verified, and no receipt grants fresh/OOS credit.
    """
    now = adapter._time(int(time.time() * 1000) if now_ms is None else now_ms, "query_time")
    result: dict[str, Any] = {"schema": "kp30.metadata_binding_report.v1", **PINS,
        "execution_ready": False, "new_full_credit": 0, "g5b_activated": False,
        "query_time_ms": now, "source_bodies_opened": False, "state_trade_bodies_opened": False,
        "unused_status": "METADATA_ONLY_NOT_CERTIFIED", "currentness_certified": False,
        "metadata_receipts_opened": [], "source_inspections": [], "metadata_binding_pass": False,
        "blockers": [
            {"category": "DATA", "code": "REAL_BODY_UNUSED_AND_COST_FUNDING_NOT_CERTIFIED"},
            {"category": "IMPLEMENTATION", "code": "NO_MARKET_RUNNER_IN_PREPARATION"},
            {"category": "APPROVAL", "code": "NEW_PROTOCOL_AND_MARKET_EXECUTION_UNAPPROVED"}]}
    def blocked(category: str, code: str) -> None:
        result["blockers"].append({"category": category, "code": code})
    if export_path is None:
        blocked("CONNECTION", "CURRENT_OPERATOR_METADATA_EXPORT_NOT_SUPPLIED")
        return result
    try:
        if not pin_origin or not isinstance(pin_origin, str):
            raise adapter.PrepError("OUT_OF_BAND_PIN_ORIGIN_REQUIRED")
        expected = _sha(expected_export_sha256, "operator_export_pin")
        supplied = Path(export_path).absolute()
        # Reject a symlink anywhere in the supplied root/file chain.
        for part in (supplied, *supplied.parents):
            if part.is_symlink():
                raise adapter.PrepError("METADATA_SYMLINK_FORBIDDEN")
        root = supplied.parent.resolve()
        path = _safe_path(root, supplied.name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise adapter.PrepError("OPERATOR_EXPORT_HASH_MISMATCH")
        export = _json(raw)
        _exact(export, {"schema", *PINS, "census", "usage", "index"}, "export")
        if export["schema"] != EXPORT_SCHEMA:
            raise adapter.PrepError("UNSUPPORTED_METADATA_SCHEMA:export")
        _pins(export)
        result.update({"export_sha256": expected, "pin_origin": pin_origin,
                       "pin_origin_authentication_verified_here": False})
        inherited_seen, inherited_identities = _inherited_seen()
        result["inherited_access_sha256"] = INHERITED_ACCESS_SHA
        result["inherited_seen_intervals"] = inherited_seen
        result["inherited_observed_source_identities"] = sorted(inherited_identities)
        result["post_witness_usage_history_certified_here"] = False
        opened = result["metadata_receipts_opened"]
        census = _receipt(root, export["census"], "census", opened)
        _exact(census, {"schema", *PINS, "collected_at_ms", *FACETS}, "census")
        collected = adapter._time(census["collected_at_ms"], "census_collected")
        if collected > now:
            raise adapter.PrepError("CENSUS_TIMESTAMP_AFTER_QUERY")
        result.update({"census_collected_at_ms": collected, "census_age_ms": now - collected})
        statuses = {"ledger": {"NOT_RUN", "STARTED", "INTERRUPTED", "FAILED", "COMPLETE"},
                    "reservations": {"ACTIVE", "RELEASED", "NONE"},
                    "locks": {"LOCKED", "UNLOCKED", "NONE"},
                    "processes": {"RUNNING", "STOPPED", "NONE"},
                    "state": {"PRESENT", "ABSENT", "STARTED", "INTERRUPTED", "FAILED"}}
        for facet in FACETS:
            doc = _receipt(root, census[facet], facet, opened)
            _exact(doc, {"schema", *PINS, "collected_at_ms", "complete", "records"}, facet)
            if doc["complete"] is not True or adapter._time(doc["collected_at_ms"], "facet_collected") != collected:
                raise adapter.PrepError("CENSUS_INCOMPLETE_OR_COLLECTION_MISMATCH:" + facet)
            if not isinstance(doc["records"], list):
                raise adapter.PrepError("CENSUS_RECORD_LIST_REQUIRED")
            for row in doc["records"]:
                _exact(row, {"identity", "status"}, facet + "_record")
                if not isinstance(row["identity"], str) or not row["identity"] or row["status"] not in statuses[facet]:
                    raise adapter.PrepError("UNSUPPORTED_CENSUS_RECORD")
                if row["status"] in ("ACTIVE", "LOCKED", "RUNNING", "STARTED"):
                    blocked("CONNECTION", "CURRENT_CANDIDATE_CONFLICT:" + facet + ":" + row["identity"])
        usage = _receipt(root, export["usage"], "usage", opened)
        _exact(usage, {"schema", *PINS, "complete", "seen"}, "usage")
        if not isinstance(usage["seen"], list):
            raise adapter.PrepError("SEEN_INDEX_LIST_REQUIRED")
        for old in usage["seen"]:
            _exact(old, {"source_id", "body_sha256", "start_ms", "end_exclusive_ms"}, "seen")
            _sha(old["body_sha256"], "seen_body")
            if not isinstance(old["source_id"], str) or not old["source_id"]:
                raise adapter.PrepError("SEEN_SOURCE_ID_REQUIRED")
            if adapter._time(old["end_exclusive_ms"], "seen_end") <= adapter._time(old["start_ms"], "seen_start"):
                raise adapter.PrepError("SEEN_INTERVAL_INVALID")
        if type(usage["complete"]) is not bool:
            raise adapter.PrepError("USAGE_COMPLETENESS_BOOLEAN_REQUIRED")
        index = _receipt(root, export["index"], "index", opened)
        _exact(index, {"schema", *PINS, "sources"}, "index")
        if not isinstance(index["sources"], list) or not index["sources"]:
            raise adapter.PrepError("SOURCE_INDEX_EMPTY")
        source_ids, source_refs = set(), set()
        for item in index["sources"]:
            identity_keys = {"source_identity_sha256"} if "source_identity_sha256" in item else set()
            _exact(item, {"source_id", "body_sha256", "received_at_ms", "start_ms", "end_exclusive_ms",
                          "usage_inventory_sha256", "usage_inventory_complete", "receipt", *identity_keys}, "source_index")
            _sha(item["body_sha256"], "source_body")
            if not isinstance(item["source_id"], str) or not item["source_id"] or item["source_id"] in source_ids:
                raise adapter.PrepError("SOURCE_ID_EMPTY_OR_DUPLICATE")
            source_ids.add(item["source_id"])
            if type(item["usage_inventory_complete"]) is not bool:
                raise adapter.PrepError("SOURCE_USAGE_COMPLETENESS_BOOLEAN_REQUIRED")
            ref_key = item["receipt"].get("path") if isinstance(item["receipt"], dict) else None
            if ref_key in source_refs:
                raise adapter.PrepError("DUPLICATE_SOURCE_METADATA_REFERENCE")
            source_refs.add(ref_key)
            if item["usage_inventory_sha256"] != export["usage"]["sha256"] or item["usage_inventory_complete"] is not usage["complete"]:
                raise adapter.PrepError("USAGE_INVENTORY_HASH_OR_COMPLETENESS_MISMATCH")
            source = _receipt(root, item["receipt"], "source", opened)
            _exact(source, {"schema", *PINS, "source_id", "body_sha256", "received_at_ms", "start_ms",
                            "end_exclusive_ms", "source_ts_ms", "usable_at_ms", "processed_at_ms", *identity_keys}, "source_receipt")
            if identity_keys:
                identity = _sha(item["source_identity_sha256"], "source_identity")
                if source["source_identity_sha256"] != identity:
                    raise adapter.PrepError("SOURCE_IDENTITY_RECEIPT_BINDING_MISMATCH")
                if identity in inherited_identities:
                    blocked("DATA", "INHERITED_SOURCE_IDENTITY_ALREADY_OBSERVED:" + item["source_id"])
            for key in ("source_id", "body_sha256", "received_at_ms", "start_ms", "end_exclusive_ms"):
                if item[key] != source[key]:
                    raise adapter.PrepError("SOURCE_CLOCK_RECEIPT_BINDING_MISMATCH:" + key)
            received = adapter._time(source["received_at_ms"], "received")
            usable = adapter._time(source["usable_at_ms"], "usable")
            processed = adapter._time(source["processed_at_ms"], "processed")
            if not received <= usable <= processed <= collected:
                raise adapter.PrepError("SOURCE_CLOCK_ORDER_INVALID")
            if source["source_ts_ms"] is not None and adapter._time(source["source_ts_ms"], "native") > usable:
                raise adapter.PrepError("SOURCE_NATIVE_CLOCK_AFTER_USABLE")
            if source["source_ts_ms"] is None:
                blocked("DATA", "SOURCE_NATIVE_CLOCK_UNAVAILABLE:" + item["source_id"])
            inspection = adapter.inspect_source_index(item, [*usage["seen"], *inherited_seen])
            result["source_inspections"].append({"source_id": item["source_id"], **inspection})
            for reason in inspection["reasons"]:
                blocked("DATA", reason + ":" + item["source_id"])
        result["metadata_binding_pass"] = len(result["blockers"]) == 3
    except (adapter.PrepError, OSError, ValueError, TypeError, KeyError) as exc:
        blocked("CONNECTION" if isinstance(exc, OSError) else "DATA", str(exc))
    return result


def run_supplied_synthetic(bundle_path: Path, *, expected_input_sha256: str, output_root: Path,
                           recover: bool = False) -> dict[str, Any]:
    """Call the real preparation adapter only for a caller-pinned synthetic file.

    Bundle keys: schema,input_kind,candidate,config,events,cashflow_inputs.
    Frames serialize as {"30": {"BTC-USDT": [bar objects]}}. Config contains only
    t0_ms,window_end_ms,runtime_identity,reference_costs_bps; output is isolated.
    Cashflow inputs are keyed by the supplied signal opportunity_key. Recover
    never changes the original bundle hash or consumes another FULL credit.
    """
    raw = Path(bundle_path).read_bytes()
    expected = _sha(expected_input_sha256, "synthetic_input")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise adapter.PrepError("SYNTHETIC_INPUT_HASH_MISMATCH")
    bundle = _json(raw)
    if bundle.get("schema") != SYNTHETIC_SCHEMA or bundle.get("input_kind") != "SYNTHETIC_ONLY":
        raise adapter.PrepError("SERIALIZED_SYNTHETIC_ONLY_REQUIRED")
    _exact(bundle, {"schema", "input_kind", "candidate", "config", "events", "cashflow_inputs"}, "synthetic_bundle")
    if bundle["candidate"] != adapter.CANDIDATE:
        raise adapter.PrepError("KP_EXACT_CANDIDATE_REQUIRED")
    _exact(bundle["config"], {"t0_ms", "window_end_ms", "runtime_identity", "reference_costs_bps"}, "synthetic_config")
    if not isinstance(bundle["events"], list) or not isinstance(bundle["cashflow_inputs"], dict):
        raise adapter.PrepError("SYNTHETIC_EVENTS_AND_CASHFLOWS_REQUIRED")
    for args in bundle["cashflow_inputs"].values():
        if not isinstance(args, dict) or set(args) - {"original_qty", "quantity_lineage", "pit_costs", "funding", "funding_coverage"}:
            raise adapter.PrepError("UNSUPPORTED_CASHFLOW_INPUTS")
    events = []
    prior = -1
    seen = set()
    for event in bundle["events"]:
        _exact(event, {"event_id", "now_ms", "quotes", "frames", "wrapper"}, "synthetic_event")
        stamp = adapter._time(event["now_ms"], "event_time")
        if stamp < prior or not isinstance(event["event_id"], str) or not event["event_id"] or event["event_id"] in seen:
            raise adapter.PrepError("SYNTHETIC_EVENT_ORDER_OR_DUPLICATE_ID")
        prior = stamp
        seen.add(event["event_id"])
        frames: dict[int, Any] = {}
        if not isinstance(event["frames"], dict):
            raise adapter.PrepError("SERIALIZED_FRAME_MAP_REQUIRED")
        for tf, symbols in event["frames"].items():
            if tf != "30" or not isinstance(symbols, dict):
                raise adapter.PrepError("KP30_SERIALIZED_FRAME_REQUIRED")
            frames[30] = {}
            for symbol, records in symbols.items():
                if symbol not in adapter.SYMBOLS or not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                    raise adapter.PrepError("SERIALIZED_FRAME_RECORDS_REQUIRED")
                frames[30][symbol] = pd.DataFrame(records)
        events.append({**event, "frames": frames})
    cfg = adapter.build_candidate_config(output_root, **bundle["config"])
    cfg["synthetic_input_sha256"] = expected  # config_sha256 is durable in STATE.
    with adapter.PrepCheckpoint(cfg, recover=recover) as cp:
        old = cp.state.get("serialized_input_sha256")
        if old is not None and old != expected:
            raise adapter.PrepError("CHECKPOINT_SERIALIZED_INPUT_DRIFT")
        if old is None:
            cp.state["serialized_input_sha256"] = expected
            cp.save()
        for event in events:
            cp.apply_synthetic(**event)
        rows = [*cp.state["paper_state"]["trades"], *cp.state["paper_state"]["positions"].values()]
        cashflows = []
        for row in rows:
            args = bundle["cashflow_inputs"].get(row["key"], {})
            unknown = set(args) - {"original_qty", "quantity_lineage", "pit_costs", "funding", "funding_coverage"}
            if unknown:
                raise adapter.PrepError("UNSUPPORTED_CASHFLOW_INPUTS")
            cashflows.append(adapter.link_cashflows(row, original_qty=args.get("original_qty"),
                quantity_lineage=args.get("quantity_lineage"), pit_costs=args.get("pit_costs", {}),
                funding=args.get("funding"), funding_coverage=args.get("funding_coverage")))
        report = {"schema": "kp30.supplied_synthetic_report.v1", "input_sha256": expected,
                  **cp.snapshot(), "cashflow_projections": cashflows,
                  "blockers": sorted({code for row in cashflows for code in row["blockers"]}),
                  "report_kind": "SYNTHETIC_PREPARATION_ONLY", "pending_and_open_preserved": True}
        adapter.atomic_json(cp.out / "SUPPLIED_SYNTHETIC_REPORT.json", report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--export", type=Path)
    inspect.add_argument("--expected-export-sha256")
    inspect.add_argument("--pin-origin")
    run = commands.add_parser("synthetic")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--expected-input-sha256", required=True)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            report = inspect_metadata_export(args.export, expected_export_sha256=args.expected_export_sha256,
                                             pin_origin=args.pin_origin)
        else:
            report = run_supplied_synthetic(args.input, expected_input_sha256=args.expected_input_sha256,
                                           output_root=args.output_root, recover=args.recover)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0  # inspection is a report, never a permission gate.
    except (adapter.PrepError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"execution_ready": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
