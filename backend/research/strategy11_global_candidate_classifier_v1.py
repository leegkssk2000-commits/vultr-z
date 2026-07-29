from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

from backend.contracts.strategy11_strategy_proposal_contract_v1 import validate_proposal

CLASSIFICATIONS = {"CORE", "SYNTHESIS", "REJECT", "HOLD"}
EVIDENCE_STATES = {"PASS", "HOLD", "FAIL", "NOT_RUN"}
REQUIRED_EVIDENCE = ("w1", "w2", "w3", "new_sealed")


class ClassifierError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ClassifierError(f"{code}:{detail}" if detail else code)


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    if minimum is not None and result < minimum:
        _fail("NUMBER_BELOW_MIN", name)
    if maximum is not None and result > maximum:
        _fail("NUMBER_ABOVE_MAX", name)
    return result


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("INT_REQUIRED", name)
    if value < minimum:
        _fail("INT_BELOW_MIN", name)
    return value


def _state(value: Any, name: str) -> str:
    if not isinstance(value, str):
        _fail("STRING_REQUIRED", name)
    result = value.strip().upper()
    if result not in EVIDENCE_STATES:
        _fail("EVIDENCE_STATE_INVALID", f"{name}={result}")
    return result


def canonical_sha(value: Mapping[str, Any]) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _dict(value, "policy")
    required = {
        "policy_id", "min_trades", "min_positive_window_ratio", "min_retention_pct",
        "min_profit_factor", "min_net_pct", "max_drawdown_pct", "min_worst_loss_r",
        "min_stress_worst_loss_r", "min_confidence_core", "max_uncertainty_core",
        "max_symbol_concentration_core_pct", "max_window_concentration_core_pct",
        "max_regime_concentration_core_pct", "max_concentration_synthesis_pct",
    }
    missing = sorted(required - set(policy))
    if missing:
        _fail("POLICY_MISSING_FIELDS", ",".join(missing))
    normalized = {
        "policy_id": str(policy["policy_id"]),
        "min_trades": _integer(policy["min_trades"], "policy.min_trades", 1),
        "min_positive_window_ratio": _number(policy["min_positive_window_ratio"], "policy.min_positive_window_ratio", 0.0, 1.0),
        "min_retention_pct": _number(policy["min_retention_pct"], "policy.min_retention_pct", 0.0, 100.0),
        "min_profit_factor": _number(policy["min_profit_factor"], "policy.min_profit_factor", 0.0),
        "min_net_pct": _number(policy["min_net_pct"], "policy.min_net_pct"),
        "max_drawdown_pct": _number(policy["max_drawdown_pct"], "policy.max_drawdown_pct", 0.0),
        "min_worst_loss_r": _number(policy["min_worst_loss_r"], "policy.min_worst_loss_r", maximum=0.0),
        "min_stress_worst_loss_r": _number(policy["min_stress_worst_loss_r"], "policy.min_stress_worst_loss_r", maximum=0.0),
        "min_confidence_core": _number(policy["min_confidence_core"], "policy.min_confidence_core", 0.0, 1.0),
        "max_uncertainty_core": _number(policy["max_uncertainty_core"], "policy.max_uncertainty_core", 0.0, 1.0),
        "max_symbol_concentration_core_pct": _number(policy["max_symbol_concentration_core_pct"], "policy.max_symbol_concentration_core_pct", 0.0, 100.0),
        "max_window_concentration_core_pct": _number(policy["max_window_concentration_core_pct"], "policy.max_window_concentration_core_pct", 0.0, 100.0),
        "max_regime_concentration_core_pct": _number(policy["max_regime_concentration_core_pct"], "policy.max_regime_concentration_core_pct", 0.0, 100.0),
        "max_concentration_synthesis_pct": _number(policy["max_concentration_synthesis_pct"], "policy.max_concentration_synthesis_pct", 0.0, 100.0),
    }
    core_caps = (
        normalized["max_symbol_concentration_core_pct"],
        normalized["max_window_concentration_core_pct"],
        normalized["max_regime_concentration_core_pct"],
    )
    if normalized["max_concentration_synthesis_pct"] < max(core_caps):
        _fail("SYNTHESIS_CAP_BELOW_CORE_CAP")
    return normalized


def validate_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _dict(value, "evidence")
    stages = _dict(evidence.get("stages"), "evidence.stages")
    normalized_stages = {name: _state(stages.get(name), f"evidence.stages.{name}") for name in REQUIRED_EVIDENCE}
    return {
        "stages": normalized_stages,
        "trade_quota_pass": _bool(evidence.get("trade_quota_pass"), "evidence.trade_quota_pass"),
        "regime_coverage_pass": _bool(evidence.get("regime_coverage_pass"), "evidence.regime_coverage_pass"),
        "dsr_pass": _bool(evidence.get("dsr_pass"), "evidence.dsr_pass"),
        "bh_fdr_pass": _bool(evidence.get("bh_fdr_pass"), "evidence.bh_fdr_pass"),
        "independent_edge_pass": _bool(evidence.get("independent_edge_pass"), "evidence.independent_edge_pass"),
        "synthesis_eligible": _bool(evidence.get("synthesis_eligible"), "evidence.synthesis_eligible"),
        "symbol_concentration_pct": _number(evidence.get("symbol_concentration_pct"), "evidence.symbol_concentration_pct", 0.0, 100.0),
        "window_concentration_pct": _number(evidence.get("window_concentration_pct"), "evidence.window_concentration_pct", 0.0, 100.0),
        "regime_concentration_pct": _number(evidence.get("regime_concentration_pct"), "evidence.regime_concentration_pct", 0.0, 100.0),
        "evidence_manifest_sha": str(evidence.get("evidence_manifest_sha", "")),
    }


def classify_candidate(proposal_value: Mapping[str, Any], evidence_value: Mapping[str, Any], policy_value: Mapping[str, Any]) -> dict[str, Any]:
    proposal = validate_proposal(proposal_value)
    evidence = validate_evidence(evidence_value)
    policy = validate_policy(policy_value)

    gates: dict[str, bool] = {}
    edge = proposal["edge"]
    risk = proposal["risk_envelope"]
    confidence = proposal["confidence"]

    gates["proposal_not_rejected"] = proposal["proposal_state"] != "REJECT"
    gates["economic_net"] = edge["net_pct"] >= policy["min_net_pct"]
    gates["economic_pf"] = edge["profit_factor"] >= policy["min_profit_factor"]
    gates["retention"] = edge["retention_pct"] >= policy["min_retention_pct"]
    gates["risk_dd"] = risk["max_drawdown_pct"] <= policy["max_drawdown_pct"]
    gates["risk_worst"] = risk["worst_loss_r"] >= policy["min_worst_loss_r"]
    gates["risk_stress_worst"] = risk["stress_worst_loss_r"] >= policy["min_stress_worst_loss_r"]
    gates["stat_dsr"] = evidence["dsr_pass"]
    gates["stat_bh_fdr"] = evidence["bh_fdr_pass"]

    hard_reject_gates = [
        "proposal_not_rejected", "economic_net", "economic_pf", "retention",
        "risk_dd", "risk_worst", "risk_stress_worst", "stat_dsr", "stat_bh_fdr",
    ]
    hard_reject = not all(gates[name] for name in hard_reject_gates)

    positive_ratio = edge["positive_windows"] / max(edge["total_windows"], 1)
    gates["trade_count"] = edge["trades"] >= policy["min_trades"] and evidence["trade_quota_pass"]
    gates["positive_windows"] = positive_ratio >= policy["min_positive_window_ratio"]
    gates["regime_coverage"] = evidence["regime_coverage_pass"]
    gates["all_nonoverlap_stages"] = all(evidence["stages"][name] == "PASS" for name in REQUIRED_EVIDENCE)
    evidence_ready = all(gates[name] for name in ("trade_count", "positive_windows", "regime_coverage", "all_nonoverlap_stages"))

    gates["core_confidence"] = confidence["score"] >= policy["min_confidence_core"]
    gates["core_uncertainty"] = confidence["uncertainty"] <= policy["max_uncertainty_core"]
    gates["core_symbol_concentration"] = evidence["symbol_concentration_pct"] <= policy["max_symbol_concentration_core_pct"]
    gates["core_window_concentration"] = evidence["window_concentration_pct"] <= policy["max_window_concentration_core_pct"]
    gates["core_regime_concentration"] = evidence["regime_concentration_pct"] <= policy["max_regime_concentration_core_pct"]
    core_ready = evidence_ready and evidence["independent_edge_pass"] and all(
        gates[name] for name in (
            "core_confidence", "core_uncertainty", "core_symbol_concentration",
            "core_window_concentration", "core_regime_concentration",
        )
    )

    max_concentration = max(
        evidence["symbol_concentration_pct"],
        evidence["window_concentration_pct"],
        evidence["regime_concentration_pct"],
    )
    gates["synthesis_concentration"] = max_concentration <= policy["max_concentration_synthesis_pct"]
    synthesis_ready = evidence_ready and evidence["synthesis_eligible"] and gates["synthesis_concentration"]

    if hard_reject:
        classification = "REJECT"
    elif not evidence_ready:
        classification = "HOLD"
    elif core_ready:
        classification = "CORE"
    elif synthesis_ready:
        classification = "SYNTHESIS"
    else:
        classification = "HOLD"

    failed = sorted(name for name, passed in gates.items() if not passed)
    result = {
        "schema_version": "strategy11.global_candidate_classification.v1",
        "strategy_id": proposal["strategy_id"],
        "candidate_sha": proposal["candidate_sha"],
        "proposal_sha": proposal["proposal_sha"],
        "classification": classification,
        "gate_results": gates,
        "failed_gates": failed,
        "reason_codes": [f"FAIL_{name.upper()}" for name in failed],
        "evidence": evidence,
        "policy": policy,
        "policy_sha": canonical_sha(policy),
        "pareto_first": True,
        "single_score_used": False,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    result["classification_sha"] = canonical_sha(result)
    if result["classification"] not in CLASSIFICATIONS:
        _fail("CLASSIFICATION_INVALID")
    return result
