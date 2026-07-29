from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, bind_package, canonical_sha
from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_attribution_ledger_v1 import sha256 as attribution_sha
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_source_bound_multicandidate_guard_v1 import (
    MulticandidateIntegrityError,
    orchestrate,
)
from backend.research.strategy11_source_bound_multicandidate_orchestrator_v1 import (
    INPUT_SCHEMA,
    MulticandidateOrchestratorError,
)
from backend.tools.r7a4d_strategy11_source_bound_chain_fixture_v1 import (
    build_package,
    source,
)

OUT = Path("artifacts/strategy11_source_bound_multicandidate_orchestrator_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}
SHARED_RUN_ID = "40000000077"
SHARED_HEAD_SHA = canonical_sha({"fixture": "shared-w1-head"})
SHARED_MANIFEST_SHA = canonical_sha({"fixture": "shared-w1-manifest"})
SHARED_DATA_SHA = canonical_sha({"fixture": "shared-nonoverlap-data"})
SHARED_WINDOW_SHA = canonical_sha({"fixture": "shared-f1-f2-f3-w1-w2-w3-sealed-window"})
SHARED_EVIDENCE_MANIFEST_SHA = canonical_sha({"fixture": "shared-w1-w2-w3-new-sealed-evidence"})


def _rehash(raw_package: dict[str, Any], source_id: str) -> None:
    raw_package["sources"][source_id]["artifact_sha"] = canonical_sha(
        raw_package["sources"][source_id]["document"]
    )


def _recompute_source_row_sha(row: dict[str, Any]) -> None:
    payload = dict(row)
    payload.pop("source_row_sha", None)
    row["source_row_sha"] = attribution_sha(payload)


def prepare_adapter(
    strategy_id: str,
    candidate_id: str,
    candidate_sha: str,
    team_lane: str,
    *,
    synthesis: bool,
    correlation_offset: int,
    correlation_values: list[float],
    complete_oos: bool = True,
    trade_lineage_mismatch: bool = False,
    bad_material_seal: bool = False,
) -> dict[str, Any]:
    if strategy_id == "alpha_combo":
        edge = {
            "trades": 56,
            "win_rate_pct": 57.5,
            "net_pct": 24.2,
            "profit_factor": 3.8,
            "payoff": 2.9,
            "positive_windows": 4,
            "total_windows": 4,
            "retention_pct": 95.0,
        }
        confidence = {"score": 0.82, "uncertainty": 0.18, "sample_quality": "HIGH", "oos_windows": 4}
        risk = {
            "max_drawdown_pct": 3.2,
            "avg_loss_r": -0.31,
            "worst_loss_r": -0.61,
            "stress_worst_loss_r": -0.71,
            "joint_tail_budget_pct": 2.0,
            "max_exposure_pct": 20.0,
        }
    else:
        edge = {
            "trades": 48,
            "win_rate_pct": 47.9,
            "net_pct": 12.8,
            "profit_factor": 1.75,
            "payoff": 1.95,
            "positive_windows": 3,
            "total_windows": 4,
            "retention_pct": 90.0,
        }
        confidence = {"score": 0.66, "uncertainty": 0.28, "sample_quality": "MEDIUM", "oos_windows": 4}
        risk = {
            "max_drawdown_pct": 4.8,
            "avg_loss_r": -0.39,
            "worst_loss_r": -0.69,
            "stress_worst_loss_r": -0.74,
            "joint_tail_budget_pct": 2.8,
            "max_exposure_pct": 15.0,
        }

    raw = build_package(
        strategy_id=strategy_id,
        candidate_sha=candidate_sha,
        team_lane=team_lane,
        edge=edge,
        confidence=confidence,
        risk=risk,
        synthesis=synthesis,
        correlation_offset=correlation_offset,
        correlation_values=correlation_values,
    )

    proposal = raw["sources"]["proposal"]["document"]
    proposal["proposal_id"] = f"multicandidate.{strategy_id}.{candidate_id}"
    proposal["metadata"]["candidate_id"] = candidate_id
    proposal["metadata"]["shared_evidence_fixture"] = True
    proposal["lineage"]["data_sha"] = SHARED_DATA_SHA
    proposal["lineage"]["window_sha"] = SHARED_WINDOW_SHA
    proposal["lineage"]["source_manifest_sha"] = SHARED_MANIFEST_SHA
    proposal["lineage"]["run_id"] = SHARED_RUN_ID
    proposal["lineage"]["artifact"] = f"shared-w1-primary-{strategy_id}"
    proposal["lineage"]["data_epoch"] = "F1_F2_F3_W1_W2_W3_NEW_SEALED_FIXTURE"
    _rehash(raw, "proposal")

    evidence = raw["sources"]["evidence"]["document"]
    evidence["evidence_manifest_sha"] = SHARED_EVIDENCE_MANIFEST_SHA
    if not complete_oos:
        evidence["stages"] = {"w1": "PASS", "w2": "NOT_RUN", "w3": "NOT_RUN", "new_sealed": "NOT_RUN"}
        evidence["regime_coverage_pass"] = False
        evidence["window_concentration_pct"] = 100.0
    _rehash(raw, "evidence")

    ledger_rows = raw["sources"]["ledger"]["document"]["trades"]
    for row_index, row in enumerate(ledger_rows):
        row["data_sha"] = SHARED_DATA_SHA
        row["window_sha"] = SHARED_WINDOW_SHA
        row["manifest_sha"] = SHARED_MANIFEST_SHA
        if trade_lineage_mismatch and row_index == 0:
            row["data_sha"] = canonical_sha({"fixture": "wrong-trade-data"})
        _recompute_source_row_sha(row)
    _rehash(raw, "ledger")

    own_rows_sha = canonical_sha([
        (row["source_ledger_id"], row["source_row_id"], row["source_row_sha"])
        for row in ledger_rows
    ])
    own_previous_head = canonical_sha({"fixture": f"previous-head:{strategy_id}"})
    own_history = raw["sources"]["history"]["document"]
    own_history.update({
        "previous_head_sha": own_previous_head,
        "rows_sha": own_rows_sha,
        "sequence": 1,
        "current_head_sha": canonical_sha({
            "previous_head_sha": own_previous_head,
            "rows_sha": own_rows_sha,
            "sequence": 1,
        }),
        "append_only_verified": True,
    })
    _rehash(raw, "history")

    role_lineage = raw["sources"]["role_lineage"]["document"]
    role_lineage["source_manifest_sha"] = SHARED_MANIFEST_SHA
    _rehash(raw, "role_lineage")
    role_messages = raw["sources"]["role_messages"]["document"]["messages"]
    for message in role_messages:
        message["lineage"]["source_manifest_sha"] = SHARED_MANIFEST_SHA
    _rehash(raw, "role_messages")

    sealed_proposal = seal_proposal(proposal)
    classifier_policy = raw["sources"]["portfolio"]["document"]["classifier"]
    classification = classify_candidate(sealed_proposal, evidence, classifier_policy)
    expected_classification = "SYNTHESIS" if synthesis and complete_oos else ("CORE" if complete_oos else "HOLD")
    assert classification["classification"] == expected_classification, classification

    material_context = raw["sources"]["portfolio"]["document"]["material_context"]
    material_id = f"material.{strategy_id}.{candidate_id}"
    material_context.update({
        "material_id": material_id,
        "material_sealed": complete_oos,
        "material_seal_candidate_sha": candidate_sha,
        "material_seal_sha": canonical_sha({
            "material_id": material_id,
            "candidate_sha": candidate_sha,
            "classification_sha": classification["classification_sha"],
            "source_manifest_sha": SHARED_MANIFEST_SHA,
        }),
    })
    if bad_material_seal:
        material_context["material_seal_sha"] = canonical_sha({"fixture": "bad-material-seal"})
    _rehash(raw, "portfolio")

    bound = bind_package(raw)
    return {
        "state": "PASS_REAL_W1_EXACT_SHA_SOURCE_BINDING",
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "source_w1_run_id": SHARED_RUN_ID,
        "source_w1_head_sha": SHARED_HEAD_SHA,
        "source_w1_manifest_sha": SHARED_MANIFEST_SHA,
        "candidate_sha": candidate_sha,
        "bound_package": bound,
        "all_values_source_bound": True,
        "inference_used": False,
        "runtime_bound": False,
        **SAFETY,
    }


def portfolio_history_source(adapters: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        trade
        for adapter in adapters
        for trade in adapter["bound_package"]["groups"]["source_ledger"]["trades"]
    ]
    rows_sha = canonical_sha([
        (row["source_ledger_id"], row["source_row_id"], row["source_row_sha"])
        for row in rows
    ])
    previous_head = canonical_sha({"fixture": "portfolio-previous-source-head"})
    document = {
        "previous_head_sha": previous_head,
        "rows_sha": rows_sha,
        "sequence": 2,
        "current_head_sha": canonical_sha({
            "previous_head_sha": previous_head,
            "rows_sha": rows_sha,
            "sequence": 2,
        }),
        "append_only_verified": True,
    }
    return source("SOURCE_LEDGER_HISTORY", "fixture-portfolio-source-history", SHARED_RUN_ID, document)


def payload(adapters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": INPUT_SCHEMA,
        "candidate_adapters": adapters,
        "portfolio_source_history": portfolio_history_source(adapters),
        "authority": AUTHORITY,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    alpha = prepare_adapter(
        "alpha_combo",
        "TIME54",
        canonical_sha({"fixture": "alpha-TIME54"}),
        "ALPHA",
        synthesis=False,
        correlation_offset=0,
        correlation_values=[0.80, -0.20, 0.60, 0.40],
    )
    turtle = prepare_adapter(
        "turtle_trend",
        "TRAIL_ACT100_ATR200",
        canonical_sha({"fixture": "turtle-TRAIL_ACT100_ATR200"}),
        "BETA",
        synthesis=True,
        correlation_offset=1,
        correlation_values=[-0.10, 0.70, -0.15, 0.90],
    )

    passed = orchestrate(payload([alpha, turtle]))
    assert passed["state"] == "PASS_SOURCE_BOUND_MULTICANDIDATE_PREFLIGHT", passed
    assert passed["classifications"] == {"alpha_combo": "CORE", "turtle_trend": "SYNTHESIS"}
    assert passed["selected_combination"] == ["alpha_combo", "turtle_trend"]
    assert passed["shadow_20c_ready"] is True
    assert passed["automatic_shadow_start"] is False
    assert passed["source_history_verified"] is True
    assert passed["bound_package_integrity_verified"] is True
    assert passed["verified_bound_group_count"] == 20
    assert passed["verified_bound_field_count"] >= 650
    assert passed["verified_source_trade_count"] == 8

    single = orchestrate(payload([alpha]))
    assert single["state"] == "HOLD_MULTICANDIDATE_INSUFFICIENT_ELIGIBLE", single
    assert single["shadow_20c_ready"] is False

    incomplete_turtle = prepare_adapter(
        "turtle_trend",
        "TRAIL_ACT100_ATR200",
        canonical_sha({"fixture": "turtle-TRAIL_ACT100_ATR200"}),
        "BETA",
        synthesis=True,
        correlation_offset=1,
        correlation_values=[-0.10, 0.70, -0.15, 0.90],
        complete_oos=False,
    )
    incomplete = orchestrate(payload([alpha, incomplete_turtle]))
    assert incomplete["state"] == "HOLD_MULTICANDIDATE_INSUFFICIENT_ELIGIBLE", incomplete
    assert incomplete["classifications"]["turtle_trend"] == "HOLD"

    duplicate_turtle = prepare_adapter(
        "turtle_trend",
        "TRAIL_ACT100_ATR200",
        canonical_sha({"fixture": "turtle-TRAIL_ACT100_ATR200"}),
        "BETA",
        synthesis=True,
        correlation_offset=0,
        correlation_values=[0.80, -0.20, 0.60, 0.40],
    )
    no_combo = orchestrate(payload([alpha, duplicate_turtle]))
    assert no_combo["state"] == "HOLD_MULTICANDIDATE_NO_COMPATIBLE_COMBINATION", no_combo

    negative_cases: list[str] = []

    bad_head = copy.deepcopy(turtle)
    bad_head["source_w1_head_sha"] = canonical_sha({"fixture": "other-head"})
    try:
        orchestrate(payload([alpha, bad_head]))
    except MulticandidateIntegrityError as exc:
        assert str(exc) == "SHARED_W1_HEAD_SHA_MISMATCH", exc
        negative_cases.append("SHARED_W1_HEAD_SHA_MISMATCH")
    else:
        raise AssertionError("head mismatch accepted")

    tampered = copy.deepcopy(alpha)
    tampered["bound_package"]["groups"]["proposal_core"]["edge"]["net_pct"] += 1.0
    try:
        orchestrate(payload([tampered, turtle]))
    except MulticandidateIntegrityError as exc:
        assert str(exc).startswith("GROUP_BINDING_SHA_MISMATCH") or str(exc).startswith("FIELD_BINDING_VALUE_SHA_MISMATCH"), exc
        negative_cases.append("BOUND_LEAF_TAMPER")
    else:
        raise AssertionError("bound leaf tamper accepted")

    bad_trade_turtle = prepare_adapter(
        "turtle_trend",
        "TRAIL_ACT100_ATR200",
        canonical_sha({"fixture": "turtle-TRAIL_ACT100_ATR200"}),
        "BETA",
        synthesis=True,
        correlation_offset=1,
        correlation_values=[-0.10, 0.70, -0.15, 0.90],
        trade_lineage_mismatch=True,
    )
    try:
        orchestrate(payload([alpha, bad_trade_turtle]))
    except MulticandidateIntegrityError as exc:
        assert str(exc).startswith("SOURCE_LEDGER_DATA_SHA_MISMATCH"), exc
        negative_cases.append("SOURCE_LEDGER_DATA_SHA_MISMATCH")
    else:
        raise AssertionError("trade lineage mismatch accepted")

    bad_seal_turtle = prepare_adapter(
        "turtle_trend",
        "TRAIL_ACT100_ATR200",
        canonical_sha({"fixture": "turtle-TRAIL_ACT100_ATR200"}),
        "BETA",
        synthesis=True,
        correlation_offset=1,
        correlation_values=[-0.10, 0.70, -0.15, 0.90],
        bad_material_seal=True,
    )
    try:
        orchestrate(payload([alpha, bad_seal_turtle]))
    except MulticandidateOrchestratorError as exc:
        assert str(exc).startswith("MATERIAL_SEAL_SHA_MISMATCH"), exc
        negative_cases.append("MATERIAL_SEAL_SHA_MISMATCH")
    else:
        raise AssertionError("bad material seal accepted")

    summary = {
        "schema_version": "strategy11.source_bound_multicandidate_fixture.v1",
        "state": "PASS_SOURCE_BOUND_MULTICANDIDATE_ORCHESTRATOR_FIXTURES",
        "pass_state": passed["state"],
        "classifications": passed["classifications"],
        "selected_combination": passed["selected_combination"],
        "target_risk_weights": passed["target_risk_weights"],
        "verified_bound_group_count": passed["verified_bound_group_count"],
        "verified_bound_field_count": passed["verified_bound_field_count"],
        "verified_source_trade_count": passed["verified_source_trade_count"],
        "single_candidate_state": single["state"],
        "incomplete_evidence_state": incomplete["state"],
        "duplicate_combination_state": no_combo["state"],
        "negative_cases_passed": negative_cases,
        "shadow_20c_ready": passed["shadow_20c_ready"],
        "automatic_shadow_start": passed["automatic_shadow_start"],
        "fixture_only": True,
        "real_shadow_started": False,
        "production_threshold_authority": False,
        "next": "SHADOW_20C_READ_ONLY_CANARY_ORCHESTRATOR",
        "runtime_bound": False,
        **SAFETY,
    }
    summary["fixture_sha"] = canonical_sha(summary)

    outputs = {
        "summary.json": summary,
        "pass.json": passed,
        "single_candidate_hold.json": single,
        "incomplete_evidence_hold.json": incomplete,
        "duplicate_combination_hold.json": no_combo,
    }
    for name, row in outputs.items():
        (OUT / name).write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], "fields=", summary["verified_bound_field_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
