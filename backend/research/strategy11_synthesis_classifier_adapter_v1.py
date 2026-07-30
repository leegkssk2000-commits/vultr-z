from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from backend.contracts.strategy11_strategy_proposal_contract_v1 import seal_proposal
from backend.research.strategy11_global_candidate_classifier_v1 import classify_candidate
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha
from backend.research.strategy11_synthesis_sealer_v1 import seal_synthesis

INPUT_SCHEMA = "strategy11.synthesis_classifier_adapter.input.v1"
OUTPUT_SCHEMA = "strategy11.synthesis_classifier_adapter.output.v1"
CONTEXT_SCHEMA = "strategy11.synthesis_classifier_context.v1"


class SynthesisClassifierAdapterError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise SynthesisClassifierAdapterError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, 64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


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


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def validate_context(value: Mapping[str, Any]) -> dict[str, Any]:
    context = _mapping(value, "context")
    required = {
        "schema_version", "artifact", "run_id", "producer", "market", "confidence",
        "cost_envelope", "edge_projection", "risk_context", "statistics", "lineage",
        "reason_codes", "metadata", "source_ledger",
    }
    missing = sorted(required - set(context))
    extra = sorted(set(context) - required)
    if missing:
        _fail("CONTEXT_FIELDS_MISSING", ",".join(missing))
    if extra:
        _fail("CONTEXT_EXTRA_FIELDS", ",".join(extra))
    if context.get("schema_version") != CONTEXT_SCHEMA:
        _fail("CONTEXT_SCHEMA_MISMATCH")

    edge = _mapping(context["edge_projection"], "context.edge_projection")
    risk = _mapping(context["risk_context"], "context.risk_context")
    stats = _mapping(context["statistics"], "context.statistics")
    lineage = _mapping(context["lineage"], "context.lineage")
    source_ledger = context["source_ledger"]
    if not isinstance(source_ledger, list) or not source_ledger:
        _fail("SOURCE_LEDGER_REQUIRED")
    normalized_trades: list[dict[str, Any]] = []
    seen_trade_ids: set[str] = set()
    for index, raw in enumerate(source_ledger):
        row = _mapping(raw, f"context.source_ledger[{index}]")
        trade_id = _string(row.get("trade_id"), f"source_ledger[{index}].trade_id")
        if trade_id in seen_trade_ids:
            _fail("DUPLICATE_SOURCE_TRADE_ID", trade_id)
        seen_trade_ids.add(trade_id)
        normalized_trades.append(
            {
                "trade_id": trade_id,
                "timestamp": _string(row.get("timestamp"), f"source_ledger[{index}].timestamp"),
                "net_r": _number(row.get("net_r"), f"source_ledger[{index}].net_r"),
                "symbol": _string(row.get("symbol"), f"source_ledger[{index}].symbol").upper(),
                "regime": _string(row.get("regime"), f"source_ledger[{index}].regime").upper(),
                "source_row_sha": _sha(row.get("source_row_sha"), f"source_ledger[{index}].source_row_sha"),
            }
        )
    normalized_trades.sort(key=lambda row: (row["timestamp"], row["trade_id"]))

    reason_codes = context["reason_codes"]
    if not isinstance(reason_codes, list):
        _fail("REASON_CODES_LIST_REQUIRED")
    normalized = {
        "schema_version": CONTEXT_SCHEMA,
        "artifact": _string(context["artifact"], "context.artifact"),
        "run_id": _string(context["run_id"], "context.run_id", 80),
        "producer": copy.deepcopy(_mapping(context["producer"], "context.producer")),
        "market": copy.deepcopy(_mapping(context["market"], "context.market")),
        "confidence": copy.deepcopy(_mapping(context["confidence"], "context.confidence")),
        "cost_envelope": copy.deepcopy(_mapping(context["cost_envelope"], "context.cost_envelope")),
        "edge_projection": {
            "win_rate_pct": _number(edge.get("win_rate_pct"), "edge.win_rate_pct", 0.0, 100.0),
            "net_pct": _number(edge.get("net_pct"), "edge.net_pct"),
            "retention_pct": _number(edge.get("retention_pct"), "edge.retention_pct", 0.0, 100.0),
        },
        "risk_context": {
            "max_drawdown_pct": _number(risk.get("max_drawdown_pct"), "risk.max_drawdown_pct", 0.0),
            "joint_tail_budget_pct": _number(risk.get("joint_tail_budget_pct"), "risk.joint_tail_budget_pct", 0.0),
            "max_exposure_pct": _number(risk.get("max_exposure_pct"), "risk.max_exposure_pct", 0.0, 100.0),
        },
        "statistics": {
            "trade_quota_pass": _boolean(stats.get("trade_quota_pass"), "statistics.trade_quota_pass"),
            "regime_coverage_pass": _boolean(stats.get("regime_coverage_pass"), "statistics.regime_coverage_pass"),
            "dsr_pass": _boolean(stats.get("dsr_pass"), "statistics.dsr_pass"),
            "bh_fdr_pass": _boolean(stats.get("bh_fdr_pass"), "statistics.bh_fdr_pass"),
            "independent_edge_pass": _boolean(stats.get("independent_edge_pass"), "statistics.independent_edge_pass"),
            "synthesis_eligible": _boolean(stats.get("synthesis_eligible"), "statistics.synthesis_eligible"),
            "symbol_concentration_pct": _number(stats.get("symbol_concentration_pct"), "statistics.symbol_concentration_pct", 0.0, 100.0),
            "window_concentration_pct": _number(stats.get("window_concentration_pct"), "statistics.window_concentration_pct", 0.0, 100.0),
            "regime_concentration_pct": _number(stats.get("regime_concentration_pct"), "statistics.regime_concentration_pct", 0.0, 100.0),
        },
        "lineage": {
            "strategy_source_sha": _sha(lineage.get("strategy_source_sha"), "lineage.strategy_source_sha"),
            "data_epoch": _string(lineage.get("data_epoch"), "lineage.data_epoch", 100),
        },
        "reason_codes": sorted({_string(item, "reason_codes[]", 100).upper() for item in reason_codes}),
        "metadata": copy.deepcopy(_mapping(context["metadata"], "context.metadata")),
        "source_ledger": normalized_trades,
    }
    return normalized


def _new_sealed_receipt(sealer_input: Mapping[str, Any]) -> dict[str, Any]:
    confirmations = sealer_input.get("confirmations")
    if not isinstance(confirmations, list):
        _fail("SEALER_CONFIRMATIONS_REQUIRED")
    matches = [dict(row) for row in confirmations if isinstance(row, Mapping) and row.get("stage") == "NEW_SEALED"]
    if len(matches) != 1:
        _fail("NEW_SEALED_RECEIPT_MATCH_COUNT", str(len(matches)))
    return matches[0]


def adapt_and_classify(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "adapter_input")
    allowed = {
        "schema_version", "sealer_input", "sealer_result", "context", "context_sha",
        "classifier_policy", "classifier_policy_sha", "authority",
    }
    if set(payload) != allowed:
        _fail("INPUT_FIELD_SET_MISMATCH")
    if payload.get("schema_version") != INPUT_SCHEMA or payload.get("authority") != SAFETY:
        _fail("INPUT_SCHEMA_OR_AUTHORITY_MISMATCH")

    sealer_input = _mapping(payload["sealer_input"], "sealer_input")
    reproduced = seal_synthesis(sealer_input)
    supplied = _mapping(payload["sealer_result"], "sealer_result")
    if supplied.get("sealer_sha") != reproduced.get("sealer_sha") or supplied != reproduced:
        _fail("SEALER_RESULT_RECONCILIATION_MISMATCH")
    if reproduced.get("state") != "PASS_SYNTHESIS_NEW_SEALED_WAIT_CLASSIFIER":
        _fail("PASS_SYNTHESIS_SEAL_REQUIRED")
    seal = _mapping(reproduced.get("synthesis_seal"), "synthesis_seal")
    if seal.get("classification_ready") is not True or seal.get("seal_state") != "NEW_SEALED_WAIT_CLASSIFIER":
        _fail("SYNTHESIS_SEAL_NOT_CLASSIFIER_READY")

    context = validate_context(payload["context"])
    if _sha(payload["context_sha"], "context_sha") != canonical_sha(context):
        _fail("CONTEXT_SHA_MISMATCH")
    classifier_policy = _mapping(payload["classifier_policy"], "classifier_policy")
    if _sha(payload["classifier_policy_sha"], "classifier_policy_sha") != canonical_sha(classifier_policy):
        _fail("CLASSIFIER_POLICY_SHA_MISMATCH")

    candidate = _mapping(sealer_input["attribution_input"]["factorial_input"]["candidate"], "candidate")
    if candidate.get("candidate_sha") != seal.get("candidate_sha"):
        _fail("CANDIDATE_SEAL_SHA_MISMATCH")
    new_sealed = _new_sealed_receipt(sealer_input)
    metrics = _mapping(new_sealed.get("metrics"), "new_sealed.metrics")
    lineage = _mapping(new_sealed.get("lineage"), "new_sealed.lineage")
    evidence_manifest_sha = canonical_sha(
        {
            "seal_sha": seal["seal_sha"],
            "context_sha": payload["context_sha"],
            "new_sealed_receipt_sha": new_sealed["receipt_sha"],
            "classifier_policy_sha": payload["classifier_policy_sha"],
        }
    )
    strategy_id = f"synthesis.{candidate['base_strategy_id']}.{candidate['candidate_sha'][:12]}"
    proposal = seal_proposal(
        {
            "schema_version": "strategy11.strategy_proposal.v1",
            "proposal_id": f"proposal.{strategy_id}.{context['run_id']}",
            "strategy_id": strategy_id,
            "candidate_sha": candidate["candidate_sha"],
            "producer": copy.deepcopy(context["producer"]),
            "market": copy.deepcopy(context["market"]),
            "edge": {
                "trades": _integer(metrics.get("trades"), "new_sealed.trades", 1),
                "win_rate_pct": context["edge_projection"]["win_rate_pct"],
                "net_pct": context["edge_projection"]["net_pct"],
                "profit_factor": _number(metrics.get("profit_factor"), "new_sealed.profit_factor", 0.0),
                "payoff": _number(metrics.get("payoff"), "new_sealed.payoff", 0.0),
                "positive_windows": _integer(metrics.get("positive_windows"), "new_sealed.positive_windows"),
                "total_windows": _integer(metrics.get("total_windows"), "new_sealed.total_windows", 1),
                "retention_pct": context["edge_projection"]["retention_pct"],
            },
            "confidence": copy.deepcopy(context["confidence"]),
            "cost_envelope": copy.deepcopy(context["cost_envelope"]),
            "risk_envelope": {
                "max_drawdown_pct": context["risk_context"]["max_drawdown_pct"],
                "avg_loss_r": _number(metrics.get("avg_loss_r"), "new_sealed.avg_loss_r", maximum=0.0),
                "worst_loss_r": _number(metrics.get("worst_loss_r"), "new_sealed.worst_loss_r", maximum=0.0),
                "stress_worst_loss_r": _number(metrics.get("stress_worst_loss_r"), "new_sealed.stress_worst_loss_r", maximum=0.0),
                "joint_tail_budget_pct": context["risk_context"]["joint_tail_budget_pct"],
                "max_exposure_pct": context["risk_context"]["max_exposure_pct"],
            },
            "lineage": {
                "strategy_source_sha": context["lineage"]["strategy_source_sha"],
                "candidate_config_sha": candidate["candidate_sha"],
                "data_sha": _sha(lineage.get("data_sha"), "new_sealed.data_sha"),
                "window_sha": _sha(lineage.get("window_sha"), "new_sealed.window_sha"),
                "source_manifest_sha": _sha(lineage.get("source_manifest_sha"), "new_sealed.source_manifest_sha"),
                "run_id": _string(lineage.get("replay_run_id"), "new_sealed.replay_run_id", 40),
                "artifact": context["artifact"],
                "data_epoch": context["lineage"]["data_epoch"],
            },
            "proposal_state": "REQUEST_EVALUATION",
            "reason_codes": context["reason_codes"],
            "authority": {
                "stage": "RESEARCH",
                "research_only": True,
                "promotion_authority": False,
                "execution_allowed": False,
                "order_authority": "BLOCKED",
                "protected_mutations": 0,
            },
            "metadata": {
                **copy.deepcopy(context["metadata"]),
                "adapter": "strategy11.synthesis_classifier_adapter.v1",
                "synthesis_seal_sha": seal["seal_sha"],
                "factorial_sha": seal["factorial_sha"],
                "attribution_sha": seal["attribution_sha"],
                "component_lineage": copy.deepcopy(seal["component_lineage"]),
                "context_sha": payload["context_sha"],
            },
        }
    )
    stats = context["statistics"]
    evidence = {
        "stages": {"w1": "PASS", "w2": "PASS", "w3": "PASS", "new_sealed": "PASS"},
        "trade_quota_pass": stats["trade_quota_pass"],
        "regime_coverage_pass": stats["regime_coverage_pass"],
        "dsr_pass": stats["dsr_pass"],
        "bh_fdr_pass": stats["bh_fdr_pass"],
        "independent_edge_pass": stats["independent_edge_pass"],
        "synthesis_eligible": stats["synthesis_eligible"],
        "symbol_concentration_pct": stats["symbol_concentration_pct"],
        "window_concentration_pct": stats["window_concentration_pct"],
        "regime_concentration_pct": stats["regime_concentration_pct"],
        "evidence_manifest_sha": evidence_manifest_sha,
    }
    classification = classify_candidate(proposal, evidence, classifier_policy)
    if classification["classification"] == "CORE":
        _fail("SYNTHESIS_SEAL_CLASSIFIED_CORE")
    state_by_class = {
        "SYNTHESIS": "PASS_SYNTHESIS_CLASSIFIER_ADAPTER",
        "HOLD": "HOLD_SYNTHESIS_CLASSIFIER_ADAPTER",
        "REJECT": "REJECT_SYNTHESIS_CLASSIFIER_ADAPTER",
    }
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "state": state_by_class[classification["classification"]],
        "strategy_id": strategy_id,
        "candidate_sha": candidate["candidate_sha"],
        "synthesis_seal_sha": seal["seal_sha"],
        "proposal": proposal,
        "proposal_sha": proposal["proposal_sha"],
        "classifier_evidence": evidence,
        "evidence_manifest_sha": evidence_manifest_sha,
        "classification": classification,
        "classification_sha": classification["classification_sha"],
        "source_ledger": context["source_ledger"],
        "fixture_or_research_only": True,
        "runtime_bound": False,
        "next": "ENSEMBLE_CORRELATION_ANALYZER" if classification["classification"] == "SYNTHESIS" else "HOLD_OR_REJECT",
        **SAFETY,
    }
    result["adapter_sha"] = canonical_sha(result)
    return result
