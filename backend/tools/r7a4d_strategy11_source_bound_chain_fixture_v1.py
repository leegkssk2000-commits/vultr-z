from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_source_binding_contract_v1 import (
    SAFETY,
    SCHEMA_VERSION,
    SourceBindingError,
    attribution_history_envelope,
    bind_package,
    canonical_sha,
)
from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.contracts.strategy11_role_boundary_zbot_zico_lico_zlice_v1 import (
    role_manifest,
    validate_message,
)
from backend.research.strategy11_attribution_ledger_v1 import build_projection, sha256 as attribution_sha
from backend.research.strategy11_ensemble_correlation_analyzer_v1 import analyze_candidates
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_model_risk_governance_v1 import evaluate_model_risk
from backend.research.strategy11_portfolio_governor_v1 import govern

OUT = Path("artifacts/strategy11_source_bound_chain_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}
FIXTURE_SHA = lambda token: canonical_sha({"fixture": token})

CLASSIFIER_POLICY = {
    "policy_id": "FIXTURE_ONLY_NOT_PRODUCTION_THRESHOLD_AUTHORITY",
    "min_trades": 30,
    "min_positive_window_ratio": 0.70,
    "min_retention_pct": 80.0,
    "min_profit_factor": 1.20,
    "min_net_pct": 0.0,
    "max_drawdown_pct": 10.0,
    "min_worst_loss_r": -0.75,
    "min_stress_worst_loss_r": -0.75,
    "min_confidence_core": 0.65,
    "max_uncertainty_core": 0.35,
    "max_symbol_concentration_core_pct": 60.0,
    "max_window_concentration_core_pct": 60.0,
    "max_regime_concentration_core_pct": 70.0,
    "max_concentration_synthesis_pct": 85.0,
}

CORRELATION_POLICY = {
    "policy_id": "FIXTURE_ONLY_CORRELATION_POLICY",
    "max_cosine_similarity": 0.85,
    "max_abs_pnl_correlation": 0.90,
    "max_loss_concurrence": 0.80,
    "max_drawdown_concurrence": 0.90,
    "rolling_window": 3,
    "min_combination_size": 2,
    "max_combination_size": 2,
    "max_candidate_combinations": 2,
}

GOVERNOR_POLICY = {
    "policy_id": "FIXTURE_ONLY_GOVERNOR_POLICY",
    "total_risk_budget": 1.0,
    "max_material_weight": 0.80,
    "min_material_weight": 0.20,
    "max_turnover": 1.50,
}

MODEL_RISK_POLICY = {
    "policy_id": "FIXTURE_ONLY_MODEL_RISK_POLICY",
    "drift_psi_warn": 0.20,
    "drift_psi_rollback": 0.35,
    "calibration_error_warn": 0.15,
    "calibration_error_rollback": 0.25,
    "error_budget_warn_ratio": 0.70,
    "error_budget_block_ratio": 1.00,
    "max_shadow_dd_pct": 8.0,
    "max_cost_overrun_pct": 20.0,
    "max_correlation_breach_count": 1,
    "max_consecutive_failures": 3,
}


def source(kind: str, artifact: str, run_id: str, document: Any, transform: str = "FIXTURE_ONLY") -> dict[str, Any]:
    return {
        "source_kind": kind,
        "artifact": artifact,
        "run_id": run_id,
        "artifact_sha": canonical_sha(document),
        "document": document,
        "transform": transform,
        "inference_used": False,
        "private_fields_present": False,
        "stale": False,
    }


def proposal_core(
    strategy_id: str,
    candidate_sha: str,
    team_lane: str,
    edge: dict[str, Any],
    confidence: dict[str, Any],
    risk: dict[str, Any],
    source_tag: str,
) -> dict[str, Any]:
    manifest_sha = FIXTURE_SHA(f"manifest:{source_tag}")
    return {
        "schema_version": "strategy11.strategy_proposal.v1",
        "proposal_id": f"fixture.{strategy_id}.{source_tag}",
        "strategy_id": strategy_id,
        "candidate_sha": candidate_sha,
        "producer": {"team_lane": team_lane, "role": "RESEARCH", "independent_proposal": True},
        "market": {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframe": "15m",
            "side": "LONG",
            "regime": "MIXED",
            "session": "ALL",
        },
        "edge": edge,
        "confidence": confidence,
        "cost_envelope": {
            "fee_bps": 2.0,
            "slippage_bps": 1.5,
            "funding_8h_pct": 0.01,
            "latency_ms": 250.0,
            "stress_multiplier": 2.0,
            "capacity_notional_usdt": 25000.0,
        },
        "risk_envelope": risk,
        "lineage": {
            "strategy_source_sha": FIXTURE_SHA(f"strategy:{strategy_id}"),
            "candidate_config_sha": candidate_sha,
            "data_sha": FIXTURE_SHA(f"data:{source_tag}"),
            "window_sha": FIXTURE_SHA(f"window:{source_tag}"),
            "source_manifest_sha": manifest_sha,
            "run_id": f"fixture-{source_tag}",
            "artifact": f"fixture-w1-{source_tag}",
            "data_epoch": "F1_F2_F3_W1_FIXTURE_ONLY",
        },
        "proposal_state": "REQUEST_EVALUATION",
        "reason_codes": ["STRICT_SOURCE_BOUND_FIXTURE"],
        "authority": {
            "stage": "RESEARCH",
            "research_only": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
        "metadata": {
            "fixture_only": True,
            "production_threshold_authority": False,
            "upstream_source_shas": [
                FIXTURE_SHA(f"w1:{source_tag}"),
                FIXTURE_SHA(f"lico:{source_tag}"),
                FIXTURE_SHA(f"calibration:{source_tag}"),
            ],
        },
    }


def classifier_evidence(strategy_id: str, *, synthesis: bool) -> dict[str, Any]:
    return {
        "stages": {"w1": "PASS", "w2": "PASS", "w3": "PASS", "new_sealed": "PASS"},
        "trade_quota_pass": True,
        "regime_coverage_pass": True,
        "dsr_pass": True,
        "bh_fdr_pass": True,
        "independent_edge_pass": not synthesis,
        "synthesis_eligible": synthesis,
        "symbol_concentration_pct": 44.0 if not synthesis else 72.0,
        "window_concentration_pct": 40.0,
        "regime_concentration_pct": 52.0,
        "evidence_manifest_sha": FIXTURE_SHA(f"classifier-evidence:{strategy_id}"),
    }


def correlation_trades(strategy_id: str, offset: int, values: list[float]) -> dict[str, Any]:
    rows = []
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT"]
    regimes = ["UPTREND", "RANGE", "DOWNTREND", "HIGH_VOL"]
    for index, value in enumerate(values):
        rows.append({
            "timestamp": f"2026-08-01T{offset + index * 2:02d}:00:00Z",
            "net_r": value,
            "symbol": symbols[index % len(symbols)],
            "regime": regimes[index % len(regimes)],
        })
    return {"strategy_id": strategy_id, "trades": rows}


def source_row(
    *,
    strategy_id: str,
    material_id: str,
    team: str,
    candidate_sha: str,
    ordinal: int,
    gross_pnl_r: float,
) -> dict[str, Any]:
    row = {
        "trade_id": f"{strategy_id}.fixture.{ordinal}",
        "source_ledger_id": "fixture.formal-ledger",
        "source_row_id": f"row-{strategy_id}-{ordinal}",
        "strategy_id": strategy_id,
        "material_id": material_id,
        "team": team,
        "symbol": ["BTCUSDT", "ETHUSDT", "SOLUSDT"][ordinal % 3],
        "regime": ["UPTREND", "RANGE", "DOWNTREND"][ordinal % 3],
        "window_id": ["W1", "W2", "W3", "NEW_SEALED"][ordinal % 4],
        "gross_pnl_r": gross_pnl_r,
        "fee_r": 0.01,
        "slippage_r": 0.01,
        "funding_r": 0.005,
        "source_sha": FIXTURE_SHA(f"source:{strategy_id}"),
        "candidate_sha": candidate_sha,
        "data_sha": FIXTURE_SHA(f"data:{strategy_id}"),
        "window_sha": FIXTURE_SHA(f"window:{strategy_id}:{ordinal}"),
        "manifest_sha": FIXTURE_SHA(f"manifest:{strategy_id}"),
    }
    row["source_row_sha"] = attribution_sha(row)
    return row


def role_bundle(strategy_id: str, manifest_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    lineage = {
        "strategy_id": strategy_id,
        "method_id": "METHOD_FIXTURE_SOURCE_BOUND",
        "skill_id": "SKILL_FIXTURE_SOURCE_BOUND",
        "team_id": "ALPHA" if strategy_id == "alpha_combo" else "BETA",
        "event_ts": "2026-08-01T08:30:00Z",
        "source_ids": [f"source:{strategy_id}", "policy:fixture"],
        "contract_version": "strategy11.source_binding_contract.v1",
        "source_manifest_sha": manifest_sha,
        "sbot_veto_active": False,
    }
    authority = {**AUTHORITY}
    messages = [
        {
            "role": "LICO",
            "action": "EMIT_CONTEXT_ENVELOPE",
            "payload": {
                "liquidity": {"state": "PASS"},
                "macro": {"state": "NEUTRAL"},
                "fx": {"state": "NEUTRAL"},
                "freshness": {"state": "PASS"},
                "cost_capacity": {"state": "PASS"},
            },
            "confidence": 0.80,
            "abstain": False,
            "stale": False,
            "latency_ms": 50.0,
            "reason_codes": ["SOURCE_BOUND_CONTEXT"],
            "sbot_veto_active": False,
            "lineage": {key: value for key, value in lineage.items() if key != "sbot_veto_active"},
            "authority": authority,
        },
        {
            "role": "ZBOT",
            "action": "ADVISE",
            "payload": {
                "advice": "KEEP_RESEARCH_ONLY",
                "alternatives": ["RETAIN_INCUMBENT"],
                "counterfactual": "HOLD_IF_LINEAGE_BREAKS",
            },
            "confidence": 0.70,
            "abstain": False,
            "stale": False,
            "latency_ms": 60.0,
            "reason_codes": ["ADVISORY_ONLY"],
            "sbot_veto_active": False,
            "lineage": {key: value for key, value in lineage.items() if key != "sbot_veto_active"},
            "authority": authority,
        },
        {
            "role": "ZICO",
            "action": "EMIT_LIFECYCLE_CONTEXT",
            "payload": {
                "intent_state": "RESEARCH",
                "lifecycle_state": "SOURCE_BOUND_FIXTURE",
                "control_context": {"rollback_target": "INCUMBENT"},
            },
            "confidence": 0.75,
            "abstain": False,
            "stale": False,
            "latency_ms": 40.0,
            "reason_codes": ["NO_EXECUTION_AUTHORITY"],
            "sbot_veto_active": False,
            "lineage": {key: value for key, value in lineage.items() if key != "sbot_veto_active"},
            "authority": authority,
        },
        {
            "role": "ZLICE",
            "action": "EMIT_ATTRIBUTION",
            "payload": {
                "evidence_lineage": {"state": "PASS"},
                "lifecycle_trace": ["PROPOSAL", "CLASSIFIER", "CORRELATION", "GOVERNOR"],
                "source_ids": lineage["source_ids"],
            },
            "confidence": 0.85,
            "abstain": False,
            "stale": False,
            "latency_ms": 30.0,
            "reason_codes": ["PROJECTION_ONLY"],
            "sbot_veto_active": False,
            "lineage": {key: value for key, value in lineage.items() if key != "sbot_veto_active"},
            "authority": authority,
        },
    ]
    return lineage, {"messages": messages}


def build_package(
    *,
    strategy_id: str,
    candidate_sha: str,
    team_lane: str,
    edge: dict[str, Any],
    confidence: dict[str, Any],
    risk: dict[str, Any],
    synthesis: bool,
    correlation_offset: int,
    correlation_values: list[float],
) -> dict[str, Any]:
    proposal = proposal_core(strategy_id, candidate_sha, team_lane, edge, confidence, risk, strategy_id)
    evidence = classifier_evidence(strategy_id, synthesis=synthesis)
    correlation = correlation_trades(strategy_id, correlation_offset, correlation_values)
    rows = [
        source_row(
            strategy_id=strategy_id,
            material_id=f"material.{strategy_id}",
            team=team_lane,
            candidate_sha=candidate_sha,
            ordinal=index,
            gross_pnl_r=value,
        )
        for index, value in enumerate(correlation_values)
    ]
    rows_sha = canonical_sha([
        (row["source_ledger_id"], row["source_row_id"], row["source_row_sha"])
        for row in rows
    ])
    previous_head = FIXTURE_SHA(f"previous-ledger-head:{strategy_id}")
    history = {
        "previous_head_sha": previous_head,
        "rows_sha": rows_sha,
        "sequence": 1,
        "current_head_sha": canonical_sha({
            "previous_head_sha": previous_head,
            "rows_sha": rows_sha,
            "sequence": 1,
        }),
        "append_only_verified": True,
    }
    lineage, messages = role_bundle(strategy_id, proposal["lineage"]["source_manifest_sha"])
    baseline = {
        "drift_psi": 0.05,
        "calibration_error": 0.06,
        "calibration_sample_count": 120,
        "error_budget_used": 1,
        "error_budget_limit": 10,
        "shadow_dd_pct": 2.5,
        "cost_overrun_pct": 4.0,
        "correlation_breach_count": 0,
        "consecutive_failures": 0,
        "incumbent_available": True,
        "shadow_only": True,
    }
    portfolio_policy = {
        "classifier": CLASSIFIER_POLICY,
        "correlation": CORRELATION_POLICY,
        "governor": GOVERNOR_POLICY,
        "material_context": {
            "net_after_cost": edge["net_pct"],
            "joint_tail_dd_pct": risk["joint_tail_budget_pct"],
            "cost_pct": 0.50,
            "capacity_score": 0.90 if strategy_id == "alpha_combo" else 0.75,
            "incumbent_weight": 0.50,
            "material_sealed": True,
            "material_seal_scope": "FIXTURE_ONLY_NOT_PRODUCTION_AUTHORITY",
        },
    }
    sources = {
        "proposal": source(
            "DETERMINISTIC_PROPOSAL_ADAPTER",
            f"fixture-proposal-{strategy_id}",
            f"fixture-proposal-{strategy_id}",
            proposal,
            "DETERMINISTIC_ADAPTER",
        ),
        "evidence": source(
            "DETERMINISTIC_EVIDENCE_ADAPTER",
            f"fixture-evidence-{strategy_id}",
            f"fixture-evidence-{strategy_id}",
            evidence,
            "DETERMINISTIC_ADAPTER",
        ),
        "correlation": source("TIMESTAMPED_TRADE_LEDGER", f"fixture-correlation-{strategy_id}", "fixture-ledger", correlation),
        "portfolio": source("FIXTURE_POLICY", "fixture-portfolio-policy", "fixture-policy", portfolio_policy),
        "ledger": source("SOURCE_LEDGER", f"fixture-source-ledger-{strategy_id}", "fixture-ledger", {"trades": rows}),
        "history": source("SOURCE_LEDGER_HISTORY", f"fixture-source-history-{strategy_id}", "fixture-ledger", history),
        "role_lineage": source("ROLE_LINEAGE_SSOT", f"fixture-role-lineage-{strategy_id}", "fixture-role", lineage),
        "role_messages": source("ROLE_MESSAGE_BUNDLE", f"fixture-role-messages-{strategy_id}", "fixture-role", messages),
        "model_baseline": source("SHADOW_MODEL_RISK_BASELINE", f"fixture-model-baseline-{strategy_id}", "fixture-shadow", baseline),
        "model_policy": source("FIXTURE_POLICY", "fixture-model-risk-policy", "fixture-policy", MODEL_RISK_POLICY),
    }
    bindings = {
        "proposal_core": {"source_id": "proposal", "field_path": "$"},
        "classifier_evidence": {"source_id": "evidence", "field_path": "$"},
        "correlation_ledger": {"source_id": "correlation", "field_path": "$"},
        "portfolio_policy": {"source_id": "portfolio", "field_path": "$"},
        "source_ledger": {"source_id": "ledger", "field_path": "$"},
        "source_history": {"source_id": "history", "field_path": "$"},
        "role_lineage": {"source_id": "role_lineage", "field_path": "$"},
        "role_messages": {"source_id": "role_messages", "field_path": "$"},
        "model_risk_baseline": {"source_id": "model_baseline", "field_path": "$"},
        "model_risk_policy": {"source_id": "model_policy", "field_path": "$"},
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": f"fixture.source-bound.{strategy_id}",
        "sources": sources,
        "group_bindings": bindings,
        "authority": AUTHORITY,
    }


def assert_negative_cases(package: dict[str, Any]) -> list[str]:
    passed: list[str] = []

    tampered = copy.deepcopy(package)
    tampered["sources"]["proposal"]["document"]["edge"]["net_pct"] += 1.0
    try:
        bind_package(tampered)
    except SourceBindingError as exc:
        assert str(exc).startswith("SOURCE_ARTIFACT_SHA_MISMATCH"), exc
        passed.append("SOURCE_ARTIFACT_SHA_TAMPER")
    else:
        raise AssertionError("tampered source was accepted")

    inferred = copy.deepcopy(package)
    inferred["sources"]["proposal"]["inference_used"] = True
    try:
        bind_package(inferred)
    except SourceBindingError as exc:
        assert str(exc).startswith("INFERENCE_FORBIDDEN"), exc
        passed.append("INFERENCE_FORBIDDEN")
    else:
        raise AssertionError("inferred source was accepted")

    missing = copy.deepcopy(package)
    del missing["group_bindings"]["model_risk_baseline"]
    try:
        bind_package(missing)
    except SourceBindingError as exc:
        assert str(exc).startswith("REQUIRED_BINDING_GROUP_MISSING"), exc
        passed.append("REQUIRED_GROUP_FAIL_CLOSED")
    else:
        raise AssertionError("missing binding group was accepted")

    unsafe = copy.deepcopy(package)
    unsafe["authority"]["execution_allowed"] = True
    try:
        bind_package(unsafe)
    except SourceBindingError as exc:
        assert str(exc) == "AUTHORITY_MISMATCH:execution_allowed", exc
        passed.append("EXECUTION_AUTHORITY_FAIL_CLOSED")
    else:
        raise AssertionError("unsafe authority was accepted")

    return passed


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    alpha_candidate_sha = FIXTURE_SHA("candidate:alpha:TIME54")
    turtle_candidate_sha = FIXTURE_SHA("candidate:turtle:TRAIL_ACT100_ATR200")

    alpha_package = build_package(
        strategy_id="alpha_combo",
        candidate_sha=alpha_candidate_sha,
        team_lane="ALPHA",
        edge={
            "trades": 56,
            "win_rate_pct": 57.5,
            "net_pct": 24.2,
            "profit_factor": 3.8,
            "payoff": 2.9,
            "positive_windows": 4,
            "total_windows": 4,
            "retention_pct": 95.0,
        },
        confidence={"score": 0.82, "uncertainty": 0.18, "sample_quality": "HIGH", "oos_windows": 3},
        risk={
            "max_drawdown_pct": 3.2,
            "avg_loss_r": -0.31,
            "worst_loss_r": -0.61,
            "stress_worst_loss_r": -0.71,
            "joint_tail_budget_pct": 2.0,
            "max_exposure_pct": 20.0,
        },
        synthesis=False,
        correlation_offset=0,
        correlation_values=[0.80, -0.20, 0.60, 0.40],
    )
    turtle_package = build_package(
        strategy_id="turtle_trend",
        candidate_sha=turtle_candidate_sha,
        team_lane="BETA",
        edge={
            "trades": 48,
            "win_rate_pct": 47.9,
            "net_pct": 12.8,
            "profit_factor": 1.75,
            "payoff": 1.95,
            "positive_windows": 3,
            "total_windows": 4,
            "retention_pct": 90.0,
        },
        confidence={"score": 0.66, "uncertainty": 0.28, "sample_quality": "MEDIUM", "oos_windows": 3},
        risk={
            "max_drawdown_pct": 4.8,
            "avg_loss_r": -0.39,
            "worst_loss_r": -0.69,
            "stress_worst_loss_r": -0.74,
            "joint_tail_budget_pct": 2.8,
            "max_exposure_pct": 15.0,
        },
        synthesis=True,
        correlation_offset=1,
        correlation_values=[-0.10, 0.70, -0.15, 0.90],
    )

    negative_cases = assert_negative_cases(alpha_package)
    bound = [bind_package(alpha_package), bind_package(turtle_package)]
    assert all(row["status"] == "PASS_STRICT_SOURCE_BINDING" for row in bound)
    assert all(row["bound_group_count"] == 10 for row in bound)
    assert all(row["all_values_source_bound"] is True for row in bound)

    proposals = [seal_proposal(row["groups"]["proposal_core"]) for row in bound]
    classifications = [
        classify_candidate(
            proposal,
            bound_row["groups"]["classifier_evidence"],
            bound_row["groups"]["portfolio_policy"]["classifier"],
        )
        for proposal, bound_row in zip(proposals, bound)
    ]
    assert classifications[0]["classification"] == "CORE", classifications[0]
    assert classifications[1]["classification"] == "SYNTHESIS", classifications[1]

    correlation_candidates = []
    for proposal, classification, bound_row in zip(proposals, classifications, bound):
        ledger = bound_row["groups"]["correlation_ledger"]
        assert ledger["strategy_id"] == proposal["strategy_id"]
        correlation_candidates.append({
            "strategy_id": proposal["strategy_id"],
            "candidate_sha": proposal["candidate_sha"],
            "proposal_sha": proposal["proposal_sha"],
            "classification_sha": classification["classification_sha"],
            "classification": classification["classification"],
            "trades": ledger["trades"],
        })
    correlation = analyze_candidates(correlation_candidates, CORRELATION_POLICY)
    assert correlation["compatible_combination_count"] >= 1, correlation
    selected = correlation["shadow_only_candidate_combinations"][0]

    materials = []
    for proposal, classification, bound_row in zip(proposals, classifications, bound):
        context = bound_row["groups"]["portfolio_policy"]["material_context"]
        materials.append({
            "material_id": f"material.{proposal['strategy_id']}",
            "classification": classification["classification"],
            "material_sealed": context["material_sealed"],
            "net_after_cost": context["net_after_cost"],
            "confidence": proposal["confidence"]["score"],
            "uncertainty": proposal["confidence"]["uncertainty"],
            "dd_pct": proposal["risk_envelope"]["max_drawdown_pct"],
            "joint_tail_dd_pct": context["joint_tail_dd_pct"],
            "cost_pct": context["cost_pct"],
            "capacity_score": context["capacity_score"],
            "incumbent_weight": context["incumbent_weight"],
        })
    governor = govern({
        "candidate_set_sha": selected["combination_sha"],
        "correlation_artifact_sha": correlation["analysis_sha"],
        "materials": materials,
        "policy": GOVERNOR_POLICY,
        **SAFETY,
    })
    assert governor["status"] == "PASS_PORTFOLIO_GOVERNOR_SHADOW_TARGETS", governor

    all_source_rows = []
    for proposal, bound_row in zip(proposals, bound):
        rows = bound_row["groups"]["source_ledger"]["trades"]
        assert all(row["candidate_sha"] == proposal["candidate_sha"] for row in rows)
        all_source_rows.extend(rows)
    attribution = build_projection({
        "projection_only": True,
        "source_ledger_mutated": False,
        "runtime_append_enabled": False,
        "trades": all_source_rows,
        **SAFETY,
    })
    assert attribution["status"] == "PASS_STRATEGY_ATTRIBUTION_LEDGER", attribution

    combined_rows_sha = canonical_sha([
        (row["source_ledger_id"], row["source_row_id"], row["source_row_sha"])
        for row in attribution["rows"]
    ])
    previous_head = FIXTURE_SHA("combined-previous-source-ledger-head")
    combined_history = {
        "previous_head_sha": previous_head,
        "rows_sha": combined_rows_sha,
        "sequence": 2,
        "current_head_sha": canonical_sha({
            "previous_head_sha": previous_head,
            "rows_sha": combined_rows_sha,
            "sequence": 2,
        }),
        "append_only_verified": True,
    }
    attribution_history = attribution_history_envelope(attribution, combined_history)
    assert attribution_history["source_history_verified"] is True

    validated_role_messages = []
    for bound_row in bound:
        lineage = bound_row["groups"]["role_lineage"]
        assert lineage["sbot_veto_active"] is False
        for message in bound_row["groups"]["role_messages"]["messages"]:
            validated_role_messages.append(validate_message(message))
    role_boundary_sha = canonical_sha({
        "manifest": role_manifest(),
        "messages": validated_role_messages,
    })

    model_risk_rows = []
    governor_sha = canonical_sha(governor)
    for proposal, classification, bound_row in zip(proposals, classifications, bound):
        baseline = bound_row["groups"]["model_risk_baseline"]
        snapshot = {
            "candidate_id": proposal["proposal_id"],
            "candidate_sha": proposal["candidate_sha"],
            "proposal_sha": proposal["proposal_sha"],
            "classification_sha": classification["classification_sha"],
            "correlation_analysis_sha": correlation["analysis_sha"],
            "portfolio_governor_sha": governor_sha,
            "attribution_projection_sha": attribution_history["history_envelope_sha"],
            "role_boundary_sha": role_boundary_sha,
            "source_manifest_sha": proposal["lineage"]["source_manifest_sha"],
            "lineage_match": True,
            "stale": False,
            "private_field_violation": False,
            **baseline,
            "authority": AUTHORITY,
        }
        result = evaluate_model_risk(snapshot, bound_row["groups"]["model_risk_policy"])
        assert result["state"] == "PASS_MODEL_RISK_GOVERNANCE", result
        model_risk_rows.append(result)

    stage_shas = {
        "source_binding": [row["binding_manifest_sha"] for row in bound],
        "proposal": [row["proposal_sha"] for row in proposals],
        "classification": [row["classification_sha"] for row in classifications],
        "correlation": correlation["analysis_sha"],
        "governor": governor_sha,
        "attribution": attribution_history["history_envelope_sha"],
        "role_boundary": role_boundary_sha,
        "model_risk": [row["governance_sha"] for row in model_risk_rows],
    }
    summary = {
        "schema_version": "strategy11.source_bound_chain_e2e.v1",
        "state": "PASS_SOURCE_BOUND_CHAIN_E2E_FIXTURE",
        "candidate_count": len(bound),
        "classification": {
            proposal["strategy_id"]: classification["classification"]
            for proposal, classification in zip(proposals, classifications)
        },
        "selected_combination": selected["members"],
        "target_risk_weights": governor["target_risk_weights"],
        "source_history_verified": attribution_history["source_history_verified"],
        "append_only_evidence": attribution_history["append_only_evidence"],
        "validated_role_message_count": len(validated_role_messages),
        "model_risk_states": [row["state"] for row in model_risk_rows],
        "bound_group_count": sum(row["bound_group_count"] for row in bound),
        "bound_field_count": sum(row["bound_field_count"] for row in bound),
        "negative_cases_passed": negative_cases,
        "stage_shas": stage_shas,
        "fixture_only": True,
        "production_threshold_authority": False,
        "real_w1_candidate_consumed": False,
        "next": "REAL_W1_EXACT_SHA_ADAPTER_THEN_SHADOW_20C_CANARY",
        "runtime_bound": False,
        **SAFETY,
    }
    summary["chain_sha"] = canonical_sha(summary)

    outputs = {
        "summary.json": summary,
        "alpha_bound.json": bound[0],
        "turtle_bound.json": bound[1],
        "classifications.json": classifications,
        "correlation.json": correlation,
        "governor.json": governor,
        "attribution.json": attribution,
        "attribution_history.json": attribution_history,
        "role_messages.json": validated_role_messages,
        "model_risk.json": model_risk_rows,
    }
    for name, value in outputs.items():
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], "fields=", summary["bound_field_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
