from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ops import issue1377_mr_batch_v1 as batch


def market() -> dict:
    start = batch.START_MS - batch.WARMUP_MS
    size = int((batch.END_MS - start) // rules_tf())
    t = np.arange(size)
    frames = {}
    for symbol in batch.rules.PARENT_SYMBOLS:
        values = np.full(size, 100.0)
        # One deterministic parent setup inside the development interval.
        at = int((batch.START_MS - start) // rules_tf()) + 20
        if symbol == "BTC-USDT":
            values[at - 1 : at + 12] = [104.0, 103.5, 103.2, 103.1, 104.0, 104.1, 104.0, 103.8, 103.6, 103.4, 103.2, 103.1, 103.0]
        ts = start + t * rules_tf()
        frame = pd.DataFrame({
            "open_ts_ms": ts,
            "close_ts_ms": ts + rules_tf(),
            "available_ts_ms": ts + rules_tf(),
            "segment_id": 0,
            "open": values,
            "high": values,
            "low": values,
            "close": values,
        })
        frame.attrs["source_inventory_sha256"] = batch.SOURCE_INVENTORY_SHA256
        frames[symbol] = frame
    return {"frames": frames, "costs": {symbol: 15.0 for symbol in batch.rules.PARENT_SYMBOLS}}


def rules_tf() -> int:
    return 30 * 60_000


def manifest() -> dict:
    return batch.build_manifest("a" * 40, batch.SOURCE_INVENTORY_SHA256)


def authority(m: dict) -> tuple[dict, dict]:
    common = {
        "issue": 1377,
        "reviewed_source_sha": m["reviewed_source_sha"],
        "manifest_sha256": m["manifest_sha256"],
        "protocol_sha256": m["protocol_sha256"],
        "source_inventory_sha256": batch.SOURCE_INVENTORY_SHA256,
        "rule_sha256": batch.RULE_SHA256,
        "cost_sha256": batch.COST_SHA256,
        "period_ms": [batch.START_MS, batch.END_MS],
        "instance_ids": list(batch.INSTANCE_IDS),
        "max_instances": 2,
        "order_authority": "BLOCKED",
    }
    approval = {**common, "schema": "zel.issue1377.mr_approval.v1", "state": "APPROVED_DEVELOPMENT_ONLY", "approval_ref": batch.APPROVAL_REF, "approval_commit_sha": "b" * 40}
    activation = {
        "github_run_id": "101",
        "github_run_attempt": "1",
        "github_job": "economic",
    }
    claim = {**common, "schema": "zel.issue1377.mr_claim.v1", "state": "RESERVED_NONRETRYABLE", "claim_ref": batch.CLAIM_REF, "claim_commit_sha": "c" * 40, "economic_instances": 2, "independent_approval_commit_sha": approval["approval_commit_sha"], "global_heavy_group": "a1-global-heavy-economic-evaluator-v1", "global_heavy_exclusive": True, "global_heavy_active_count": 1, "global_heavy_active_job": activation, "activation": activation}
    return approval, claim


def authority_api(m: dict):
    approval, claim = authority(m)
    approval_sha = approval.pop("approval_commit_sha")
    claim_sha = claim.pop("claim_commit_sha")
    approval_raw = json.dumps(approval).encode()
    claim_raw = json.dumps(claim).encode()
    approval_blob = hashlib.sha1(
        b"blob " + str(len(approval_raw)).encode() + b"\0" + approval_raw,
        usedforsecurity=False,
    ).hexdigest()
    claim_blob = hashlib.sha1(
        b"blob " + str(len(claim_raw)).encode() + b"\0" + claim_raw,
        usedforsecurity=False,
    ).hexdigest()
    routes = {
        "/git/ref/" + batch.APPROVAL_REF.removeprefix("refs/"): {
            "ref": batch.APPROVAL_REF,
            "object": {"type": "commit", "sha": approval_sha},
        },
        "/git/commits/" + approval_sha: {
            "tree": {"sha": "d" * 40},
            "parents": [{"sha": m["reviewed_source_sha"]}],
        },
        "/git/trees/" + "d" * 40: {
            "tree": [{"path": "APPROVED.json", "type": "blob", "sha": approval_blob}]
        },
        "/git/blobs/" + approval_blob: {
            "encoding": "base64",
            "content": base64.b64encode(approval_raw).decode(),
        },
        "/git/ref/" + batch.CLAIM_REF.removeprefix("refs/"): {
            "ref": batch.CLAIM_REF,
            "object": {"type": "commit", "sha": claim_sha},
        },
        "/git/commits/" + claim_sha: {
            "tree": {"sha": "e" * 40},
            "parents": [{"sha": approval_sha}],
        },
        "/git/trees/" + "e" * 40: {
            "tree": [{"path": "CLAIM.json", "type": "blob", "sha": claim_blob}]
        },
        "/git/blobs/" + claim_blob: {
            "encoding": "base64",
            "content": base64.b64encode(claim_raw).decode(),
        },
    }

    def api(method, route):
        assert method == "GET"
        return routes[route]

    return api, routes


def test_protocol_and_manifest_bind_fixed_period_cost_rule_and_two_instances() -> None:
    p = batch.protocol()
    m = manifest()
    assert p["period_ms"] == [batch.START_MS, batch.END_MS]
    assert m["warmup_start_ms"] == batch.START_MS - batch.WARMUP_MS
    assert m["instance_ids"] == ["N_PARENT", "N_CANDIDATE"]
    assert m["max_instances"] == 2
    assert m["classification"] == batch.CLASSIFICATION


def test_authority_rejects_rehashed_manifest_cost_period_or_instance_tamper() -> None:
    m = manifest()
    approval, claim = authority(m)
    batch.validate_authority(m, approval, claim)
    for key, value in (
        ("cost_sha256", "f" * 64),
        ("period_ms", [batch.START_MS + 1, batch.END_MS]),
        ("instance_ids", ["N_CANDIDATE"]),
    ):
        bad = copy.deepcopy(claim)
        bad[key] = value
        with pytest.raises(batch.Issue1377Error, match="CLAIM_BINDING"):
            batch.validate_authority(m, approval, bad)


def test_end_to_end_input_authority_model_save_audit_and_no_retry(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    api, _ = authority_api(m)
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    calls = []
    monkeypatch.setattr(
        batch,
        "atomic_consume_claim",
        lambda claim, supplied: calls.append(("consume", supplied["manifest_sha256"])),
    )
    def loader(source_root):
        assert calls == [("consume", m["manifest_sha256"])]
        calls.append(("market", source_root))
        return market()
    monkeypatch.setattr(batch, "load_market", loader)
    output = tmp_path / "RESULT.json"
    result = batch.execute(output, tmp_path, api=api)
    assert result["instances"]["N_PARENT"]["census"]["signals"] >= 1
    assert result["instances"]["N_CANDIDATE"]["census"]["signals"] >= 1
    assert calls[0][0] == "consume" and calls[1][0] == "market"
    assert batch.audit_result(output, m)["state"] == "PASS_SAVED_CENSUS_AND_ACCOUNTING"
    with pytest.raises(batch.Issue1377Error, match="RESULT_ALREADY_EXISTS_NO_RETRY"):
        batch.execute(output, tmp_path, api=api)


def test_saved_result_and_accounting_tamper_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    api, _ = authority_api(m)
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    monkeypatch.setattr(batch, "atomic_consume_claim", lambda claim, supplied: None)
    monkeypatch.setattr(batch, "load_market", lambda source_root: market())
    output = tmp_path / "RESULT.json"
    batch.execute(output, tmp_path, api=api)
    value = json.loads(output.read_text())
    value["instances"]["N_PARENT"]["cost_1x"]["T"] += 1
    value["result_sha256"] = batch.digest({k: v for k, v in value.items() if k != "result_sha256"})
    output.write_text(json.dumps(value))
    with pytest.raises(batch.Issue1377Error, match="SAVED_ACCOUNTING_MISMATCH"):
        batch.audit_result(output, m)


def test_rehashed_saved_result_missing_instance_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    api, _ = authority_api(m)
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    monkeypatch.setattr(batch, "atomic_consume_claim", lambda claim, supplied: None)
    monkeypatch.setattr(batch, "load_market", lambda source_root: market())
    output = tmp_path / "RESULT.json"
    batch.execute(output, tmp_path, api=api)
    value = json.loads(output.read_text())
    value["instances"].pop("N_PARENT")
    value["result_sha256"] = batch.digest(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(value))
    with pytest.raises(batch.Issue1377Error, match="SAVED_INSTANCE_SET_MISMATCH"):
        batch.audit_result(output, m)


def test_rehashed_saved_paired_and_full_census_tamper_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    api, _ = authority_api(m)
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    monkeypatch.setattr(batch, "atomic_consume_claim", lambda claim, supplied: None)
    monkeypatch.setattr(batch, "load_market", lambda source_root: market())
    output = tmp_path / "RESULT.json"
    batch.execute(output, tmp_path, api=api)
    original = json.loads(output.read_text())
    paired = copy.deepcopy(original)
    paired["paired"]["parent_winners_harmed"] += 1
    paired["result_sha256"] = batch.digest(
        {key: item for key, item in paired.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(paired))
    with pytest.raises(batch.Issue1377Error, match="SAVED_PAIRED_MISMATCH"):
        batch.audit_result(output, m)
    census = copy.deepcopy(original)
    census["instances"]["N_PARENT"]["census"]["signals"] += 1
    census["result_sha256"] = batch.digest(
        {key: item for key, item in census.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(census))
    with pytest.raises(batch.Issue1377Error, match="SAVED_CENSUS_MISMATCH"):
        batch.audit_result(output, m)
    swapped = copy.deepcopy(original)
    swapped["instances"]["N_PARENT"], swapped["instances"]["N_CANDIDATE"] = (
        swapped["instances"]["N_CANDIDATE"],
        swapped["instances"]["N_PARENT"],
    )
    swapped["paired"] = batch._paired(
        swapped["instances"]["N_PARENT"],
        swapped["instances"]["N_CANDIDATE"],
    )
    swapped["result_sha256"] = batch.digest(
        {key: item for key, item in swapped.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(swapped))
    with pytest.raises(batch.Issue1377Error, match="SAVED_INSTANCE_IDENTITY"):
        batch.audit_result(output, m)
    row_identity = copy.deepcopy(original)
    row_identity["instances"]["N_PARENT"]["trades"][0]["identity"] = "forged"
    row_identity["result_sha256"] = batch.digest(
        {key: item for key, item in row_identity.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(row_identity))
    with pytest.raises(batch.Issue1377Error, match="SAVED_ROW_IDENTITY"):
        batch.audit_result(output, m)
    safety = copy.deepcopy(original)
    safety["order_authority"] = "ENABLED"
    safety["promotion"] = True
    safety["result_sha256"] = batch.digest(
        {key: item for key, item in safety.items() if key != "result_sha256"}
    )
    output.write_text(json.dumps(safety))
    with pytest.raises(batch.Issue1377Error, match="SAVED_PROFILE_MISMATCH"):
        batch.audit_result(output, m)


def test_authority_refs_are_git_verified_and_checkout_is_exact(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    api, routes = authority_api(m)
    assert batch.verified_approval(api)["approval_commit_sha"] == "b" * 40
    assert batch.verified_claim(api)["claim_commit_sha"] == "c" * 40
    routes["/git/commits/" + "c" * 40]["parents"] = [{"sha": "f" * 40}]
    with pytest.raises(batch.Issue1377Error, match="CLAIM_PARENT_IDENTITY"):
        batch.verified_claim(api)
    routes["/git/commits/" + "c" * 40]["parents"] = [{"sha": "b" * 40}]
    claim_blob = routes["/git/trees/" + "e" * 40]["tree"][0]["sha"]
    original_content = routes["/git/blobs/" + claim_blob]["content"]
    routes["/git/blobs/" + claim_blob]["content"] = base64.b64encode(b"{}").decode()
    with pytest.raises(batch.Issue1377Error, match="AUTHORITY_BLOB_HASH"):
        batch.verified_claim(api)
    routes["/git/blobs/" + claim_blob]["content"] = original_content
    monkeypatch.setattr(batch, "current_head", lambda: "f" * 40)
    monkeypatch.setattr(batch, "load_market", lambda source_root: market())
    with pytest.raises(batch.Issue1377Error, match="EXECUTING_CHECKOUT"):
        batch.execute(tmp_path / "RESULT.json", tmp_path, api=api)


def test_current_head_rejects_dirty_checkout(monkeypatch) -> None:
    def output(command, **kwargs):
        if command[1:3] == ["rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        assert command[1:3] == ["status", "--porcelain=v1"]
        return " M ops/issue1377_mr_batch_v1.py\n"

    monkeypatch.setattr(batch.subprocess, "check_output", output)
    with pytest.raises(batch.Issue1377Error, match="EXECUTING_CHECKOUT_DIRTY"):
        batch.current_head()


def test_load_market_disables_mutable_cache(monkeypatch) -> None:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    data = market()
    calls = []

    def load_candles(source_root, timeframe, cache_dir):
        calls.append((source_root, timeframe, cache_dir))
        return data["frames"]

    monkeypatch.setattr(source, "load_candles", load_candles)
    monkeypatch.setattr(batch, "file_sha256", lambda path: batch.COST_SHA256)
    monkeypatch.setattr(batch, "read_json", lambda path: {"costs_bps": data["costs"]})
    loaded = batch.load_market(Path("/fixed/source"))
    assert calls == [(Path("/fixed/source"), 30, None)]
    assert set(loaded["frames"]) == set(batch.rules.PARENT_SYMBOLS)


def test_frozen_cost_snapshot_matches_driver_hash() -> None:
    assert batch.COST_PATH.is_file()
    assert batch.file_sha256(batch.COST_PATH) == batch.COST_SHA256


def test_claim_is_consumed_once_before_compute(monkeypatch) -> None:
    m = manifest()
    _, claim = authority(m)
    for key, value in claim["activation"].items():
        monkeypatch.setenv(key.upper(), value)
    created = {"ref": False}

    def api(method, route, payload):
        assert method == "POST"
        if route == "/git/blobs":
            raw = base64.b64decode(payload["content"])
            return {"sha": batch._git_blob_sha(raw)}
        if route == "/git/trees":
            return {"sha": "d" * 40}
        if route == "/git/commits":
            assert payload["parents"] == [claim["claim_commit_sha"]]
            return {"sha": "e" * 40}
        if created["ref"]:
            raise batch.Issue1377Error("CLAIM_ALREADY_CONSUMED_NO_RETRY")
        created["ref"] = True
        return {
            "ref": batch.CONSUMPTION_REF,
            "object": {"sha": "e" * 40},
        }

    receipt = batch.atomic_consume_claim(claim, m, api)
    assert receipt["state"] == "CONSUMED_NONRETRYABLE_BEFORE_COMPUTE"
    with pytest.raises(batch.Issue1377Error, match="CLAIM_ALREADY_CONSUMED"):
        batch.atomic_consume_claim(claim, m, api)


def test_end_boundary_has_no_later_h_bar_and_unresolved_is_not_forced_closed() -> None:
    data = market()
    assert all(int(frame.iloc[-1].close_ts_ms) == batch.END_MS for frame in data["frames"].values())
    m = manifest()
    result = batch.compare(data, m)
    for instance in result["instances"].values():
        assert all(int(row["outcome_available_ts_ms"]) < batch.END_MS for row in instance["trades"])
        assert all(row["state"].startswith("UNRESOLVED") for row in instance["unresolved"])


def test_workflow_tracks_all_execution_dependencies() -> None:
    workflow = (
        batch.ROOT / ".github/workflows/issue1377-keltner-orthogonal-v1.yml"
    ).read_text()
    for dependency in (
        "scalp7_source_data_v2.py",
        "scalp7_source_binding_repair_v2.py",
        "scalp7_execution_v2.py",
        "scalp7_metrics_v2.py",
    ):
        assert dependency in workflow
