from __future__ import annotations

import copy
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
    claim = {**common, "schema": "zel.issue1377.mr_claim.v1", "state": "RESERVED_NONRETRYABLE", "claim_ref": batch.CLAIM_REF, "economic_instances": 2, "independent_approval_commit_sha": approval["approval_commit_sha"], "global_heavy_group": "a1-global-heavy-economic-evaluator-v1", "global_heavy_exclusive": True}
    return approval, claim


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


def test_end_to_end_input_authority_model_save_audit_and_no_retry(tmp_path: Path) -> None:
    m = manifest()
    approval, claim = authority(m)
    output = tmp_path / "RESULT.json"
    result = batch.execute(m, approval, claim, market(), output)
    assert result["instances"]["N_PARENT"]["census"]["signals"] >= 1
    assert result["instances"]["N_CANDIDATE"]["census"]["signals"] >= 1
    assert batch.audit_result(output, m)["state"] == "PASS_SAVED_CENSUS_AND_ACCOUNTING"
    with pytest.raises(batch.Issue1377Error, match="RESULT_ALREADY_EXISTS_NO_RETRY"):
        batch.execute(m, approval, claim, market(), output)


def test_saved_result_and_accounting_tamper_are_rejected(tmp_path: Path) -> None:
    m = manifest()
    approval, claim = authority(m)
    output = tmp_path / "RESULT.json"
    batch.execute(m, approval, claim, market(), output)
    value = json.loads(output.read_text())
    value["instances"]["N_PARENT"]["cost_1x"]["T"] += 1
    value["result_sha256"] = batch.digest({k: v for k, v in value.items() if k != "result_sha256"})
    output.write_text(json.dumps(value))
    with pytest.raises(batch.Issue1377Error, match="SAVED_ACCOUNTING_MISMATCH"):
        batch.audit_result(output, m)


def test_end_boundary_has_no_later_h_bar_and_unresolved_is_not_forced_closed() -> None:
    data = market()
    assert all(int(frame.iloc[-1].close_ts_ms) == batch.END_MS for frame in data["frames"].values())
    m = manifest()
    result = batch.compare(data, m)
    for instance in result["instances"].values():
        assert all(int(row["outcome_available_ts_ms"]) < batch.END_MS for row in instance["trades"])
        assert all(row["state"].startswith("UNRESOLVED") for row in instance["unresolved"])
