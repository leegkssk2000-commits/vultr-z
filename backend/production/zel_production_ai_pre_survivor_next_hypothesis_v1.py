from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.production import zel_production_ai_proposal_layer_v1 as proposal_v1
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_pre_survivor_next_hypothesis.v1"
POLICY_SCHEMA = "zel.production_ai_pre_survivor_next_hypothesis_policy.v1"
TEMPLATE_REGISTRY_SCHEMA = "zel.production_ai_admission_template_registry.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_pre_survivor_next_hypothesis_v1.json")
ACCUMULATING_STATE = "PASS_PRE_SURVIVOR_ACCUMULATING_CONTEXT_PROJECTED"
EDGE_SCHEMA = "zel.production_economic_edge_router.v1"
ACTIVE_PROPOSAL_PATH = "/home/z/z/ledger/production_ai_edge_proposals_v1.json"


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_NON_PAPER_FORBIDDEN")
    if policy.get("role") != "PARALLEL_NEXT_HYPOTHESIS_OBSERVER_NOT_ROUTE":
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_ROLE_DRIFT")
    for key in ("proposal_policy_path", "feedback_path", "factory_path", "survivor_pool_path", "output_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_NEXT_HYPOTHESIS_PATH_MISSING:{key}")
    if "template_registry_path" in policy and not str(policy.get("template_registry_path") or "").strip():
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY_PATH_MISSING")
    if str(policy["output_path"]) == ACTIVE_PROPOSAL_PATH:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_ACTIVE_PROPOSAL_PATH_FORBIDDEN")
    _authority_guard(policy, "PRE_SURVIVOR_NEXT_HYPOTHESIS_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_MUTATION_FORBIDDEN")
    return dict(policy)


def _feedback_context(feedback: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "context_kind",
        "non_terminal_context",
        "source_admission_state",
        "family_id",
        "template_id",
        "progress_direction",
        "trade_count",
        "win_rate_pct",
        "net_expectancy",
        "profit_factor",
        "net_pnl",
        "max_dd_pct",
    )
    missing = [key for key in required if key not in feedback]
    if missing:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_FEEDBACK_FIELD_MISSING:" + ",".join(missing))
    if feedback.get("context_kind") != "PROVISIONAL_ACCUMULATING" or feedback.get("non_terminal_context") is not True:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_CONTEXT_KIND_INVALID")
    return {
        "state": feedback.get("state"),
        "context_kind": feedback.get("context_kind"),
        "non_terminal_context": True,
        "source_admission_state": feedback.get("source_admission_state"),
        "family_id": feedback.get("family_id"),
        "template_id": feedback.get("template_id"),
        "progress_direction": feedback.get("progress_direction"),
        "context_intent": feedback.get("context_intent"),
        "metrics": {
            "trade_count": feedback.get("trade_count"),
            "win_rate_pct": feedback.get("win_rate_pct"),
            "net_expectancy": feedback.get("net_expectancy"),
            "profit_factor": feedback.get("profit_factor"),
            "net_pnl": feedback.get("net_pnl"),
            "max_dd_pct": feedback.get("max_dd_pct"),
        },
        "metric_units": feedback.get("metric_units"),
        "delta_vs_previous": feedback.get("delta_vs_previous"),
        "win_rate_role": feedback.get("win_rate_role"),
    }


def _synthetic_edge(feedback_context: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint = stable_sha({"lane": "PRE_SURVIVOR_NEXT_HYPOTHESIS", "feedback": feedback_context})
    return {
        "schema_version": EDGE_SCHEMA,
        "state": "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED",
        "next": "PROPOSE_PARALLEL_NEXT_HYPOTHESIS_WITHOUT_ROUTE",
        "blockers": ["PRE_SURVIVOR_PARALLEL_OBSERVER_ONLY", "CURRENT_FAMILY_REMAINS_ACTIVE_AND_UNCHANGED"],
        "explore_context_sha256": fingerprint,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def _frozen_template_context(template_registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    if template_registry.get("schema_version") != TEMPLATE_REGISTRY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY_SCHEMA_INVALID")
    _authority_guard(template_registry, "PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY")
    if template_registry.get("source_code_mutation_allowed") is not False or template_registry.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY_MUTATION_FORBIDDEN")
    templates = template_registry.get("templates")
    if not isinstance(templates, Mapping) or not templates:
        raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY_EMPTY")
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for template_id, raw in sorted(templates.items()):
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_INVALID:{template_id}")
        signature = tuple(sorted(map(str, raw.get("required_sources_exact") or [])))
        if not signature or signature in seen:
            raise RuntimeError("PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_SIGNATURE_INVALID")
        seen.add(signature)
        if raw.get("numeric_signal_thresholds") != [] or raw.get("parameter_search") is not False:
            raise RuntimeError(f"PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_SEARCH_FORBIDDEN:{template_id}")
        out.append(
            {
                "template_id": str(template_id),
                "required_sources_exact": list(signature),
                "mechanism_class": raw.get("mechanism_class"),
                "event_anchor": raw.get("event_anchor"),
                "direction_rule": raw.get("direction_rule"),
                "context_rule": raw.get("context_rule"),
                "horizon_rule": raw.get("horizon_rule"),
            }
        )
    return out


def build_context(
    proposal_policy: Mapping[str, Any],
    *,
    feedback: Mapping[str, Any],
    factory: Mapping[str, Any],
    pool: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    proposal_cfg = proposal_v1.validate_policy(proposal_policy)
    feedback_context = _feedback_context(feedback)
    edge = _synthetic_edge(feedback_context)
    context = proposal_v1.build_context(
        proposal_cfg,
        edge=edge,
        factory=factory,
        pool=pool,
        improvement=None,
    )
    context["lane"] = "PRE_SURVIVOR_PARALLEL_NEXT_HYPOTHESIS_OBSERVER"
    context["pre_survivor_feedback"] = feedback_context
    context["current_family_mutation_allowed"] = False
    context["current_contract_mutation_allowed"] = False
    if isinstance(template_registry, Mapping):
        context["frozen_admission_templates"] = _frozen_template_context(template_registry)
        context["required_source_signature_rule"] = "MUST_EXACTLY_MATCH_ONE_FROZEN_ADMISSION_TEMPLATE"
    return context


def proposal_prompt(context: Mapping[str, Any], candidate_budget: int) -> str:
    schema = {
        "status": "PASS|HOLD",
        "proposals": [
            {
                "proposal_type": "NEW_ECONOMIC_FAMILY|FEATURE_AUGMENTATION",
                "family_id": "lower_snake_case",
                "economic_mechanism": "plain causal economic hypothesis",
                "required_sources": ["source_id"],
                "causal_reason": "why the mechanism could create a risk premium or information advantage",
                "falsification_test": "one bounded deterministic test that can reject the hypothesis",
                "expected_horizon": "natural market horizon, no fitted threshold",
            }
        ],
        "hold_reason": "optional",
    }
    template_instruction = ""
    if context.get("frozen_admission_templates"):
        template_instruction = (
            " For this research lane, every proposal required_sources set MUST exactly equal one required_sources_exact set in "
            "CONTEXT.frozen_admission_templates. Do not invent, union, subtract, or otherwise alter a frozen source signature. "
            "The causal mechanism must be consistent with the matched frozen template mechanism_class/direction/context; if no distinct causal "
            "hypothesis can use an existing frozen signature, return HOLD rather than proposing an unmaterializable family."
        )
    return (
        "You are a proposal-only quantitative research planner in a fail-closed crypto futures system. "
        "The current economic family is still accumulating evidence and MUST NOT be replaced, tuned, promoted, rejected, or routed by you. "
        f"Using its current observer-only economic feedback, propose at most {candidate_budget} distinct NEXT hypotheses for parallel future evaluation. "
        "Do not claim profitability, choose a winner, alter the current contract, grant selection/promotion/execution/order authority, provide code, "
        "or propose numeric thresholds, parameter sweeps, stop/TP tuning, leverage, or sizing. "
        "Prefer causal mechanisms using verified native sources and avoid duplicating any existing or terminal family mechanism. "
        "Each proposal must contain one bounded falsification test."
        + template_instruction
        + " Return strict JSON only.\n\n"
        + f"CONTEXT={json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
        + f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def _bind_frozen_templates(
    proposals: list[dict[str, Any]], template_registry: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    templates = _frozen_template_context(template_registry)
    by_signature = {tuple(row["required_sources_exact"]): row for row in templates}
    bound: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for proposal in proposals:
        signature = tuple(sorted(map(str, proposal.get("required_sources") or [])))
        template = by_signature.get(signature)
        if template is None:
            blockers.append(
                {
                    "family_id": str(proposal.get("family_id") or ""),
                    "classification": "ADMISSION_TEMPLATE_REQUIRED",
                    "required_sources": list(signature),
                }
            )
            continue
        row = dict(proposal)
        row["template_id"] = str(template["template_id"])
        row["template_ready"] = True
        bound.append(row)
    return bound, blockers


def _base(state: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "role": "PARALLEL_NEXT_HYPOTHESIS_OBSERVER_NOT_ROUTE",
        "action": "hold",
        "proposal_count": 0,
        "source_ready_count": 0,
        "template_ready_count": 0,
        "proposals": [],
        "template_blockers": [],
        "ai_call_made": False,
        "ai_call_succeeded": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": now_ms,
    }


def next_hypothesis_tick(
    policy: Mapping[str, Any],
    proposal_policy: Mapping[str, Any],
    *,
    feedback: Mapping[str, Any] | None,
    factory: Mapping[str, Any] | None,
    pool: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    ai_caller: Callable[[str], tuple[str, Mapping[str, Any]]] | None,
    template_registry: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], bool]:
    cfg = validate_policy(policy)
    proposal_cfg = proposal_v1.validate_policy(proposal_policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(feedback, Mapping) or feedback.get("state") != ACCUMULATING_STATE:
        out = _base("HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_NO_ACCUMULATING_CONTEXT", now)
        out["receipt_sha256"] = stable_sha(out)
        return out, False
    _authority_guard(feedback, "PRE_SURVIVOR_NEXT_HYPOTHESIS_FEEDBACK")
    if not isinstance(factory, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_FACTORY_MISSING", now)
        out["receipt_sha256"] = stable_sha(out)
        return out, False
    template_required = bool(str(cfg.get("template_registry_path") or "").strip())
    if template_required and not isinstance(template_registry, Mapping):
        out = _base("HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_REGISTRY_MISSING", now)
        out["receipt_sha256"] = stable_sha(out)
        return out, False
    context = build_context(
        proposal_cfg,
        feedback=feedback,
        factory=factory,
        pool=pool,
        template_registry=template_registry if template_required else None,
    )
    context_sha = stable_sha(context)
    explore_sha = str(context["explore_context_sha256"])
    if (
        isinstance(previous, Mapping)
        and previous.get("schema_version") == SCHEMA
        and previous.get("context_sha256") == context_sha
        and previous.get("ai_call_succeeded") is True
    ):
        return dict(previous), False
    if ai_caller is None:
        out = _base("HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_CALLER_UNAVAILABLE", now)
        out.update({"context_sha256": context_sha, "explore_context_sha256": explore_sha})
        out["receipt_sha256"] = stable_sha(out)
        return out, False
    try:
        model, raw = ai_caller(proposal_prompt(context, int(proposal_cfg["candidate_budget"])))
        raw_proposals = proposal_v1.validate_ai_response(raw, policy=proposal_cfg, context=context)
        template_blockers: list[dict[str, Any]] = []
        proposals = raw_proposals
        if template_required:
            assert isinstance(template_registry, Mapping)
            proposals, template_blockers = _bind_frozen_templates(raw_proposals, template_registry)
    except Exception as exc:  # noqa: BLE001
        out = _base("HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_CALL_FAILED", now)
        out.update(
            {
                "context_sha256": context_sha,
                "explore_context_sha256": explore_sha,
                "error_class": type(exc).__name__,
                "error_code": str(exc)[:500],
                "ai_call_made": True,
            }
        )
        out["receipt_sha256"] = stable_sha(out)
        return out, True
    source_ready = sum(bool(row.get("source_ready")) for row in proposals)
    template_ready = sum(bool(row.get("template_ready")) for row in proposals) if template_required else len(proposals)
    if template_required and raw_proposals and not proposals:
        state = "HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_TEMPLATE_BINDING_REQUIRED"
    elif source_ready:
        state = "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
    elif proposals:
        state = "HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_BINDING_REQUIRED"
    else:
        state = "HOLD_PRE_SURVIVOR_NEXT_HYPOTHESIS_NO_CANDIDATE"
    out = _base(state, now)
    out.update(
        {
            "provider": "GEMINI",
            "model": model,
            "context_sha256": context_sha,
            "explore_context_sha256": explore_sha,
            "source_feedback_receipt_sha256": str(feedback.get("receipt_sha256") or ""),
            "current_family_id": str(feedback.get("family_id") or ""),
            "current_progress_direction": str(feedback.get("progress_direction") or ""),
            "ai_proposal_count": len(raw_proposals),
            "proposal_count": len(proposals),
            "source_ready_count": source_ready,
            "template_ready_count": template_ready,
            "proposals": proposals,
            "template_blockers": template_blockers,
            "available_sources": list(context["available_sources"]),
            "ai_call_made": True,
            "ai_call_succeeded": True,
            "reused": False,
        }
    )
    out["receipt_sha256"] = stable_sha(out)
    return out, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate observer-only next hypotheses from accumulating pre-survivor economics")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    proposal_policy = json.loads(Path(str(cfg["proposal_policy_path"])).read_text(encoding="utf-8"))
    proposal_cfg = proposal_v1.validate_policy(proposal_policy)
    feedback = read_json(Path(str(cfg["feedback_path"])))
    factory = read_json(Path(str(cfg["factory_path"])))
    if not isinstance(factory, Mapping):
        factory = read_json(Path(str(proposal_cfg["factory_path"])))
    pool = read_json(Path(str(cfg["survivor_pool_path"])))
    template_registry = None
    if str(cfg.get("template_registry_path") or "").strip():
        template_registry = read_json(Path(str(cfg["template_registry_path"])))
    previous = read_json(Path(str(cfg["output_path"])))
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    def caller(prompt: str) -> tuple[str, Mapping[str, Any]]:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY_MISSING")
        return proposal_v1.call_gemini(
            api_key,
            [str(v) for v in proposal_cfg["models"]],
            prompt,
            int(proposal_cfg["max_output_tokens"]),
            float(proposal_cfg["temperature"]),
        )

    result, should_write = next_hypothesis_tick(
        cfg,
        proposal_cfg,
        feedback=feedback,
        factory=factory,
        pool=pool,
        previous=previous,
        ai_caller=caller,
        template_registry=template_registry,
    )
    if should_write or not isinstance(previous, Mapping) or previous.get("receipt_sha256") != result.get("receipt_sha256"):
        atomic_json_write(Path(str(cfg["output_path"])), result)
        written = True
    else:
        written = False
    print(
        json.dumps(
            {
                "state": result["state"],
                "proposal_count": int(result.get("proposal_count") or 0),
                "source_ready_count": int(result.get("source_ready_count") or 0),
                "template_ready_count": int(result.get("template_ready_count") or 0),
                "current_family_id": result.get("current_family_id"),
                "ai_call_made": bool(result.get("ai_call_made")),
                "reused": bool(result.get("reused")),
                "written": written,
                "receipt_sha256": result.get("receipt_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
