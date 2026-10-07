from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
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


def v8_activation(m: dict) -> dict:
    return {
        "schema": "zel.issue1377.mr_v8_activation.v1",
        "issue": 1377,
        "v8_comment_id": batch.V8_COMMENT_ID,
        "token": batch.V8_TOKEN,
        "reviewed_source_sha": m["reviewed_source_sha"],
        "protocol_sha256": m["protocol_sha256"],
        "source_inventory_sha256": batch.SOURCE_INVENTORY_SHA256,
        "rule_sha256": batch.RULE_SHA256,
        "cost_sha256": batch.COST_SHA256,
        "period_ms": [batch.START_MS, batch.END_MS],
        "instance_ids": list(batch.INSTANCE_IDS),
        "economic_instances": 2,
        "global_heavy_group": batch.GLOBAL_HEAVY_GROUP,
        "source_files_sha256": {
            name: batch.file_sha256(batch.ROOT / name)
            for name in (
                "ops/issue1377_mr_batch_v1.py",
                ".github/workflows/issue1377-keltner-orthogonal-v1.yml",
                "tests/test_issue1377_mr_batch_v1.py",
            )
        },
        "order_authority": "BLOCKED",
        "promotion": False,
    }


def v8_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "101")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_JOB", "economic-v8")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("ISSUE1377_GLOBAL_HEAVY_GROUP", batch.GLOBAL_HEAVY_GROUP)


def test_direct_script_invocation_bootstraps_repository_imports(tmp_path: Path) -> None:
    script = batch.ROOT / "ops/issue1377_mr_batch_v1.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


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


def test_end_to_end_input_start_parent_candidate_save_audit_and_no_retry(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    calls = []
    monkeypatch.setattr(
        batch,
        "load_market",
        lambda source_root: calls.append(("market", source_root)) or market(),
    )
    def start(supplied, receipt, activation_document, api):
        assert calls == [("market", tmp_path)]
        calls.append(("start", receipt["receipt_sha256"]))
        return {
            "execution_commit_sha": "e" * 40,
            "reviewed_source_sha": supplied["reviewed_source_sha"],
            "manifest_sha256": supplied["manifest_sha256"],
            "activation": {
                "github_run_id": "101",
                "github_run_attempt": "1",
                "github_job": "economic-v8",
                "github_sha": "f" * 40,
            },
        }
    monkeypatch.setattr(batch, "atomic_start_v8", start)
    monkeypatch.setattr(
        batch,
        "persist_v8_result",
        lambda result_id, value, start, api: calls.append(("persist", result_id))
        or {"result_id": result_id},
    )
    activation_path = tmp_path / "ACTIVATION.json"
    activation_path.write_text(json.dumps(v8_activation(m)))
    output = tmp_path / "RESULTS"
    result = batch.execute_v8(output, activation_path, tmp_path)
    assert result["state"] == "COMPLETE_TWO_INSTANCES_PERSISTED_AND_AUDITED"
    assert [row[1] for row in calls if row[0] == "persist"] == [
        "N_PARENT",
        "N_CANDIDATE",
        "COMPARISON",
    ]
    assert calls[0][0] == "market" and calls[1][0] == "start"
    assert batch.audit_result(output / "COMPARISON.json", m)["state"] == "PASS_SAVED_CENSUS_AND_ACCOUNTING"
    with pytest.raises(batch.Issue1377Error, match="OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_RETRY"):
        batch.execute_v8(output, activation_path, tmp_path)


def test_saved_result_and_accounting_tamper_are_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    output = tmp_path / "RESULT.json"
    batch.write_once(output, batch.compare(market(), m))
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
    output = tmp_path / "RESULT.json"
    batch.write_once(output, batch.compare(market(), m))
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
    output = tmp_path / "RESULT.json"
    batch.write_once(output, batch.compare(market(), m))
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
    activation = v8_activation(m)
    activation["reviewed_source_sha"] = "f" * 40
    with pytest.raises(batch.Issue1377Error, match="V8_ACTIVATION_BINDING"):
        batch.validate_v8_activation(activation, m)


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
            raise batch.Issue1377Error("PERMANENT_REF_ALREADY_EXISTS_NO_RETRY")
        created["ref"] = True
        return {
            "ref": batch.CONSUMPTION_REF,
            "object": {"sha": "e" * 40},
        }

    receipt = batch.atomic_consume_claim(claim, m, api)
    assert receipt["state"] == "CONSUMED_NONRETRYABLE_BEFORE_COMPUTE"
    with pytest.raises(batch.Issue1377Error, match="PERMANENT_REF_ALREADY_EXISTS"):
        batch.atomic_consume_claim(claim, m, api)


def test_v8_activation_rejects_reviewed_source_file_hash_tamper() -> None:
    m = manifest()
    activation = v8_activation(m)
    activation["source_files_sha256"]["ops/issue1377_mr_batch_v1.py"] = "0" * 64
    with pytest.raises(batch.Issue1377Error, match="V8_ACTIVATION_SOURCE_FILE_DRIFT"):
        batch.validate_v8_activation(activation, m)


def test_v8_atomic_start_is_one_permanent_record_without_approval_chain(
    monkeypatch,
) -> None:
    m = manifest()
    receipt = batch.source_receipt(market())
    activation_document = v8_activation(m)
    v8_env(monkeypatch)
    calls = []
    created = {"ref": False}

    def api(method, route, payload):
        calls.append((route, copy.deepcopy(payload)))
        if route == "/git/blobs":
            raw = base64.b64decode(payload["content"])
            decoded = json.loads(raw)
            assert "approval_ref" not in decoded and "claim_ref" not in decoded
            assert decoded["source_receipt_sha256"] == receipt["receipt_sha256"]
            return {"sha": batch._git_blob_sha(raw)}
        if route == "/git/trees":
            return {"sha": "b" * 40}
        if route == "/git/commits":
            assert payload["parents"] == [m["reviewed_source_sha"]]
            return {"sha": "c" * 40}
        if created["ref"]:
            raise batch.Issue1377Error("PERMANENT_REF_ALREADY_EXISTS_NO_RETRY")
        created["ref"] = True
        return {"ref": batch.V8_EXECUTION_REF, "object": {"sha": "c" * 40}}

    start = batch.atomic_start_v8(m, receipt, activation_document, api)
    assert start["state"] == "STARTED_NONRETRYABLE_AFTER_INPUT_VALIDATION_BEFORE_COMPUTE"
    assert [route for route, _ in calls] == [
        "/git/blobs",
        "/git/trees",
        "/git/commits",
        "/git/refs",
    ]
    with pytest.raises(batch.Issue1377Error, match="PERMANENT_REF_ALREADY_EXISTS"):
        batch.atomic_start_v8(m, receipt, activation_document, api)


def test_v8_batch_runs_each_model_once_and_persists_parent_before_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    m = manifest()
    monkeypatch.setattr(batch, "current_head", lambda: m["reviewed_source_sha"])
    monkeypatch.setattr(batch, "load_market", lambda source_root: market())
    monkeypatch.setattr(
        batch,
        "atomic_start_v8",
        lambda manifest, receipt, activation_document, api: {
            "execution_commit_sha": "e" * 40,
            "reviewed_source_sha": manifest["reviewed_source_sha"],
            "manifest_sha256": manifest["manifest_sha256"],
            "activation": {"github_run_id": "1"},
        },
    )
    order = []
    original = batch._run_identity

    def run(identity, supplied_market):
        order.append(("run", identity))
        return original(identity, supplied_market)

    def persist(result_id, value, start, api):
        order.append(("persist", result_id))
        return {"result_id": result_id}

    monkeypatch.setattr(batch, "_run_identity", run)
    monkeypatch.setattr(batch, "persist_v8_result", persist)
    activation_path = tmp_path / "ACTIVATION.json"
    activation_path.write_text(json.dumps(v8_activation(m)))
    batch.execute_v8(tmp_path / "out", activation_path, tmp_path)
    assert order == [
        ("run", batch.PARENT),
        ("persist", "N_PARENT"),
        ("run", batch.CANDIDATE),
        ("persist", "N_CANDIDATE"),
        ("persist", "COMPARISON"),
    ]


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
    assert "group: a1-global-heavy-economic-evaluator-v1" in workflow
    assert "cancel-in-progress: false" in workflow
    assert batch.V8_TOKEN in workflow
    assert "issue1377-mr-v8-prestart-recovery-1-20261007T0220Z-542be1c" in workflow
    assert "ISSUE1377_V8_PRIOR_JOB_NOT_ZERO_STEP_CANCELLED" in workflow
    assert "ISSUE1377_V8_RECOVERY_REF_ALREADY_PRESENT" in workflow
    assert "V8_EXECUTION_RECOVERY.json" in workflow
    assert "python ops/issue1377_mr_batch_v1.py" in workflow
    assert "issue1377-mr-v8-economic-results" in workflow
