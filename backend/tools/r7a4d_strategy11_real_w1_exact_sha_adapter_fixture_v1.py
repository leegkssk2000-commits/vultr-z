from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_real_w1_exact_sha_adapter_v1 import (
    ADAPTER_INPUT_SCHEMA,
    RealW1AdapterError,
    adapt,
)
from backend.tools.r7a4d_strategy11_source_bound_chain_fixture_v1 import (
    CLASSIFIER_POLICY,
    CORRELATION_POLICY,
    GOVERNOR_POLICY,
    MODEL_RISK_POLICY,
    role_bundle,
    source,
    source_row,
)

OUT = Path("artifacts/strategy11_real_w1_exact_sha_adapter_v1")
AUTHORITY = {**SAFETY, "runtime_bound": False}


def fixture_sha(token: str) -> str:
    return canonical_sha({"fixture": token})


def wait_input() -> dict[str, Any]:
    status = {
        "state": "WAIT_DATA",
        "blockers": [],
        "available_non_overlap_bars": 43,
        "missing_bars": 437,
        "next_eligible_window_end": "2026-08-01T08:30:00Z",
    }
    return {
        "schema_version": ADAPTER_INPUT_SCHEMA,
        "candidate_id": "TIME54",
        "source_status": source("W1_SOURCE_STATUS", "s11-data-wait-pool-compute-v1-wait", "30299513066", status),
        "primary_summary": source("PRIMARY_W1_SUMMARY", "unused-primary-wait", "30299513066", {"state": "WAIT_DATA"}),
        "context_sources": {},
        "authority": AUTHORITY,
    }


def pass_sources(*, full_oos: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    run_id = "40000000001"
    manifest_sha = fixture_sha("real-w1-manifest")
    status_document = {
        "state": "PASS",
        "blockers": [],
        "W1_manifest_sha256": manifest_sha,
        "available_non_overlap_bars": 480,
        "missing_bars": 0,
        "next_eligible_window_end": "2026-08-01T08:30:00Z",
    }
    primary_document = {
        "state": "PASS_W1_PRIMARY_CONFIRMATION",
        "blockers": [],
        "strategy_id": "alpha_combo",
        "source_w1_run_id": run_id,
        "source_w1_head_sha": fixture_sha("primary-head"),
        "source_w1_manifest_sha256": manifest_sha,
        "active_candidate_queue": ["TIME54"],
        "variants": [
            {
                "variant_id": "TIME54",
                "candidate_config_sha256": fixture_sha("candidate:TIME54"),
                "source_w1_manifest_sha256": manifest_sha,
                "W1": {
                    "trade_count": 16,
                    "win_rate_pct": 56.25,
                    "net_return_pct_sum": 5.4,
                    "net_profit_factor": 2.1,
                    "payoff_ratio": 1.9,
                    "max_drawdown_pct": 1.8,
                    "loss_metrics": {
                        "normal_worst_net_loss_R": -0.62,
                        "avg_loss_R": -0.34,
                    },
                },
                "W1_stress_2x_p95_plus_one": {
                    "trade_count": 16,
                    "net_return_pct_sum": 3.7,
                    "net_profit_factor": 1.6,
                    "payoff_ratio": 1.5,
                    "max_drawdown_pct": 2.3,
                    "loss_metrics": {
                        "normal_worst_net_loss_R": -0.72,
                        "avg_loss_R": -0.40,
                    },
                },
                "cumulative_F1_F2_F3_W1": {
                    "trade_count": 56,
                    "win_rate_pct": 57.14,
                    "net_return_pct_sum": 26.4,
                    "net_profit_factor": 3.9,
                    "payoff_ratio": 2.85,
                    "max_drawdown_pct": 3.3,
                    "avg_loss_R": -0.32,
                    "worst_net_loss_R": -0.62,
                    "positive_windows": 4,
                },
                "W1_confirmation_gate": {
                    "pass": True,
                    "trade_retention_pct": 94.0,
                },
            }
        ],
    }
    source_status = source("W1_SOURCE_STATUS", "s11-data-wait-pool-compute-v1-pass", run_id, status_document, "DIRECT_ARTIFACT")
    primary_summary = source("PRIMARY_W1_SUMMARY", "s11-alpha-primary-w1-pass", run_id, primary_document, "DIRECT_ARTIFACT")

    proposal_context = {
        "producer": {"team_lane": "ALPHA", "role": "RESEARCH", "independent_proposal": True},
        "market": {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"],
            "timeframe": "15m",
            "side": "LONG",
            "regime": "MIXED",
            "session": "ALL",
        },
        "confidence": {
            "score": 0.78,
            "uncertainty": 0.22,
            "sample_quality": "HIGH",
            "oos_windows": 1 if not full_oos else 4,
        },
        "cost_envelope": {
            "fee_bps": 2.0,
            "slippage_bps": 1.5,
            "funding_8h_pct": 0.01,
            "latency_ms": 250.0,
            "stress_multiplier": 2.0,
            "capacity_notional_usdt": 25000.0,
        },
        "risk_context": {
            "joint_tail_budget_pct": 2.0,
            "max_exposure_pct": 20.0,
        },
        "lineage": {
            "strategy_source_sha": fixture_sha("alpha-strategy-source"),
            "data_sha": fixture_sha("shared-w1-data"),
            "window_sha": fixture_sha("shared-w1-window"),
            "data_epoch": "F1_F2_F3_W1_EXACT_SHA",
        },
        "reason_codes": ["EXACT_SHA_W1_SOURCE_ADAPTER"],
        "metadata": {
            "real_w1_adapter_fixture": True,
            "production_threshold_authority": False,
        },
    }
    stages = {
        "w1": "PASS",
        "w2": "PASS" if full_oos else "NOT_RUN",
        "w3": "PASS" if full_oos else "NOT_RUN",
        "new_sealed": "PASS" if full_oos else "NOT_RUN",
    }
    classifier_evidence = {
        "stages": stages,
        "trade_quota_pass": True,
        "regime_coverage_pass": full_oos,
        "dsr_pass": True,
        "bh_fdr_pass": True,
        "independent_edge_pass": True,
        "synthesis_eligible": False,
        "symbol_concentration_pct": 45.0,
        "window_concentration_pct": 40.0 if full_oos else 100.0,
        "regime_concentration_pct": 55.0,
        "evidence_manifest_sha": fixture_sha(f"evidence:{'full' if full_oos else 'w1-only'}"),
    }
    correlation = {
        "strategy_id": "alpha_combo",
        "trades": [
            {"timestamp": "2026-08-01T09:00:00Z", "net_r": 0.8, "symbol": "BTCUSDT", "regime": "UPTREND"},
            {"timestamp": "2026-08-01T11:00:00Z", "net_r": -0.2, "symbol": "ETHUSDT", "regime": "RANGE"},
            {"timestamp": "2026-08-01T13:00:00Z", "net_r": 0.6, "symbol": "SOLUSDT", "regime": "HIGH_VOL"},
        ],
    }
    rows = [
        source_row(
            strategy_id="alpha_combo",
            material_id="material.alpha_combo.TIME54",
            team="ALPHA",
            candidate_sha=fixture_sha("candidate:TIME54"),
            ordinal=index,
            gross_pnl_r=value,
        )
        for index, value in enumerate([0.8, -0.2, 0.6])
    ]
    rows_sha = canonical_sha([
        (row["source_ledger_id"], row["source_row_id"], row["source_row_sha"])
        for row in rows
    ])
    previous_head = fixture_sha("alpha-ledger-previous")
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
    lineage, messages = role_bundle("alpha_combo", manifest_sha)
    portfolio_policy = {
        "classifier": CLASSIFIER_POLICY,
        "correlation": CORRELATION_POLICY,
        "governor": GOVERNOR_POLICY,
        "material_context": {
            "net_after_cost": 26.4,
            "joint_tail_dd_pct": 2.0,
            "cost_pct": 0.5,
            "capacity_score": 0.9,
            "incumbent_weight": 1.0,
            "material_sealed": full_oos,
            "material_seal_scope": "FULL_OOS_FIXTURE" if full_oos else "NOT_AVAILABLE",
        },
    }
    model_baseline = {
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
    context_sources = {
        "proposal_context": source("W1_PROPOSAL_CONTEXT", "s11-w1-proposal-context", run_id, proposal_context, "DETERMINISTIC_ADAPTER"),
        "classifier_evidence": source("OOS_EVIDENCE_MANIFEST", f"s11-evidence-{'full' if full_oos else 'w1-only'}", run_id, classifier_evidence, "DIRECT_ARTIFACT"),
        "correlation_ledger": source("TIMESTAMPED_TRADE_LEDGER", "s11-alpha-timestamped-ledger", run_id, correlation, "DIRECT_ARTIFACT"),
        "portfolio_policy": source("PORTFOLIO_POLICY_SSOT", "s11-portfolio-policy-fixture", "policy-fixture", portfolio_policy, "FIXTURE_ONLY"),
        "source_ledger": source("SOURCE_LEDGER", "s11-alpha-source-ledger", run_id, {"trades": rows}, "DIRECT_ARTIFACT"),
        "source_history": source("SOURCE_LEDGER_HISTORY", "s11-alpha-source-history", run_id, history, "DIRECT_ARTIFACT"),
        "role_lineage": source("ROLE_LINEAGE_SSOT", "s11-alpha-role-lineage", run_id, lineage, "DIRECT_ARTIFACT"),
        "role_messages": source("ROLE_MESSAGE_BUNDLE", "s11-alpha-role-messages", run_id, messages, "DIRECT_ARTIFACT"),
        "model_risk_baseline": source("SHADOW_MODEL_RISK_BASELINE", "s11-alpha-model-risk-baseline", run_id, model_baseline, "DIRECT_ARTIFACT"),
        "model_risk_policy": source("MODEL_RISK_POLICY_SSOT", "s11-model-risk-policy-fixture", "policy-fixture", MODEL_RISK_POLICY, "FIXTURE_ONLY"),
    }
    return source_status, primary_summary, context_sources


def pass_input(*, full_oos: bool) -> dict[str, Any]:
    source_status, primary_summary, context_sources = pass_sources(full_oos=full_oos)
    return {
        "schema_version": ADAPTER_INPUT_SCHEMA,
        "candidate_id": "TIME54",
        "source_status": source_status,
        "primary_summary": primary_summary,
        "context_sources": context_sources,
        "authority": AUTHORITY,
    }


def assert_negative_cases(payload: dict[str, Any]) -> list[str]:
    passed: list[str] = []

    manifest = copy.deepcopy(payload)
    manifest["primary_summary"]["document"]["source_w1_manifest_sha256"] = fixture_sha("wrong-manifest")
    manifest["primary_summary"]["artifact_sha"] = canonical_sha(manifest["primary_summary"]["document"])
    try:
        adapt(manifest)
    except RealW1AdapterError as exc:
        assert str(exc) == "SHARED_W1_MANIFEST_SHA_MISMATCH", exc
        passed.append("MANIFEST_SHA_MISMATCH")
    else:
        raise AssertionError("manifest mismatch accepted")

    inactive = copy.deepcopy(payload)
    inactive["candidate_id"] = "TIME60"
    try:
        adapt(inactive)
    except RealW1AdapterError as exc:
        assert str(exc).startswith("CANDIDATE_NOT_ACTIVE"), exc
        passed.append("INACTIVE_CANDIDATE")
    else:
        raise AssertionError("inactive candidate accepted")

    tampered = copy.deepcopy(payload)
    tampered["context_sources"]["proposal_context"]["document"]["confidence"]["score"] = 0.99
    try:
        adapt(tampered)
    except RealW1AdapterError as exc:
        assert str(exc).startswith("SOURCE_ARTIFACT_SHA_MISMATCH"), exc
        passed.append("CONTEXT_SHA_TAMPER")
    else:
        raise AssertionError("context tamper accepted")

    run_mismatch = copy.deepcopy(payload)
    run_mismatch["primary_summary"]["document"]["source_w1_run_id"] = "40000000002"
    run_mismatch["primary_summary"]["artifact_sha"] = canonical_sha(run_mismatch["primary_summary"]["document"])
    try:
        adapt(run_mismatch)
    except RealW1AdapterError as exc:
        assert str(exc) == "SHARED_W1_RUN_ID_MISMATCH", exc
        passed.append("RUN_ID_MISMATCH")
    else:
        raise AssertionError("run mismatch accepted")

    return passed


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    wait = adapt(wait_input())
    assert wait["state"] == "PASS_REAL_W1_EXACT_SHA_ADAPTER_WAIT_DATA", wait
    assert wait["available_non_overlap_bars"] == 43
    assert wait["missing_bars"] == 437
    assert wait["proposal_created"] is False

    w1_only_input = pass_input(full_oos=False)
    negative_cases = assert_negative_cases(w1_only_input)
    w1_only = adapt(w1_only_input)
    assert w1_only["state"] == "PASS_REAL_W1_EXACT_SHA_SOURCE_BINDING", w1_only
    assert w1_only["all_values_source_bound"] is True
    w1_proposal = seal_proposal(w1_only["bound_package"]["groups"]["proposal_core"])
    w1_evidence = w1_only["bound_package"]["groups"]["classifier_evidence"]
    w1_policy = w1_only["bound_package"]["groups"]["portfolio_policy"]["classifier"]
    w1_classification = classify_candidate(w1_proposal, w1_evidence, w1_policy)
    assert w1_classification["classification"] == "HOLD", w1_classification
    assert "all_nonoverlap_stages" in w1_classification["failed_gates"]
    assert "regime_coverage" in w1_classification["failed_gates"]

    full_input = pass_input(full_oos=True)
    full = adapt(full_input)
    assert full["state"] == "PASS_REAL_W1_EXACT_SHA_SOURCE_BINDING", full
    full_proposal = seal_proposal(full["bound_package"]["groups"]["proposal_core"])
    full_evidence = full["bound_package"]["groups"]["classifier_evidence"]
    full_policy = full["bound_package"]["groups"]["portfolio_policy"]["classifier"]
    full_classification = classify_candidate(full_proposal, full_evidence, full_policy)
    assert full_classification["classification"] == "CORE", full_classification

    summary = {
        "schema_version": "strategy11.real_w1_exact_sha_adapter_fixture.v1",
        "state": "PASS_REAL_W1_EXACT_SHA_ADAPTER_FIXTURES",
        "wait_state": wait["state"],
        "wait_bars": f"{wait['available_non_overlap_bars']}/480",
        "w1_only_adapter_state": w1_only["state"],
        "w1_only_classification": w1_classification["classification"],
        "w1_only_failed_gates": w1_classification["failed_gates"],
        "full_evidence_adapter_state": full["state"],
        "full_evidence_classification": full_classification["classification"],
        "shared_w1_manifest_sha": full["source_w1_manifest_sha"],
        "bound_group_count": full["bound_package"]["bound_group_count"],
        "bound_field_count": full["bound_package"]["bound_field_count"],
        "negative_cases_passed": negative_cases,
        "w1_performance_promoted": False,
        "fixture_only": True,
        "production_threshold_authority": False,
        "next": "W2_W3_NEW_SEALED_REAL_ARTIFACT_BINDING_THEN_MULTI_CANDIDATE_CHAIN",
        "runtime_bound": False,
        **SAFETY,
    }
    summary["fixture_sha"] = canonical_sha(summary)

    outputs = {
        "summary.json": summary,
        "wait.json": wait,
        "w1_only_adapter.json": w1_only,
        "w1_only_classification.json": w1_classification,
        "full_adapter.json": full,
        "full_classification.json": full_classification,
    }
    for name, row in outputs.items():
        (OUT / name).write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], summary["w1_only_classification"], "->", summary["full_evidence_classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
