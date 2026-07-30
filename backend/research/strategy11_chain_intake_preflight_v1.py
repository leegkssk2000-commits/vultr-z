from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

COMPONENT_PATHS = {
    "COMMON_STRATEGY_OUTPUT_CONTRACT": "backend/contracts/strategy11_strategy_proposal_contract_v1.py",
    "GLOBAL_CANDIDATE_CLASSIFIER": "backend/research/strategy11_global_candidate_classifier_v1.py",
    "ENSEMBLE_CORRELATION_ANALYZER": "backend/research/strategy11_ensemble_correlation_analyzer_v1.py",
    "PORTFOLIO_GOVERNOR": "backend/research/strategy11_portfolio_governor_v1.py",
    "STRATEGY_ATTRIBUTION_LEDGER": "backend/research/strategy11_attribution_ledger_v1.py",
    "ROLE_BOUNDARY_ZBOT_ZICO_LICO_ZLICE": "backend/contracts/strategy11_role_boundary_zbot_zico_lico_zlice_v1.py",
    "MODEL_RISK_GOVERNANCE": "backend/research/strategy11_model_risk_governance_v1.py",
}

W1_TERMINAL_STATES = {
    "PASS_W1_PRIMARY_CONFIRMATION",
    "W1_LOW_SAMPLE_HOLD",
    "W1_REJECT_RETAIN_INCUMBENT",
}

# These fields are required by the seven-layer chain but are not source-authoritative
# in the current alpha PRIMARY W1 summary contract. They must not be guessed.
REQUIRED_SOURCE_BINDINGS = {
    "proposal_market": [
        "market.symbols",
        "market.timeframe",
        "market.side",
        "market.regime",
        "market.session",
    ],
    "proposal_confidence": [
        "confidence.score",
        "confidence.uncertainty",
        "confidence.sample_quality",
        "confidence.oos_windows",
    ],
    "lico_cost_capacity": [
        "cost_envelope.fee_bps",
        "cost_envelope.slippage_bps",
        "cost_envelope.funding_8h_pct",
        "cost_envelope.latency_ms",
        "cost_envelope.capacity_notional_usdt",
    ],
    "portfolio_risk_context": [
        "risk_envelope.joint_tail_budget_pct",
        "risk_envelope.max_exposure_pct",
    ],
    "classifier_evidence": [
        "evidence.stages.w2",
        "evidence.stages.w3",
        "evidence.stages.new_sealed",
        "evidence.trade_quota_pass",
        "evidence.regime_coverage_pass",
        "evidence.dsr_pass",
        "evidence.bh_fdr_pass",
        "evidence.independent_edge_pass",
        "evidence.synthesis_eligible",
        "evidence.symbol_concentration_pct",
        "evidence.window_concentration_pct",
        "evidence.regime_concentration_pct",
        "evidence.evidence_manifest_sha",
    ],
    "correlation_ledger": [
        "per_material.timestamped_trade_series",
        "per_material.signal_vector",
        "per_material.pnl_series",
        "per_material.drawdown_series",
        "per_material.symbol_regime_exposure",
    ],
    "portfolio_policy_ssot": [
        "classifier.production_policy_sha",
        "correlation.production_policy_sha",
        "governor.total_risk_budget",
        "governor.min_material_weight",
        "governor.max_material_weight",
        "governor.max_turnover",
    ],
    "attribution_source_history": [
        "source_ledger.previous_head_sha",
        "source_ledger.current_head_sha",
        "source_ledger.hash_chain_verified",
    ],
    "role_lineage": [
        "lineage.method_id",
        "lineage.skill_id",
        "lineage.team_id",
        "lineage.advisor_contract_sha",
        "lineage.sbot_veto_state",
    ],
    "model_risk_baseline": [
        "model_risk.reference_distribution_sha",
        "model_risk.calibration_history_sha",
        "model_risk.error_budget_policy_sha",
        "model_risk.previous_verified_incumbent_sha",
    ],
}

PATCH_ORDER = [
    "W1_PROPOSAL_CONTEXT_ENVELOPE_ADAPTER",
    "W2_W3_NEW_SEALED_EVIDENCE_BINDING",
    "TIMESTAMPED_CORRELATION_LEDGER_ADAPTER",
    "PORTFOLIO_POLICY_SSOT_AND_RISK_BUDGET",
    "SOURCE_LEDGER_HISTORY_CHAIN_BINDING",
    "ROLE_LINEAGE_AND_SBOT_VETO_BINDING",
    "MODEL_RISK_REFERENCE_AND_ERROR_BUDGET_BINDING",
    "END_TO_END_SHADOW_CANARY_ORCHESTRATOR",
]


class IntakeError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntakeError("JSON_OBJECT_REQUIRED")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def component_inventory(repo_root: Path) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    missing: list[str] = []
    for capability, relative in COMPONENT_PATHS.items():
        path = repo_root / relative
        exists = path.is_file()
        if not exists:
            missing.append(capability)
        rows[capability] = {
            "path": relative,
            "exists": exists,
            "sha256": sha256_file(path) if exists else None,
        }
    return {
        "components": rows,
        "missing_components": missing,
        "all_seven_present": not missing,
    }


def validate_safety(payload: Mapping[str, Any]) -> None:
    if payload.get("promotion_authority") is not False:
        raise IntakeError("PROMOTION_AUTHORITY_FORBIDDEN")
    if payload.get("execution_allowed") is not False:
        raise IntakeError("EXECUTION_FORBIDDEN")
    if payload.get("order_authority") != "BLOCKED":
        raise IntakeError("ORDER_AUTHORITY_NOT_BLOCKED")
    if int(payload.get("protected_mutations", 0)) != 0:
        raise IntakeError("PROTECTED_MUTATION_FORBIDDEN")


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IntakeError(f"OBJECT_REQUIRED:{name}")
    return dict(value)


def require_nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"STRING_REQUIRED:{name}")
    return value.strip()


def available_variant_fields(variant: Mapping[str, Any]) -> dict[str, Any]:
    w1 = require_mapping(variant.get("W1"), "variant.W1")
    stress = require_mapping(variant.get("W1_stress_2x_p95_plus_one"), "variant.W1_stress_2x_p95_plus_one")
    cumulative = require_mapping(variant.get("cumulative_F1_F2_F3_W1"), "variant.cumulative_F1_F2_F3_W1")
    parity = require_mapping(variant.get("parity"), "variant.parity")
    gate = require_mapping(variant.get("W1_confirmation_gate"), "variant.W1_confirmation_gate")
    normal_loss = require_mapping(w1.get("loss_metrics"), "variant.W1.loss_metrics")
    stress_loss = require_mapping(stress.get("loss_metrics"), "variant.W1_stress.loss_metrics")
    if parity.get("state") != "PASS" or int(parity.get("duplicate_trade_count", -1)) != 0:
        raise IntakeError("W1_VARIANT_PARITY_OR_DUPLICATE_FAIL")
    if gate.get("pass") is not True:
        raise IntakeError("ACTIVE_VARIANT_GATE_NOT_PASS")
    return {
        "strategy_id": "alpha_combo",
        "candidate_sha": require_nonempty(variant.get("candidate_config_sha256"), "candidate_config_sha256"),
        "edge.trades": int(cumulative.get("trade_count") or 0),
        "edge.win_rate_pct": cumulative.get("win_rate_pct"),
        "edge.net_pct": cumulative.get("net_return_pct_sum"),
        "edge.profit_factor": cumulative.get("net_profit_factor"),
        "edge.payoff": cumulative.get("payoff_ratio"),
        "edge.positive_windows": int(cumulative.get("positive_windows") or 0),
        "edge.total_windows": 4,
        "edge.retention_pct": gate.get("trade_retention_pct"),
        "risk_envelope.max_drawdown_pct": cumulative.get("max_drawdown_pct"),
        "risk_envelope.avg_loss_r": cumulative.get("avg_loss_R"),
        "risk_envelope.worst_loss_r": normal_loss.get("normal_worst_net_loss_R"),
        "risk_envelope.stress_worst_loss_r": stress_loss.get("normal_worst_net_loss_R"),
        "lineage.candidate_config_sha": variant.get("candidate_config_sha256"),
        "lineage.strategy_source_sha": variant.get("strategy_source_sha256"),
        "lineage.source_w1_run_id": variant.get("source_w1_run_id"),
        "lineage.source_w1_head_sha": variant.get("source_w1_head_sha"),
        "lineage.source_w1_manifest_sha": variant.get("source_w1_manifest_sha256"),
        "w1.parity_sha_a": parity.get("replay_a_sha256"),
        "w1.parity_sha_b": parity.get("replay_b_sha256"),
    }


def flatten_bindings() -> list[str]:
    return sorted(field for fields in REQUIRED_SOURCE_BINDINGS.values() for field in fields)


def audit(payload: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    inventory = component_inventory(repo_root)
    if not inventory["all_seven_present"]:
        raise IntakeError("SEVEN_LAYER_COMPONENT_MISSING:" + ",".join(inventory["missing_components"]))

    state = str(payload.get("state", "")).strip()
    validate_safety(payload)

    base = {
        "schema_version": "strategy11.chain_intake_preflight.v1",
        "source_state": state,
        "source_sha": sha256_value(payload),
        "component_inventory": inventory,
        "proposal_created": False,
        "classification_created": False,
        "correlation_material_created": False,
        "target_weights_created": False,
        "attribution_projection_created": False,
        "runtime_bound": False,
        "shadow_only": True,
        **SAFETY,
    }

    if state == "WAIT_DATA":
        return {
            **base,
            "status": "PASS_CHAIN_INTAKE_WAIT_DATA",
            "available_non_overlap_bars": int(payload.get("available_non_overlap_bars") or 0),
            "missing_bars": int(payload.get("missing_bars") or 0),
            "next_eligible_window_end": payload.get("next_eligible_window_end"),
            "candidate_count": 0,
            "available_source_fields": {},
            "missing_source_bindings": flatten_bindings(),
            "missing_binding_groups": sorted(REQUIRED_SOURCE_BINDINGS),
            "next_patch": PATCH_ORDER[0],
            "patch_order": PATCH_ORDER,
            "decision": "WAIT_DATA",
        }

    if state not in W1_TERMINAL_STATES:
        raise IntakeError(f"W1_STATE_UNSUPPORTED:{state}")

    active_ids = payload.get("active_candidate_queue")
    variants = payload.get("variants")
    if not isinstance(active_ids, list) or not isinstance(variants, list):
        raise IntakeError("W1_ACTIVE_QUEUE_OR_VARIANTS_MISSING")
    by_id = {str(row.get("variant_id")): row for row in variants if isinstance(row, Mapping)}

    if state != "PASS_W1_PRIMARY_CONFIRMATION":
        return {
            **base,
            "status": "HOLD_CHAIN_INTAKE_NO_W1_SURVIVOR",
            "candidate_count": 0,
            "active_candidate_ids": [],
            "available_source_fields": {},
            "missing_source_bindings": flatten_bindings(),
            "missing_binding_groups": sorted(REQUIRED_SOURCE_BINDINGS),
            "next_patch": "RETAIN_INCUMBENT_OR_COLLECT_NEXT_NON_OVERLAP",
            "patch_order": PATCH_ORDER,
            "decision": "HOLD",
        }

    if not active_ids:
        raise IntakeError("PASS_W1_WITH_EMPTY_ACTIVE_QUEUE")

    available: dict[str, Any] = {}
    for candidate_id in active_ids:
        key = str(candidate_id)
        if key not in by_id:
            raise IntakeError(f"ACTIVE_VARIANT_MISSING:{key}")
        available[key] = available_variant_fields(by_id[key])

    return {
        **base,
        "status": "HOLD_CHAIN_INTAKE_MISSING_SOURCED_FIELDS",
        "candidate_count": len(available),
        "active_candidate_ids": sorted(available),
        "available_source_fields": available,
        "missing_source_bindings": flatten_bindings(),
        "missing_binding_groups": sorted(REQUIRED_SOURCE_BINDINGS),
        "next_patch": PATCH_ORDER[0],
        "patch_order": PATCH_ORDER,
        "decision": "HOLD",
        "reason": "Seven capabilities exist, but real W1 candidates cannot enter the common proposal/classifier chain until every required context, cost, risk, evidence and lineage field has an explicit source authority.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        result = audit(read_json(args.input), args.repo_root.resolve())
        write_json(args.output, result)
        print(result["status"])
        return 0
    except Exception as exc:
        result = {
            "schema_version": "strategy11.chain_intake_preflight.v1",
            "status": "BLOCK_CHAIN_INTAKE_PREFLIGHT",
            "blockers": [str(exc)[:1000]],
            "proposal_created": False,
            "classification_created": False,
            "correlation_material_created": False,
            "target_weights_created": False,
            "attribution_projection_created": False,
            "runtime_bound": False,
            "shadow_only": True,
            **SAFETY,
        }
        write_json(args.output, result)
        print(result["status"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
