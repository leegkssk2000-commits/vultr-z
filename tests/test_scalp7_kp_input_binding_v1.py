"""Offline metadata receipts plus supplied-file synthetic integration, no market replay."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "research/campaigns/scalp7_20261003/kp_validation_prep_v1/input_binding.py"


def module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


binding = module("kp30_input_binding_test", PATH)
fixtures = module("kp30_input_binding_existing_fixtures", ROOT / "tests/test_scalp7_kp_validation_prep_v1.py")
prep = binding.adapter
BASE = fixtures.BASE
TF = fixtures.TF
SYMBOL = fixtures.SYMBOL


def write(path: Path, doc: Any) -> dict[str, str]:
    path.write_text(json.dumps(doc, sort_keys=True, allow_nan=False))
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def metadata(tmp_path: Path, *, conflict: bool = False, seen: bool = False,
             complete: bool = True) -> tuple[Path, str]:
    pins = binding.PINS
    collected = BASE + 1000
    census = {"schema": binding.SCHEMAS["census"], **pins, "collected_at_ms": collected}
    for facet in binding.FACETS:
        records = [{"identity": "KP30_PREP_CURRENT", "status": "RUNNING"}] if facet == "processes" and conflict else []
        census[facet] = write(tmp_path / (facet + ".metadata.json"), {
            "schema": "kp30." + facet + "_metadata.v1", **pins,
            "collected_at_ms": collected, "complete": True, "records": records})
    census_ref = write(tmp_path / "census.metadata.json", census)
    old = [{"source_id": "*", "body_sha256": "9"*64, "start_ms": BASE-TF,
            "end_exclusive_ms": BASE+1}] if seen else []
    usage_ref = write(tmp_path / "usage.metadata.json", {"schema": binding.SCHEMAS["usage"],
        **pins, "complete": complete, "seen": old})
    source = {"schema": binding.SCHEMAS["source"], **pins, "source_id": "operator-indexed-btc",
        "body_sha256": "a"*64, "received_at_ms": BASE+100, "start_ms": BASE,
        "end_exclusive_ms": BASE+TF, "source_ts_ms": BASE+90,
        "usable_at_ms": BASE+100, "processed_at_ms": BASE+101}
    source_ref = write(tmp_path / "source-clock.metadata.json", source)
    item = {key: source[key] for key in ("source_id", "body_sha256", "received_at_ms", "start_ms", "end_exclusive_ms")}
    item.update({"usage_inventory_sha256": usage_ref["sha256"],
                 "usage_inventory_complete": complete, "receipt": source_ref})
    index_ref = write(tmp_path / "index.metadata.json", {"schema": binding.SCHEMAS["index"], **pins, "sources": [item]})
    path = tmp_path / "export.metadata.json"
    ref = write(path, {"schema": binding.EXPORT_SCHEMA, **pins, "census": census_ref,
                       "usage": usage_ref, "index": index_ref})
    return path, ref["sha256"]


def inspect(path: Path, sha: str) -> dict[str, Any]:
    return binding.inspect_metadata_export(path, expected_export_sha256=sha,
        pin_origin="authenticated-operator-export:caller-pin", now_ms=BASE+1100)


def synthetic(tmp_path: Path, *, terminal: bool = True, costs: bool = True) -> tuple[Path, str]:
    bars = {"30": {SYMBOL: fixtures.frames()[30][SYMBOL].to_dict("records")}}
    event = lambda name, stamp, quotes, wrapper=None: {"event_id": name, "now_ms": stamp,
        "quotes": quotes, "frames": copy.deepcopy(bars), "wrapper": wrapper}
    events = [event("admit", BASE+101, {}, fixtures.wrapper()),
              event("entry", BASE+110, fixtures.quotes(BASE+110))]
    if terminal:
        events += [event("partial-trigger", BASE+120, fixtures.quotes(BASE+120, 110, 111)),
                   event("partial-fill", BASE+130, fixtures.quotes(BASE+130, 111, 112)),
                   event("stop-trigger", BASE+140, fixtures.quotes(BASE+140, 94, 95)),
                   event("exit-fill", BASE+150, fixtures.quotes(BASE+150, 93, 94))]
    cashflow = {"original_qty": 2.0, "quantity_lineage": {"original_qty": 2.0,
        "known_at_ms": BASE, "kind": "PAPER_ORIGINAL_QUANTITY_MODEL", "body_sha256": "1"*64},
        "pit_costs": fixtures.costs(), "funding": [fixtures.funding(BASE+131)],
        "funding_coverage": {"complete": True, "start_ms": BASE+110,
                             "end_ms": BASE+150, "body_sha256": "2"*64}}
    path = tmp_path / "synthetic.json"
    ref = write(path, {"schema": binding.SYNTHETIC_SCHEMA, "input_kind": "SYNTHETIC_ONLY",
        "candidate": prep.CANDIDATE,
        "config": {"t0_ms": BASE, "window_end_ms": BASE+2*TF,
                   "runtime_identity": "KP30_PREP_SYNTHETIC_FILE_CALLER_V1", "reference_costs_bps": {SYMBOL: 8.0}},
        "events": events, "cashflow_inputs": {"synthetic-signal-one": cashflow} if costs else {}})
    return path, ref["sha256"]


def run(path: Path, sha: str, tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    return binding.run_supplied_synthetic(path, expected_input_sha256=sha,
                                         output_root=tmp_path/prep.NAMESPACE, **kwargs)


def test_complete_metadata_only_opens_receipts_never_certifies_unused(tmp_path: Path, monkeypatch: Any) -> None:
    path, sha = metadata(tmp_path)
    forbidden = tmp_path / "market.jsonl"
    forbidden.write_text('actual market body must not be opened')
    state = tmp_path / "STATE.json"
    state.write_text('actual state/trade body must not be opened')
    opened = []
    original = Path.read_bytes
    def safe_read(item: Path) -> bytes:
        assert item not in (forbidden, state)
        opened.append(item.name)
        return original(item)
    monkeypatch.setattr(Path, "read_bytes", safe_read)
    report = inspect(path, sha)
    assert report["metadata_binding_pass"]
    assert report["census_age_ms"] == 100
    assert len(opened) == 11
    assert "ACCESS_INVENTORY.json" in opened
    assert report["unused_status"] == "METADATA_ONLY_NOT_CERTIFIED"
    assert not report["currentness_certified"] and not report["execution_ready"]
    assert not report["pin_origin_authentication_verified_here"]
    assert not report["source_bodies_opened"] and not report["state_trade_bodies_opened"]
    assert not report["source_inspections"][0]["genuine_fresh"]
    assert {b["category"] for b in report["blockers"]} == {"DATA", "IMPLEMENTATION", "APPROVAL"}


@pytest.mark.parametrize("conflict,seen,complete,code", [
    (True, False, True, "CURRENT_CANDIDATE_CONFLICT:processes"),
    (False, True, True, "SEEN_BODY_OR_INTERVAL"),
    (False, False, False, "USAGE_INVENTORY_INCOMPLETE")])
def test_current_census_conflict_and_seen_or_incomplete_inventory_block(
    tmp_path: Path, conflict: bool, seen: bool, complete: bool, code: str,
) -> None:
    path, sha = metadata(tmp_path, conflict=conflict, seen=seen, complete=complete)
    report = inspect(path, sha)
    assert not report["metadata_binding_pass"]
    assert any(code in b["code"] for b in report["blockers"])
    assert not report["execution_ready"]


@pytest.mark.parametrize("change", ["export", "receipt", "parent", "schema", "path", "symlink", "body_key", "future"])
def test_metadata_mutation_schema_candidate_and_unsafe_paths_block(tmp_path: Path, change: str) -> None:
    path, sha = metadata(tmp_path)
    doc = json.loads(path.read_bytes())
    if change == "export":
        path.write_text(path.read_text() + " ")
    elif change == "receipt":
        (tmp_path/"ledger.metadata.json").write_text('{}')
    else:
        if change == "parent":
            doc["candidate"] = "OTHER_LANE"
        elif change == "schema":
            doc["schema"] = "kp30.metadata_export.v2"
        elif change == "path":
            doc["usage"]["path"] = "../usage.metadata.json"
        elif change == "symlink":
            target = tmp_path/"usage.metadata.json"
            target.rename(tmp_path/"actual.metadata.json")
            target.symlink_to(tmp_path/"actual.metadata.json")
        elif change == "body_key":
            doc["market_body_path"] = "market.jsonl"
        elif change == "future":
            census = json.loads((tmp_path/"census.metadata.json").read_bytes())
            census["collected_at_ms"] = BASE + 1200
            doc["census"] = write(tmp_path/"census.metadata.json", census)
        sha = write(path, doc)["sha256"]
    report = inspect(path, sha)
    assert not report["metadata_binding_pass"]
    assert not report["execution_ready"]
    assert len(report["blockers"]) > 3


def test_absent_export_and_unpinned_export_are_concrete_connection_blocks(tmp_path: Path) -> None:
    report = binding.inspect_metadata_export(None, expected_export_sha256=None, pin_origin=None, now_ms=BASE)
    assert any(b["category"] == "CONNECTION" for b in report["blockers"])
    path, sha = metadata(tmp_path)
    report = binding.inspect_metadata_export(path, expected_export_sha256=sha, pin_origin=None)
    assert any("PIN_ORIGIN" in b["code"] for b in report["blockers"])
    assert report["metadata_receipts_opened"] == []


def test_cli_inspect_reports_blocked_without_receipts(tmp_path: Path) -> None:
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("PYTHONPATH", "PYTHONHOME")}
    for cwd in (ROOT, tmp_path):
        process = subprocess.run([sys.executable, str(PATH), "inspect"], cwd=cwd,
                                 env=environment, check=True, capture_output=True, text=True)
        report = json.loads(process.stdout)
        assert not report["execution_ready"] and report["new_full_credit"] == 0
        assert any(b["category"] == "CONNECTION" for b in report["blockers"])


def test_serialized_synthetic_pipeline_partial_exit_cashflow_and_single_artifact(tmp_path: Path) -> None:
    path, sha = synthetic(tmp_path)
    report = run(path, sha, tmp_path)
    assert report["closed_synthetic_trades"] == 1 and report["open_positions"] == 0
    assert report["consumed_full_credit"] == 0 and not report["execution_ready"]
    projection = report["cashflow_projections"][0]
    assert [e["event_qty"] for e in projection["cashflows"]] == pytest.approx([2.0, 0.2, 1.8])
    assert projection["gross_original_notional_bps"] == pytest.approx(-520)
    assert projection["signed_funding_debit_bps"] == pytest.approx(9)
    assert projection["net_pnl_r"] == pytest.approx(projection["net_original_notional_bps"] / 500)
    assert not projection["terminal_eligible"] and not report["blockers"]
    out = tmp_path/prep.NAMESPACE
    assert json.loads((out/"SUPPLIED_SYNTHETIC_REPORT.json").read_bytes()) == report
    state = json.loads((out/"STATE.json").read_bytes())
    assert state["serialized_input_sha256"] == sha and state["attempt_count"] == 1


def test_missing_cost_and_funding_stays_null_and_open_is_preserved(tmp_path: Path) -> None:
    path, sha = synthetic(tmp_path, terminal=False, costs=False)
    report = run(path, sha, tmp_path)
    assert report["open_positions"] == 1 and report["closed_synthetic_trades"] == 0
    assert report["cashflow_projections"][0]["net_pnl_r"] is None
    assert "SIGNED_FUNDING_COMPLETE_INTERVAL_MISSING" in report["blockers"]
    assert "PIT_COST_LINEAGE_MISSING:ENTRY" in report["blockers"]


def test_interrupted_file_resume_uses_same_binding_and_never_duplicates(tmp_path: Path, monkeypatch: Any) -> None:
    path, sha = synthetic(tmp_path)
    original = prep.PrepCheckpoint.apply_synthetic
    def interrupted(cp: Any, event_id: str, **kwargs: Any) -> Any:
        if event_id == "partial-fill":
            raise KeyboardInterrupt("file caller interrupted")
        return original(cp, event_id, **kwargs)
    monkeypatch.setattr(prep.PrepCheckpoint, "apply_synthetic", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(path, sha, tmp_path)
    out = tmp_path/prep.NAMESPACE
    state = json.loads((out/"STATE.json").read_bytes())
    assert state["attempt_status"] == "INTERRUPTED"
    assert len(state["processed_events"]) == 3
    monkeypatch.undo()
    with pytest.raises(prep.PrepError, match="EXPLICIT_RECOVERY"):
        run(path, sha, tmp_path)
    report = run(path, sha, tmp_path, recover=True)
    assert report["closed_synthetic_trades"] == 1 and report["attempt_count"] == 1
    state = json.loads((out/"STATE.json").read_bytes())
    assert len(state["processed_events"]) == 6
    assert any(row["kind"] == "INTERRUPTED" for row in state["history"])
    before = state["paper_state"]
    assert run(path, sha, tmp_path, recover=True) == report
    assert json.loads((out/"STATE.json").read_bytes())["paper_state"] == before


def test_changed_synthetic_bundle_is_rejected_against_checkpoint_before_mutation(tmp_path: Path) -> None:
    path, sha = synthetic(tmp_path)
    run(path, sha, tmp_path)
    out = tmp_path/prep.NAMESPACE
    before = (out/"STATE.json").read_bytes()
    doc = json.loads(path.read_bytes())
    doc["cashflow_inputs"] = {}
    changed = write(path, doc)["sha256"]
    with pytest.raises(prep.PrepError, match="HASH_OR_CONFIGURATION_DRIFT"):
        run(path, changed, tmp_path, recover=True)
    assert (out/"STATE.json").read_bytes() == before
    with pytest.raises(prep.PrepError, match="INPUT_HASH_MISMATCH"):
        run(path, sha, tmp_path, recover=True)


def test_real_and_unsupported_synthetic_inputs_denied_before_checkpoint(tmp_path: Path) -> None:
    path, sha = synthetic(tmp_path)
    for kind in ("REAL", "REAL_SOURCE_RECEIPTS", "SYNTHETIC_PREPARATION_ONLY"):
        doc = json.loads(path.read_bytes())
        doc["input_kind"] = kind
        sha = write(path, doc)["sha256"]
        with pytest.raises(prep.PrepError, match="SYNTHETIC_ONLY"):
            run(path, sha, tmp_path)
        assert not (tmp_path/prep.NAMESPACE).exists()


def replace_index_source(path: Path, changes: dict[str, Any], *, receipt_changes: dict[str, Any] | None = None,
                         duplicate: bool = False) -> str:
    export = json.loads(path.read_bytes())
    index_path = path.parent/export["index"]["path"]
    index = json.loads(index_path.read_bytes())
    item = index["sources"][0]
    item.update(changes)
    source_path = path.parent/item["receipt"]["path"]
    source = json.loads(source_path.read_bytes())
    source.update(receipt_changes if receipt_changes is not None else {
        key: value for key, value in changes.items() if key in source or key == "source_identity_sha256"})
    item["receipt"] = write(source_path, source)
    if duplicate:
        index["sources"].append(copy.deepcopy(item))
    export["index"] = write(index_path, index)
    return write(path, export)["sha256"]


def test_empty_claimed_complete_inventory_cannot_erase_inherited_original_seen_history(tmp_path: Path) -> None:
    path, _ = metadata(tmp_path)
    sha = replace_index_source(path, {"start_ms": 1757894400000, "end_exclusive_ms": 1757894400000+TF})
    report = inspect(path, sha)
    assert not report["metadata_binding_pass"]
    assert any("SEEN_BODY_OR_INTERVAL" in b["code"] for b in report["blockers"])
    assert report["inherited_access_sha256"] == binding.INHERITED_ACCESS_SHA
    assert not report["post_witness_usage_history_certified_here"]


def test_known_observed_source_identity_is_preserved_without_claiming_identity_is_body_hash(tmp_path: Path) -> None:
    path, _ = metadata(tmp_path)
    identity = "a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9"
    sha = replace_index_source(path, {"source_identity_sha256": identity})
    report = inspect(path, sha)
    assert not report["metadata_binding_pass"]
    assert any("INHERITED_SOURCE_IDENTITY_ALREADY_OBSERVED" in b["code"] for b in report["blockers"])
    assert report["source_inspections"][0]["state"] == "NOT_PREVIOUSLY_INSPECTED_METADATA"


@pytest.mark.parametrize("changes,duplicate", [({"source_id": ""}, False),
    ({"body_sha256": "-"+"a"*63}, False), ({"usage_inventory_complete": 1}, False), ({}, True)])
def test_strict_source_id_hash_boolean_and_duplicate_contract(tmp_path: Path, changes: dict[str, Any], duplicate: bool) -> None:
    path, _ = metadata(tmp_path)
    sha = replace_index_source(path, changes, duplicate=duplicate)
    report = inspect(path, sha)
    assert not report["metadata_binding_pass"] and len(report["blockers"]) > 3


def test_malformed_cashflow_inputs_are_denied_before_checkpoint(tmp_path: Path) -> None:
    path, _ = synthetic(tmp_path)
    doc = json.loads(path.read_bytes())
    doc["cashflow_inputs"]["synthetic-signal-one"] = ["original_qty"]
    sha = write(path, doc)["sha256"]
    with pytest.raises(prep.PrepError, match="UNSUPPORTED_CASHFLOW"):
        run(path, sha, tmp_path)
    assert not (tmp_path/prep.NAMESPACE).exists()
