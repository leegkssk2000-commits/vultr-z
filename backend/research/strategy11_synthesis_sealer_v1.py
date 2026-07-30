from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.research.strategy11_component_attribution_v1 import attribute_components
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha
from backend.contracts.strategy11_validation_primitives_v1 import ValidationPrimitives

INPUT_SCHEMA = "strategy11.synthesis_sealer.input.v1"
OUTPUT_SCHEMA = "strategy11.synthesis_sealer.output.v1"
RECEIPT_SCHEMA = "strategy11.synthesis_confirmation_receipt.v1"
REQUIRED_STAGES = {"W3", "NEW_SEALED"}


class SynthesisSealerError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SynthesisSealerError(f"{code}:{detail}" if detail else code)

_validation = ValidationPrimitives(_fail)
_mapping = _validation.mapping
_string = _validation.string
_sha = _validation.sha256
_bool = _validation.boolean
_integer = _validation.integer
_number = _validation.number









def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(value, "policy")
    required = {
        "policy_id", "min_trades", "min_profit_factor", "min_payoff",
        "min_net_after_cost_r", "max_drawdown_r", "min_avg_loss_r",
        "min_worst_loss_r", "min_stress_worst_loss_r", "min_positive_windows",
        "min_net_retention_vs_w2_pct", "max_drawdown_expansion_vs_w2_pct",
        "require_ab_parity", "require_duplicate_zero",
    }
    missing = sorted(required - set(policy))
    extra = sorted(set(policy) - required)
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("POLICY_EXTRA_FIELDS", ",".join(extra))
    return {
        "policy_id": _string(policy["policy_id"], "policy.policy_id"),
        "min_trades": _integer(policy["min_trades"], "policy.min_trades", minimum=1),
        "min_profit_factor": _number(policy["min_profit_factor"], "policy.min_profit_factor", minimum=0.0),
        "min_payoff": _number(policy["min_payoff"], "policy.min_payoff", minimum=0.0),
        "min_net_after_cost_r": _number(policy["min_net_after_cost_r"], "policy.min_net_after_cost_r"),
        "max_drawdown_r": _number(policy["max_drawdown_r"], "policy.max_drawdown_r", minimum=0.0),
        "min_avg_loss_r": _number(policy["min_avg_loss_r"], "policy.min_avg_loss_r", maximum=0.0),
        "min_worst_loss_r": _number(policy["min_worst_loss_r"], "policy.min_worst_loss_r", maximum=0.0),
        "min_stress_worst_loss_r": _number(policy["min_stress_worst_loss_r"], "policy.min_stress_worst_loss_r", maximum=0.0),
        "min_positive_windows": _integer(policy["min_positive_windows"], "policy.min_positive_windows", minimum=1),
        "min_net_retention_vs_w2_pct": _number(
            policy["min_net_retention_vs_w2_pct"],
            "policy.min_net_retention_vs_w2_pct",
            minimum=0.0,
            maximum=200.0,
        ),
        "max_drawdown_expansion_vs_w2_pct": _number(
            policy["max_drawdown_expansion_vs_w2_pct"],
            "policy.max_drawdown_expansion_vs_w2_pct",
            minimum=0.0,
            maximum=500.0,
        ),
        "require_ab_parity": _bool(policy["require_ab_parity"], "policy.require_ab_parity"),
        "require_duplicate_zero": _bool(policy["require_duplicate_zero"], "policy.require_duplicate_zero"),
    }


def _metrics(value: Any, stage: str) -> dict[str, Any]:
    metrics = _mapping(value, f"{stage}.metrics")
    required = {
        "trades", "net_after_cost_r", "profit_factor", "payoff", "max_drawdown_r",
        "avg_loss_r", "worst_loss_r", "stress_worst_loss_r", "positive_windows", "total_windows",
    }
    missing = sorted(required - set(metrics))
    extra = sorted(set(metrics) - required)
    if missing:
        _fail("METRIC_FIELDS_MISSING", f"{stage}:{','.join(missing)}")
    if extra:
        _fail("METRIC_EXTRA_FIELDS", f"{stage}:{','.join(extra)}")
    result = {
        "trades": _integer(metrics["trades"], f"{stage}.trades", minimum=1),
        "net_after_cost_r": _number(metrics["net_after_cost_r"], f"{stage}.net_after_cost_r"),
        "profit_factor": _number(metrics["profit_factor"], f"{stage}.profit_factor", minimum=0.0),
        "payoff": _number(metrics["payoff"], f"{stage}.payoff", minimum=0.0),
        "max_drawdown_r": _number(metrics["max_drawdown_r"], f"{stage}.max_drawdown_r", minimum=0.0),
        "avg_loss_r": _number(metrics["avg_loss_r"], f"{stage}.avg_loss_r", maximum=0.0),
        "worst_loss_r": _number(metrics["worst_loss_r"], f"{stage}.worst_loss_r", maximum=0.0),
        "stress_worst_loss_r": _number(metrics["stress_worst_loss_r"], f"{stage}.stress_worst_loss_r", maximum=0.0),
        "positive_windows": _integer(metrics["positive_windows"], f"{stage}.positive_windows"),
        "total_windows": _integer(metrics["total_windows"], f"{stage}.total_windows", minimum=1),
    }
    if result["positive_windows"] > result["total_windows"]:
        _fail("POSITIVE_WINDOWS_EXCEED_TOTAL", stage)
    return result


def validate_receipt(value: Mapping[str, Any], candidate_id: str, candidate_sha: str) -> dict[str, Any]:
    receipt = _mapping(value, "confirmation_receipt")
    supplied_sha = _sha(receipt.get("receipt_sha"), "receipt.receipt_sha")
    raw = copy.deepcopy(receipt)
    raw.pop("receipt_sha", None)
    if canonical_sha(raw) != supplied_sha:
        _fail("RECEIPT_SHA_MISMATCH", str(receipt.get("stage")))
    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        _fail("RECEIPT_SCHEMA_MISMATCH")
    stage = _string(receipt.get("stage"), "receipt.stage").upper()
    if stage not in REQUIRED_STAGES:
        _fail("RECEIPT_STAGE_INVALID", stage)
    if receipt.get("candidate_id") != candidate_id:
        _fail("RECEIPT_CANDIDATE_ID_MISMATCH", stage)
    if receipt.get("candidate_sha") != candidate_sha:
        _fail("RECEIPT_CANDIDATE_SHA_MISMATCH", stage)
    if receipt.get("config_sha") != candidate_sha:
        _fail("RECEIPT_CONFIG_SHA_MISMATCH", stage)
    lineage = _mapping(receipt.get("lineage"), f"{stage}.lineage")
    normalized = {
        "schema_version": RECEIPT_SCHEMA,
        "stage": stage,
        "candidate_id": candidate_id,
        "candidate_sha": candidate_sha,
        "config_sha": candidate_sha,
        "lineage": {
            "data_sha": _sha(lineage.get("data_sha"), f"{stage}.lineage.data_sha"),
            "window_sha": _sha(lineage.get("window_sha"), f"{stage}.lineage.window_sha"),
            "source_manifest_sha": _sha(lineage.get("source_manifest_sha"), f"{stage}.lineage.source_manifest_sha"),
            "replay_run_id": _string(lineage.get("replay_run_id"), f"{stage}.lineage.replay_run_id"),
        },
        "ab_parity_pass": _bool(receipt.get("ab_parity_pass"), f"{stage}.ab_parity_pass"),
        "duplicate_count": _integer(receipt.get("duplicate_count"), f"{stage}.duplicate_count"),
        "metrics": _metrics(receipt.get("metrics"), stage),
        "authority": copy.deepcopy(receipt.get("authority")),
    }
    if normalized["authority"] != SAFETY:
        _fail("RECEIPT_AUTHORITY_MISMATCH", stage)
    normalized["receipt_sha"] = canonical_sha(normalized)
    if normalized["receipt_sha"] != supplied_sha:
        _fail("RECEIPT_NORMALIZED_SHA_MISMATCH", stage)
    return normalized


def _receipt_blockers(
    receipt: Mapping[str, Any],
    policy: Mapping[str, Any],
    w2_net: float,
    w2_dd: float,
) -> tuple[list[str], dict[str, float]]:
    stage = receipt["stage"]
    metrics = receipt["metrics"]
    blockers: list[str] = []
    if policy["require_ab_parity"] and not receipt["ab_parity_pass"]:
        blockers.append("AB_PARITY_REQUIRED")
    if policy["require_duplicate_zero"] and receipt["duplicate_count"] != 0:
        blockers.append("DUPLICATE_ZERO_REQUIRED")
    if metrics["trades"] < policy["min_trades"]:
        blockers.append("TRADES_LOW")
    if metrics["profit_factor"] < policy["min_profit_factor"]:
        blockers.append("PF_LOW")
    if metrics["payoff"] < policy["min_payoff"]:
        blockers.append("PAYOFF_LOW")
    if metrics["net_after_cost_r"] < policy["min_net_after_cost_r"]:
        blockers.append("NET_LOW")
    if metrics["max_drawdown_r"] > policy["max_drawdown_r"]:
        blockers.append("DD_HIGH")
    if metrics["avg_loss_r"] < policy["min_avg_loss_r"]:
        blockers.append("AVG_LOSS_BREACH")
    if metrics["worst_loss_r"] < policy["min_worst_loss_r"]:
        blockers.append("WORST_LOSS_BREACH")
    if metrics["stress_worst_loss_r"] < policy["min_stress_worst_loss_r"]:
        blockers.append("STRESS_LOSS_BREACH")
    if metrics["positive_windows"] < policy["min_positive_windows"]:
        blockers.append("WINDOW_BREADTH_LOW")
    net_retention = metrics["net_after_cost_r"] / w2_net * 100.0 if w2_net > 0 else 0.0
    dd_expansion = (metrics["max_drawdown_r"] / w2_dd - 1.0) * 100.0 if w2_dd > 0 else 0.0
    if net_retention < policy["min_net_retention_vs_w2_pct"]:
        blockers.append("W2_NET_RETENTION_LOW")
    if dd_expansion > policy["max_drawdown_expansion_vs_w2_pct"]:
        blockers.append("W2_DD_EXPANSION_HIGH")
    return [f"{stage}:{code}" for code in blockers], {
        "net_retention_vs_w2_pct": net_retention,
        "drawdown_expansion_vs_w2_pct": dd_expansion,
    }


def seal_synthesis(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "sealer_input")
    allowed = {"schema_version", "attribution_input", "attribution_result", "confirmations", "policy", "authority"}
    missing = sorted(allowed - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing:
        _fail("INPUT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("INPUT_EXTRA_FIELDS", ",".join(extra))
    if payload.get("schema_version") != INPUT_SCHEMA:
        _fail("INPUT_SCHEMA_MISMATCH")
    if payload.get("authority") != SAFETY:
        _fail("INPUT_AUTHORITY_MISMATCH")

    attribution_input = _mapping(payload["attribution_input"], "attribution_input")
    reproduced_attribution = attribute_components(attribution_input)
    supplied_attribution = _mapping(payload["attribution_result"], "attribution_result")
    if supplied_attribution.get("attribution_sha") != reproduced_attribution.get("attribution_sha"):
        _fail("ATTRIBUTION_SHA_MISMATCH")
    if supplied_attribution != reproduced_attribution:
        _fail("ATTRIBUTION_RECONCILIATION_MISMATCH")
    if reproduced_attribution["state"] != "PASS_COMPONENT_ATTRIBUTION":
        _fail("PASS_ATTRIBUTION_REQUIRED")

    factorial_input = _mapping(attribution_input.get("factorial_input"), "factorial_input")
    candidate = _mapping(factorial_input.get("candidate"), "candidate")
    candidate_id = _string(candidate.get("candidate_id"), "candidate.candidate_id")
    candidate_sha = _sha(candidate.get("candidate_sha"), "candidate.candidate_sha")
    policy = validate_policy(payload["policy"])
    confirmations = payload.get("confirmations")
    if not isinstance(confirmations, list) or len(confirmations) != 2:
        _fail("EXACT_TWO_CONFIRMATIONS_REQUIRED")
    receipts: dict[str, dict[str, Any]] = {}
    for raw in confirmations:
        if not isinstance(raw, Mapping):
            _fail("CONFIRMATION_OBJECT_REQUIRED")
        receipt = validate_receipt(raw, candidate_id, candidate_sha)
        if receipt["stage"] in receipts:
            _fail("DUPLICATE_CONFIRMATION_STAGE", receipt["stage"])
        receipts[receipt["stage"]] = receipt
    if set(receipts) != REQUIRED_STAGES:
        _fail("CONFIRMATION_STAGE_COVERAGE_MISMATCH")

    factorial_result = _mapping(attribution_input.get("factorial_result"), "factorial_result")
    if factorial_result.get("state") != "PASS_SYNTHESIS_FACTORIAL_W2_CANDIDATE":
        _fail("PASS_W2_FACTORIAL_REQUIRED")
    w2_lineage = _mapping(factorial_result.get("evaluation_lineage"), "w2_lineage")
    selection_lineage = _mapping(candidate.get("selection_lineage"), "selection_lineage")
    lineages = {
        "SELECTION": selection_lineage,
        "W2": w2_lineage,
        "W3": receipts["W3"]["lineage"],
        "NEW_SEALED": receipts["NEW_SEALED"]["lineage"],
    }
    for field in ("data_sha", "window_sha"):
        values = [row.get(field) for row in lineages.values()]
        if any(not isinstance(item, str) for item in values):
            _fail("LINEAGE_FIELD_MISSING", field)
        if len(values) != len(set(values)):
            _fail("STAGE_LINEAGE_OVERLAP", field)

    w2_ab = next(
        row for row in factorial_input["cells"]
        if isinstance(row, Mapping) and row.get("cell_id") == "BASE_AB"
    )
    w2_metrics = _mapping(w2_ab.get("metrics"), "w2_ab.metrics")
    w2_net = _number(w2_metrics.get("net_after_cost_r"), "w2.net_after_cost_r")
    w2_dd = _number(w2_metrics.get("max_drawdown_r"), "w2.max_drawdown_r", minimum=0.0)
    blockers: list[str] = []
    receipt_deltas: dict[str, dict[str, float]] = {}
    for stage in ("W3", "NEW_SEALED"):
        stage_blockers, deltas = _receipt_blockers(receipts[stage], policy, w2_net, w2_dd)
        blockers.extend(stage_blockers)
        receipt_deltas[stage] = deltas

    state = "PASS_SYNTHESIS_NEW_SEALED_WAIT_CLASSIFIER" if not blockers else "HOLD_SYNTHESIS_SEAL"
    seal: dict[str, Any] | None = None
    if not blockers:
        seal = {
            "schema_version": "strategy11.synthesis_seal.v1",
            "seal_state": "NEW_SEALED_WAIT_CLASSIFIER",
            "candidate_id": candidate_id,
            "candidate_sha": candidate_sha,
            "template": candidate["template"],
            "base_strategy_id": candidate["base_strategy_id"],
            "component_lineage": [
                {
                    "material_id": row["material_id"],
                    "material_sha": row["material_sha"],
                    "semantic_axis": row["semantic_axis"],
                }
                for row in candidate["components"]
            ],
            "factorial_sha": factorial_result["factorial_sha"],
            "attribution_sha": reproduced_attribution["attribution_sha"],
            "w3_receipt_sha": receipts["W3"]["receipt_sha"],
            "new_sealed_receipt_sha": receipts["NEW_SEALED"]["receipt_sha"],
            "stage_lineage_sha": canonical_sha(lineages),
            "classification_ready": True,
            "runtime_bound": False,
            **SAFETY,
        }
        seal["seal_sha"] = canonical_sha(seal)

    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state,
        "candidate_id": candidate_id,
        "candidate_sha": candidate_sha,
        "stage_lineages": lineages,
        "receipt_deltas": receipt_deltas,
        "blockers": blockers,
        "synthesis_seal": seal,
        "classification_ready": seal is not None,
        "next": "GLOBAL_CANDIDATE_CLASSIFIER" if seal is not None else "HOLD_OR_REDESIGN",
        **SAFETY,
    }
    result["sealer_sha"] = canonical_sha(result)
    return result
