from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_admission_materializer.v1"
POLICY_SCHEMA = "zel.production_ai_admission_materializer_policy.v1"
PROPOSAL_SCHEMA = "zel.production_ai_proposal_layer.v1"
SOURCE_REGISTRY_SCHEMA = "zel.production_source_capability_registry.v1"
TEMPLATE_REGISTRY_SCHEMA = "zel.production_ai_admission_template_registry.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_admission_materializer_v1.json")


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("AI_ADMISSION_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("AI_ADMISSION_NON_PAPER_FORBIDDEN")
    if int(policy.get("candidate_budget") or 0) not in (1, 2):
        raise RuntimeError("AI_ADMISSION_CANDIDATE_BUDGET_INVALID")
    for key in ("proposal_state_path", "source_registry_path", "template_registry_path", "output_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"AI_ADMISSION_PATH_MISSING:{key}")
    _authority_guard(policy, "AI_ADMISSION_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("AI_ADMISSION_MUTATION_FORBIDDEN")
    return dict(policy)


def validate_source_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    if registry.get("schema_version") != SOURCE_REGISTRY_SCHEMA:
        raise RuntimeError("AI_ADMISSION_SOURCE_REGISTRY_SCHEMA_INVALID")
    _authority_guard(registry, "AI_ADMISSION_SOURCE_REGISTRY")
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise RuntimeError("AI_ADMISSION_SOURCE_REGISTRY_EMPTY")
    return dict(registry)


def validate_template_registry(registry: Mapping[str, Any]) -> dict[str, Any]:
    if registry.get("schema_version") != TEMPLATE_REGISTRY_SCHEMA:
        raise RuntimeError("AI_ADMISSION_TEMPLATE_REGISTRY_SCHEMA_INVALID")
    _authority_guard(registry, "AI_ADMISSION_TEMPLATE_REGISTRY")
    if registry.get("source_code_mutation_allowed") is not False or registry.get("self_modification_allowed") is not False:
        raise RuntimeError("AI_ADMISSION_TEMPLATE_MUTATION_FORBIDDEN")
    templates = registry.get("templates")
    if not isinstance(templates, Mapping) or not templates:
        raise RuntimeError("AI_ADMISSION_TEMPLATES_EMPTY")
    seen: set[tuple[str, ...]] = set()
    for template_id, raw in templates.items():
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"AI_ADMISSION_TEMPLATE_INVALID:{template_id}")
        required = tuple(sorted(map(str, raw.get("required_sources_exact") or [])))
        if not required or required in seen:
            raise RuntimeError("AI_ADMISSION_TEMPLATE_SOURCE_SIGNATURE_DUPLICATE")
        seen.add(required)
        if raw.get("numeric_signal_thresholds") != [] or raw.get("parameter_search") is not False:
            raise RuntimeError(f"AI_ADMISSION_TEMPLATE_SEARCH_FORBIDDEN:{template_id}")
        if str(raw.get("outcome_source") or "") != "ohlcv":
            raise RuntimeError(f"AI_ADMISSION_TEMPLATE_OUTCOME_DRIFT:{template_id}")
        controls = raw.get("negative_controls")
        if controls != ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"]:
            raise RuntimeError(f"AI_ADMISSION_TEMPLATE_CONTROLS_DRIFT:{template_id}")
    return dict(registry)


def _find_template(templates: Mapping[str, Any], required_sources: list[str]) -> tuple[str, dict[str, Any]] | None:
    signature = tuple(sorted(required_sources))
    matches: list[tuple[str, dict[str, Any]]] = []
    for template_id, raw in templates.items():
        if tuple(sorted(map(str, raw.get("required_sources_exact") or []))) == signature:
            matches.append((str(template_id), dict(raw)))
    if len(matches) > 1:
        raise RuntimeError("AI_ADMISSION_TEMPLATE_AMBIGUOUS")
    return matches[0] if matches else None


def materialize_tick(
    policy: Mapping[str, Any],
    *,
    proposal: Mapping[str, Any] | None,
    source_registry: Mapping[str, Any] | None,
    template_registry: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    out: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "HOLD_AI_ADMISSION_NO_SOURCE_READY_PROPOSAL",
        "action": "hold",
        "contracts": [],
        "blockers": [],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "updated_at_ms": now,
    }
    if not isinstance(proposal, Mapping):
        out["receipt_sha256"] = stable_sha(out)
        return out
    if proposal.get("schema_version") != PROPOSAL_SCHEMA:
        raise RuntimeError("AI_ADMISSION_PROPOSAL_SCHEMA_INVALID")
    _authority_guard(proposal, "AI_ADMISSION_PROPOSAL")
    if proposal.get("exchange_order_submitted") is not False:
        raise RuntimeError("AI_ADMISSION_PROPOSAL_ORDER_INVALID")
    if not isinstance(source_registry, Mapping) or not isinstance(template_registry, Mapping):
        out["state"] = "HOLD_AI_ADMISSION_REGISTRY_MISSING"
        out["receipt_sha256"] = stable_sha(out)
        return out
    sources = validate_source_registry(source_registry)["sources"]
    templates = validate_template_registry(template_registry)["templates"]
    raw_proposals = proposal.get("proposals")
    if not isinstance(raw_proposals, list) or len(raw_proposals) > int(cfg["candidate_budget"]):
        raise RuntimeError("AI_ADMISSION_PROPOSAL_LIST_INVALID")

    for raw in raw_proposals:
        if not isinstance(raw, Mapping):
            raise RuntimeError("AI_ADMISSION_PROPOSAL_ROW_INVALID")
        family_id = str(raw.get("family_id") or "")
        required = sorted(set(map(str, raw.get("required_sources") or [])))
        if not family_id or not required:
            raise RuntimeError("AI_ADMISSION_PROPOSAL_IDENTITY_INVALID")
        unavailable = sorted(s for s in required if s not in sources or sources[s].get("proposal_available") is not True)
        if unavailable or raw.get("source_ready") is not True:
            out["blockers"].append({"family_id": family_id, "classification": "SOURCE_UNBOUND", "missing_sources": unavailable or list(raw.get("missing_sources") or [])})
            continue
        match = _find_template(templates, required)
        if match is None:
            out["blockers"].append({"family_id": family_id, "classification": "ADMISSION_TEMPLATE_REQUIRED", "required_sources": required})
            continue
        template_id, template = match
        outcome_source = str(template["outcome_source"])
        if outcome_source not in sources or sources[outcome_source].get("proposal_available") is not True:
            out["blockers"].append({"family_id": family_id, "classification": "OUTCOME_SOURCE_UNBOUND", "missing_sources": [outcome_source]})
            continue
        frozen = {
            "schema_version": "zel.production_ai_admission_contract.v1",
            "contract_id": stable_sha({"proposal_id": raw.get("proposal_id"), "template_id": template_id, "source_registry_sha256": stable_sha(source_registry)})[:32],
            "family_id": family_id,
            "proposal_id": str(raw.get("proposal_id") or ""),
            "proposal_receipt_sha256": proposal.get("receipt_sha256"),
            "template_id": template_id,
            "template_sha256": stable_sha(template),
            "source_registry_sha256": stable_sha(source_registry),
            "required_sources": required,
            "outcome_source": outcome_source,
            "mechanism_class": template["mechanism_class"],
            "event_anchor": template["event_anchor"],
            "direction_rule": template["direction_rule"],
            "horizon_rule": template["horizon_rule"],
            "temporal_durability_split": template["temporal_durability_split"],
            "negative_controls": list(template["negative_controls"]),
            "numeric_signal_thresholds": [],
            "parameter_search": False,
            "executor_state": template["executor_state"],
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        frozen["receipt_sha256"] = stable_sha(frozen)
        out["contracts"].append(frozen)

    if out["contracts"]:
        out["state"] = "PASS_AI_ADMISSION_CONTRACTS_FROZEN"
        out["next"] = "WAIT_VERIFIED_NORMALIZED_SOURCE_HISTORY_THEN_RUN_DETERMINISTIC_TEMPLATE_ADMISSION"
    elif any(x.get("classification") == "ADMISSION_TEMPLATE_REQUIRED" for x in out["blockers"]):
        out["state"] = "HOLD_AI_ADMISSION_TEMPLATE_REQUIRED"
        out["next"] = "REGISTER_FROZEN_DECLARATIVE_ADMISSION_TEMPLATE"
    elif out["blockers"]:
        out["state"] = "HOLD_AI_ADMISSION_SOURCE_BINDING_REQUIRED"
        out["next"] = "WAIT_FOR_SOURCE_ACQUISITION_RESOLUTION"
    out["contract_count"] = len(out["contracts"])
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    result = materialize_tick(
        cfg,
        proposal=read_json(Path(str(cfg["proposal_state_path"]))),
        source_registry=read_json(Path(str(cfg["source_registry_path"]))),
        template_registry=read_json(Path(str(cfg["template_registry_path"]))),
    )
    atomic_json_write(Path(str(cfg["output_path"])), result)
    print(json.dumps({"state": result["state"], "contract_count": result.get("contract_count", 0), "next": result.get("next"), "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
