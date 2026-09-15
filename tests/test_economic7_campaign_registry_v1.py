import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from backend.research.rebuild.economic7_campaign_registry_v1 import (
    CampaignLedger,
    CandidateIdentity,
    MaterialPolicy,
    composite_promotion_gate,
    fusion_gate,
    material_attempt_gate,
    verified_material_receipt,
)


def identity(name="one", axis="one"):
    return CandidateIdentity(
        name, "turtle_trend", "frozen-parent", axis, *(["a" * 64] * 4)
    )


@pytest.fixture
def ledger(tmp_path):
    value = CampaignLedger(tmp_path / "ledger.db")
    value.create_scope("scope", "root", 3, 2, {"rule": "test-only"})
    return value


def test_single_owner_and_immutable_scope(ledger):
    assert not ledger.create_scope("scope", "root", 3, 2, {"rule": "test-only"})
    with pytest.raises(ValueError, match="IMMUTABLE_SCOPE"):
        ledger.create_scope("scope", "other", 3, 2, {"rule": "test-only"})
    with pytest.raises(PermissionError):
        ledger.reserve("scope", "other", identity())


def test_atomic_duplicate_claim_and_start(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: ledger.reserve("scope", "root", identity()), range(8))
        )
    assert sum(row["new"] for row in results) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        starts = list(
            pool.map(lambda _: ledger.start(identity().key, "root"), range(8))
        )
    assert sum(starts) == 1
    assert ledger.status("scope")["executions_started"] == 1


def test_renaming_or_scope_does_not_reset_rejection(ledger):
    key = ledger.reserve("scope", "root", identity())["identity_key"]
    assert ledger.finish(key, "root", "REJECTED", {"cause": "preflight"})
    assert not ledger.reserve("scope", "root", identity("renamed"))["new"]
    ledger.create_scope("next", "root", 1, 1, {})
    assert not ledger.reserve("next", "root", identity("new-campaign"))["new"]
    assert not ledger.start(key, "root")


def test_identity_immutability_and_budgets(ledger):
    ledger.reserve("scope", "root", identity())
    with pytest.raises(ValueError, match="IMMUTABLE_CANDIDATE"):
        ledger.reserve("scope", "root", identity(axis="changed"))
    for n in ("two", "three"):
        ledger.reserve("scope", "root", identity(n, n))
    with pytest.raises(ValueError, match="CANDIDATE_BUDGET"):
        ledger.reserve("scope", "root", identity("four", "four"))
    assert ledger.start(identity().key, "root")
    assert ledger.start(identity("two", "two").key, "root")
    with pytest.raises(ValueError, match="EXECUTION_BUDGET"):
        ledger.start(identity("three", "three").key, "root")


def test_close_and_terminal_are_idempotent_and_immutable(ledger):
    key = ledger.reserve("scope", "root", identity())["identity_key"]
    with pytest.raises(ValueError, match="EXECUTION_NOT_STARTED"):
        ledger.finish(key, "root", "COMPLETED", {})
    with pytest.raises(ValueError, match="CLOSE_REQUIRES_RUNNING"):
        ledger.record_close(key, "root", "trade-1", {})
    ledger.start(key, "root")
    assert ledger.record_close(key, "root", "trade-1", {"net": 1})
    assert not ledger.record_close(key, "root", "trade-1", {"net": 1})
    with pytest.raises(ValueError, match="IMMUTABLE_CLOSE"):
        ledger.record_close(key, "root", "trade-1", {"net": 2})
    assert ledger.finish(key, "root", "COMPLETED", {"t": 1})
    assert not ledger.finish(key, "root", "COMPLETED", {"t": 1})
    with pytest.raises(ValueError, match="IMMUTABLE_TERMINAL"):
        ledger.finish(key, "root", "COMPLETED", {"t": 2})


def test_legacy_ingest_never_allocates_or_rescores(ledger):
    original = {"state": "FAIL", "Net_bps": -12.5, "unknown": [1, 2]}
    first = ledger.ingest_legacy("scope", "root", "saved.json", original)
    assert first["new"] and first["identity_state"] == "legacy_no_canonical_id"
    assert not ledger.ingest_legacy("scope", "root", "saved.json", original)["new"]
    assert ledger.status("scope")["claims"] == {}
    assert ledger.status("scope")["executions_started"] == 0
    with ledger._db() as db:
        saved = json.loads(db.execute("SELECT receipt_json FROM legacy").fetchone()[0])
    assert saved == original


@pytest.fixture
def policy():
    directory = Path(__file__).resolve().parents[1] / "backend/research/rebuild"
    return MaterialPolicy.load(directory)


def acceptance(tmp_path, value, requirements=None):
    # Test-only explicit prior policy. Production must bind its own preregistration.
    source = tmp_path / "test-prereg-source.txt"
    source.write_text(
        "TEST ONLY: marginal net and DD improvement acceptance; no PF delta gate"
    )
    content = {
        "state": "FROZEN_PREREGISTRATION",
        "frozen_at": "2026-01-01T00:00:00Z",
        "source": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "subject_id": value.get("material_id", value.get("composite_id")),
        **{
            key: value[key]
            for key in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")
        },
        "requirements": (
            requirements
            if requirements is not None
            else [
                {"metric": "marginal_net_bps", "op": ">", "value": 0},
                {"metric": "dd_improvement_bps", "op": ">", "value": 0},
            ]
        ),
    }
    path = tmp_path / (content["subject_id"] + "-acceptance.json")
    raw = json.dumps(content).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def receipt(tmp_path, material="turtle_trend", role="entry_quality", **changes):
    value = {
        "material_id": material,
        "grade": "B",
        "role": role,
        "integrity": "PASS",
        "fresh_forward": True,
        "changed_axes": 1,
        **{
            k: "a" * 64
            for k in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")
        },
        "metrics": {
            "net_bps": 15.0,
            "pf": 1.3,
            "t": 20,
            "dd_bps": 12.0,
            "reference_dd_bps": 14.0,
            "reference_net_bps": 14.0,
            "reference_pf": 1.2,
            "reference_t": 25,
            "cost_bps_T": 14.0,
            "marginal_net_bps": 1.0,
            "delta_pf": 0.1,
            "dd_improvement_bps": 2.0,
            "winner_preservation": 0.95,
            "t_retention": 0.8,
            "max_loss_streak": 2,
        },
    }
    value["execution_started_at"] = "2026-01-02T00:00:00Z"
    value["marginal_acceptance"] = acceptance(tmp_path, value)
    value.update(changes)
    path = tmp_path / (material + ".json")
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_ssot_material_counts_and_gates(policy):
    assert len(policy.materials) == 20
    assert not any(
        row["material_grade"] in {"A", "B"} for row in policy.materials.values()
    )
    assert policy.minimum_trades == 12
    assert policy.minimum_pf_exclusive == 1
    assert policy.cost_floor_bps == 14


def test_d_cannot_generate_entries_and_hold_cannot_replay(policy):
    assert (
        material_attempt_gate(
            policy, "alpha_combo", "entry_quality", "marginal_ablation", 1, 1
        ).state
        == "BLOCKED"
    )
    assert (
        material_attempt_gate(
            policy, "alpha_combo", "context_filter_or_veto", "marginal_ablation", 1, 1
        ).state
        == "ELIGIBLE"
    )
    assert (
        material_attempt_gate(
            policy,
            "liquidity_sweep",
            "execution/microstructure",
            "standalone_grade_up",
            1,
            1,
        ).state
        == "HOLD"
    )
    assert (
        material_attempt_gate(
            policy,
            "liquidity_sweep",
            "execution/microstructure",
            "source_completion",
            1,
            1,
        ).state
        == "ELIGIBLE"
    )
    assert (
        material_attempt_gate(
            policy, "turtle_trend", "entry_quality", "marginal_ablation", 2, 1
        ).state
        == "BLOCKED"
    )
    assert (
        material_attempt_gate(
            policy, "turtle_trend", "entry_quality", "marginal_ablation", 1, 4
        ).state
        == "BLOCKED"
    )


def test_no_verified_b_no_fusion(policy):
    assert fusion_gate(policy, [], 0.2, 2).state == "BLOCKED"


def test_hash_binding_fresh_missing_and_nonfinite_metrics_hold(policy, tmp_path):
    path, sha = receipt(tmp_path)
    assert verified_material_receipt(path, "f" * 64, policy)[0].state == "HOLD"
    assert verified_material_receipt(path, sha, policy)[0].state == "ELIGIBLE"
    for changes in (
        {"fresh_forward": False},
        {"metrics": {}},
        {"metrics": {"net_bps": float("nan")}},
        {"data_sha256": "missing"},
    ):
        path, sha = receipt(tmp_path, **changes)
        assert verified_material_receipt(path, sha, policy)[0].state == "HOLD"


def test_fusion_complementarity_cosine_and_axis_budget(policy, tmp_path):
    a = receipt(tmp_path)
    b = receipt(tmp_path, "rsi_swing_fail", "exit_or_risk")
    assert fusion_gate(policy, [a, b], 0.2, 2).state == "ELIGIBLE"
    assert fusion_gate(policy, [a, b], 0.86, 2).state == "BLOCKED"
    assert fusion_gate(policy, [a, b], None, 2).state == "HOLD"
    assert fusion_gate(policy, [a, b], 0.2, 3).state == "BLOCKED"
    assert fusion_gate(policy, [a, a], 0.2, 2).state == "BLOCKED"


def test_composite_does_not_promote_without_rolling_and_marginal_evidence(
    policy, tmp_path
):
    assert composite_promotion_gate(policy, {}).state == "HOLD"
    a = receipt(tmp_path)
    b = receipt(tmp_path, "rsi_swing_fail", "exit_or_risk")
    row = {
        "parents": [{"path": str(p), "sha256": sha} for p, sha in (a, b)],
        "behavior_cosine": 0.2,
        "changed_axes": 2,
        "integrity": "PASS",
        **{
            key: "a" * 64
            for key in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")
        },
        "fresh_forward": True,
        "rolling_oos_positive": True,
        "metrics": {"marginal_net_bps": 1, "delta_pf": 0.1, "dd_improvement_bps": 2},
    }
    row["composite_id"] = "test-composite"
    row["execution_started_at"] = "2026-01-02T00:00:00Z"
    row["marginal_acceptance"] = acceptance(tmp_path, row)
    assert composite_promotion_gate(policy, row).state == "ELIGIBLE"
    row["fresh_forward"] = False
    assert composite_promotion_gate(policy, row).state == "HOLD"
    row["fresh_forward"] = True
    row["metrics"]["marginal_net_bps"] = -1
    assert composite_promotion_gate(policy, row).state == "BLOCKED"


def test_malformed_identity_rejected():
    with pytest.raises(ValueError, match="HASH_INVALID"):
        replace(identity(), cost_sha256="not-a-hash")


def test_positive_standalone_cannot_hide_negative_marginal_or_frozen_role(
    policy, tmp_path
):
    path, sha = receipt(tmp_path)
    value = json.loads(path.read_text())
    value["metrics"].update({"reference_net_bps": 100, "marginal_net_bps": -85})
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    assert (
        verified_material_receipt(path, hashlib.sha256(raw).hexdigest(), policy)[
            0
        ].state
        == "BLOCKED"
    )
    value["metrics"]["marginal_net_bps"] = 1
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    assert (
        verified_material_receipt(path, hashlib.sha256(raw).hexdigest(), policy)[
            0
        ].state
        == "HOLD"
    )
    path, sha = receipt(tmp_path, role="exit_or_risk")
    assert verified_material_receipt(path, sha, policy)[0].state == "BLOCKED"


def test_material_acceptance_has_no_unsourced_all_three_positive_fallback(
    policy, tmp_path
):
    path, sha = receipt(tmp_path)
    value = json.loads(path.read_text())
    value["metrics"].update({"pf": 1.1, "delta_pf": -0.1})
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    decision, _ = verified_material_receipt(
        path, hashlib.sha256(raw).hexdigest(), policy
    )
    assert decision.state == "ELIGIBLE"  # Explicit test policy accepts this tradeoff.
    value.pop("marginal_acceptance")
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    decision, _ = verified_material_receipt(
        path, hashlib.sha256(raw).hexdigest(), policy
    )
    assert decision.state == "HOLD"
    assert "HOLD_REQUIRES_PREREG_MARGINAL_ACCEPTANCE" in decision.reasons


@pytest.mark.parametrize(
    "fault", ["source", "late_freeze", "rule_binding", "unknown_metric"]
)
def test_acceptance_source_time_binding_and_metric_fail_closed(policy, tmp_path, fault):
    path, _ = receipt(tmp_path)
    value = json.loads(path.read_text())
    prereg_path = Path(value["marginal_acceptance"]["path"])
    prereg = json.loads(prereg_path.read_text())
    if fault == "source":
        prereg["source"]["sha256"] = "f" * 64
    elif fault == "late_freeze":
        prereg["frozen_at"] = "2026-01-03T00:00:00Z"
    elif fault == "rule_binding":
        prereg["rule_sha256"] = "b" * 64
    else:
        prereg["requirements"][0]["metric"] = "future_pnl"
    raw = json.dumps(prereg).encode()
    prereg_path.write_bytes(raw)
    value["marginal_acceptance"]["sha256"] = hashlib.sha256(raw).hexdigest()
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    assert (
        verified_material_receipt(path, hashlib.sha256(raw).hexdigest(), policy)[
            0
        ].state
        == "HOLD"
    )
