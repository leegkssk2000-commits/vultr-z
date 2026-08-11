from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_proposal_layer.v1"
POLICY_SCHEMA = "zel.production_ai_proposal_policy.v1"
EDGE_SCHEMA = "zel.production_economic_edge_router.v1"
FACTORY_SCHEMA = "zel.production_alpha_factory.v1"
POOL_SCHEMA = "zel.production_survivor_pool.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_proposal_layer_v1.json")

_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_ALLOWED_PROPOSAL_TYPES = {"NEW_ECONOMIC_FAMILY", "FEATURE_AUGMENTATION"}
_BANNED_KEYS = {
    "selection_authority",
    "promotion_authority",
    "execution_authority",
    "order_authority",
    "live_trade_authority",
    "exchange_order_submitted",
    "source_code",
    "code_patch",
    "patch",
    "threshold",
    "thresholds",
    "parameter",
    "parameters",
    "expected_pnl",
    "expected_return",
    "profit_target",
}
_VOLATILE_EDGE_KEYS = {"updated_at_ms", "receipt_sha256"}


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("AI_PROPOSAL_NON_PAPER_FORBIDDEN")
    if int(policy.get("candidate_budget") or 0) not in (1, 2):
        raise RuntimeError("AI_PROPOSAL_CANDIDATE_BUDGET_INVALID")
    for key in (
        "acquisition_state_path",
        "factory_path",
        "survivor_pool_path",
        "improvement_evidence_path",
        "proposal_state_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"AI_PROPOSAL_PATH_MISSING:{key}")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("AI_PROPOSAL_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("AI_PROPOSAL_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("AI_PROPOSAL_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("AI_PROPOSAL_MUTATION_FORBIDDEN")
    if policy.get("numeric_threshold_proposals_allowed") is not False:
        raise RuntimeError("AI_PROPOSAL_NUMERIC_THRESHOLDS_FORBIDDEN")
    for key in ("raw_trades_sent", "private_code_sent", "account_data_sent", "credentials_sent"):
        if policy.get(key) is not False:
            raise RuntimeError(f"AI_PROPOSAL_DATA_BOUNDARY_INVALID:{key}")
    trigger_states = policy.get("trigger_states")
    if not isinstance(trigger_states, list) or trigger_states != ["HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"]:
        raise RuntimeError("AI_PROPOSAL_TRIGGER_STATES_INVALID")
    vocabulary = policy.get("source_vocabulary")
    if not isinstance(vocabulary, list) or not vocabulary or len(vocabulary) != len(set(map(str, vocabulary))):
        raise RuntimeError("AI_PROPOSAL_SOURCE_VOCABULARY_INVALID")
    if any(not _SAFE_ID.fullmatch(str(v)) for v in vocabulary):
        raise RuntimeError("AI_PROPOSAL_SOURCE_VOCABULARY_UNSAFE")
    models = policy.get("models")
    if not isinstance(models, list) or not models:
        raise RuntimeError("AI_PROPOSAL_MODELS_MISSING")
    return dict(policy)


def _edge_structural_view(edge: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in edge.items() if k not in _VOLATILE_EDGE_KEYS}


def edge_context_sha(edge: Mapping[str, Any]) -> str:
    supplied = str(edge.get("explore_context_sha256") or "").strip()
    if supplied:
        return supplied
    return stable_sha(_edge_structural_view(edge))


def _source_capabilities(factory: Mapping[str, Any], vocabulary: Sequence[str]) -> tuple[list[str], list[str]]:
    if factory.get("schema_version") != FACTORY_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_FACTORY_SCHEMA_INVALID")
    families = factory.get("families")
    if not isinstance(families, Mapping):
        raise RuntimeError("AI_PROPOSAL_FACTORY_FAMILIES_MISSING")
    available: set[str] = set()
    observed: set[str] = set()
    aliases = {
        "funding_source_bound": "funding",
        "basis_source_bound": "basis",
        "open_interest_source_bound": "open_interest",
        "flow_source_bound": "flow",
    }
    allowed = set(map(str, vocabulary))
    for row in families.values():
        if not isinstance(row, Mapping):
            continue
        for key, cap in aliases.items():
            if key in row and cap in allowed:
                observed.add(cap)
                if row.get(key) is True:
                    available.add(cap)
    unavailable = sorted(observed - available)
    return sorted(available), unavailable


def _family_context(factory: Mapping[str, Any]) -> list[dict[str, Any]]:
    families = factory.get("families")
    if not isinstance(families, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for family_id, raw in sorted(families.items()):
        if not isinstance(raw, Mapping):
            continue
        source_flags = {
            key: raw.get(key)
            for key in (
                "funding_source_bound",
                "basis_source_bound",
                "open_interest_source_bound",
                "flow_source_bound",
                "history_coverage_bound",
            )
            if key in raw
        }
        out.append(
            {
                "family_id": str(family_id),
                "strategy_id": str(raw.get("strategy_id") or ""),
                "status": str(raw.get("status") or ""),
                "mechanism": raw.get("mechanism"),
                "symbols": list(raw.get("symbols") or []),
                "source_flags": source_flags,
                "reactivation_allowed": raw.get("reactivation_allowed"),
            }
        )
    return out


def _pool_context(pool: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pool, Mapping):
        return {"state": "MISSING", "active_count": 0, "reserve_count": 0, "verified_family_count": 0}
    if pool.get("schema_version") != POOL_SCHEMA:
        return {"state": "SCHEMA_UNRECOGNIZED", "active_count": 0, "reserve_count": 0, "verified_family_count": 0}
    return {
        "state": pool.get("state"),
        "active_count": int(pool.get("active_count") or 0),
        "reserve_count": int(pool.get("reserve_count") or 0),
        "verified_family_count": int(pool.get("verified_family_count") or 0),
        "active_families": [str(x.get("family_id") or "") for x in (pool.get("active") or []) if isinstance(x, Mapping)],
        "reserve_families": [str(x.get("family_id") or "") for x in (pool.get("reserve") or []) if isinstance(x, Mapping)],
    }


def _improvement_context(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        return {"state": "MISSING"}
    metrics: dict[str, Any] = {}
    for key in (
        "trade_count",
        "net_expectancy",
        "profit_factor",
        "net_pnl",
        "max_dd_pct",
        "error_count",
        "score",
    ):
        if key in evidence:
            metrics[key] = evidence.get(key)
    return {"state": evidence.get("state"), "metrics": metrics}


def build_context(
    policy: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    factory: Mapping[str, Any],
    pool: Mapping[str, Any] | None,
    improvement: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    if edge.get("schema_version") != EDGE_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_EDGE_SCHEMA_INVALID")
    available, unavailable = _source_capabilities(factory, cfg["source_vocabulary"])
    return {
        "explore_context_sha256": edge_context_sha(edge),
        "edge_state": edge.get("state"),
        "edge_next": edge.get("next"),
        "edge_blockers": list(edge.get("blockers") or []),
        "available_sources": available,
        "observed_but_unbound_sources": unavailable,
        "source_vocabulary": list(cfg["source_vocabulary"]),
        "families": _family_context(factory),
        "survivor_pool": _pool_context(pool),
        "improvement": _improvement_context(improvement),
    }


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
    return (
        "You are a proposal-only quantitative research planner inside a fail-closed crypto futures system. "
        "The deterministic system has exhausted its currently source-ready economic-family catalog. "
        f"Propose at most {candidate_budget} distinct economic hypotheses. "
        "Do NOT claim profitability, do NOT choose a winner, do NOT grant survivor/selection/promotion/execution/order authority, "
        "do NOT provide code or patches, and do NOT propose numeric thresholds, parameter sweeps, stop/TP tuning, or leverage/sizing. "
        "Prefer causal economic mechanisms and currently available native sources. You may name an unavailable source only when it is essential; "
        "the deterministic source gate will then HOLD it. Do not duplicate or rename an existing/terminal family mechanism. "
        "Each proposal must contain one falsification test, not a recipe for optimization. Return strict JSON only.\n\n"
        f"CONTEXT={json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def _parse_gemini_text(payload: Mapping[str, Any]) -> str:
    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content")
        if not isinstance(content, Mapping):
            continue
        for part in content.get("parts", []):
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("AI_PROPOSAL_EMPTY_GEMINI_RESPONSE")
    return text


def _parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].lstrip()
    payload = json.loads(stripped)
    if not isinstance(payload, Mapping):
        raise RuntimeError("AI_PROPOSAL_RESPONSE_NOT_OBJECT")
    return dict(payload)


def _list_gemini_models(api_key: str, preferred: Sequence[str]) -> list[str]:
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    eligible = [
        str(row["name"])
        for row in payload.get("models", [])
        if row.get("name") and "generateContent" in row.get("supportedGenerationMethods", [])
    ]
    ordered = [model for model in preferred if model in eligible]
    ordered.extend(model for model in eligible if model not in ordered and "flash" in model.lower())
    return ordered


def call_gemini(api_key: str, models: Sequence[str], prompt: str, max_output_tokens: int, temperature: float) -> tuple[str, dict[str, Any]]:
    available = _list_gemini_models(api_key, models)
    if not available:
        raise RuntimeError("AI_PROPOSAL_NO_ELIGIBLE_GEMINI_MODEL")
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
    ).encode("utf-8")
    errors: list[str] = []
    for model in available[:4]:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                generated = json.load(response)
            return model, _parse_json_response(_parse_gemini_text(generated))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            errors.append(f"{model}:HTTP_{exc.code}:{detail}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("AI_PROPOSAL_ALL_MODELS_FAILED:" + "|".join(errors[-8:]))


def _reject_banned_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in _BANNED_KEYS:
                raise RuntimeError(f"AI_PROPOSAL_BANNED_KEY:{path}.{key_text}")
            _reject_banned_keys(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_banned_keys(child, f"{path}[{idx}]")


def validate_ai_response(
    response: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cfg = validate_policy(policy)
    _reject_banned_keys(response)
    status = str(response.get("status") or "")
    if status not in {"PASS", "HOLD"}:
        raise RuntimeError("AI_PROPOSAL_STATUS_INVALID")
    raw = response.get("proposals")
    if raw is None and status == "HOLD":
        raw = []
    if not isinstance(raw, list):
        raise RuntimeError("AI_PROPOSAL_LIST_INVALID")
    if len(raw) > int(cfg["candidate_budget"]):
        raise RuntimeError("AI_PROPOSAL_BUDGET_EXCEEDED")
    existing = {str(row.get("family_id") or "") for row in context.get("families", []) if isinstance(row, Mapping)}
    vocab = set(map(str, cfg["source_vocabulary"]))
    available = set(map(str, context.get("available_sources") or []))
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise RuntimeError("AI_PROPOSAL_ITEM_INVALID")
        required_keys = {
            "proposal_type",
            "family_id",
            "economic_mechanism",
            "required_sources",
            "causal_reason",
            "falsification_test",
            "expected_horizon",
        }
        if set(item) != required_keys:
            extra = sorted(set(item) - required_keys)
            missing = sorted(required_keys - set(item))
            raise RuntimeError(f"AI_PROPOSAL_SCHEMA_MISMATCH:{index}:extra={extra}:missing={missing}")
        proposal_type = str(item["proposal_type"])
        family_id = str(item["family_id"])
        if proposal_type not in _ALLOWED_PROPOSAL_TYPES:
            raise RuntimeError("AI_PROPOSAL_TYPE_INVALID")
        if not _SAFE_ID.fullmatch(family_id):
            raise RuntimeError("AI_PROPOSAL_FAMILY_ID_INVALID")
        if family_id in existing or family_id in seen:
            raise RuntimeError("AI_PROPOSAL_DUPLICATE_FAMILY")
        seen.add(family_id)
        required_sources = item["required_sources"]
        if not isinstance(required_sources, list) or not required_sources or len(required_sources) > 6:
            raise RuntimeError("AI_PROPOSAL_REQUIRED_SOURCES_INVALID")
        normalized_sources = [str(v) for v in required_sources]
        if len(normalized_sources) != len(set(normalized_sources)) or any(v not in vocab for v in normalized_sources):
            raise RuntimeError("AI_PROPOSAL_REQUIRED_SOURCE_OUTSIDE_VOCAB")
        for key in ("economic_mechanism", "causal_reason", "falsification_test", "expected_horizon"):
            text = str(item[key] or "").strip()
            if not text or len(text) > 1200:
                raise RuntimeError(f"AI_PROPOSAL_TEXT_INVALID:{key}")
        missing_sources = sorted(set(normalized_sources) - available)
        proposal = {
            "proposal_id": stable_sha({"context": context["explore_context_sha256"], "family_id": family_id})[:24],
            "proposal_type": proposal_type,
            "family_id": family_id,
            "economic_mechanism": str(item["economic_mechanism"]).strip(),
            "required_sources": sorted(normalized_sources),
            "missing_sources": missing_sources,
            "source_ready": not missing_sources,
            "causal_reason": str(item["causal_reason"]).strip(),
            "falsification_test": str(item["falsification_test"]).strip(),
            "expected_horizon": str(item["expected_horizon"]).strip(),
            "state": "PASS_AI_PROPOSAL_SOURCE_READY" if not missing_sources else "HOLD_AI_PROPOSAL_SOURCE_UNBOUND",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "source_code_mutation_allowed": False,
        }
        proposals.append(proposal)
    return proposals


def proposal_tick(
    policy: Mapping[str, Any],
    *,
    edge: Mapping[str, Any] | None,
    factory: Mapping[str, Any] | None,
    pool: Mapping[str, Any] | None,
    improvement: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    ai_caller: Callable[[str], tuple[str, Mapping[str, Any]]] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(edge, Mapping) or str(edge.get("state") or "") not in set(map(str, cfg["trigger_states"])):
        return None, False
    if not isinstance(factory, Mapping):
        out = _base_output("HOLD_AI_PROPOSAL_FACTORY_MISSING", edge_context_sha(edge), now)
        return out, False
    context = build_context(cfg, edge=edge, factory=factory, pool=pool, improvement=improvement)
    context_sha = str(context["explore_context_sha256"])
    if isinstance(previous, Mapping) and previous.get("schema_version") == SCHEMA and previous.get("explore_context_sha256") == context_sha:
        retry_after = int(previous.get("retry_after_ms") or 0)
        if previous.get("ai_call_succeeded") is True or now < retry_after:
            return dict(previous), False
    if ai_caller is None:
        out = _base_output("HOLD_AI_PROPOSAL_CALLER_UNAVAILABLE", context_sha, now)
        return out, False
    try:
        model, raw = ai_caller(proposal_prompt(context, int(cfg["candidate_budget"])))
        proposals = validate_ai_response(raw, policy=cfg, context=context)
    except Exception as exc:  # noqa: BLE001
        out = _base_output("HOLD_AI_PROPOSAL_CALL_FAILED", context_sha, now)
        out["error_class"] = type(exc).__name__
        out["error_code"] = str(exc)[:500]
        out["retry_after_ms"] = now + int(cfg["proposal_retry_cooldown_ms"])
        out["ai_call_made"] = True
        out["ai_call_succeeded"] = False
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out, True
    ready = sum(bool(row.get("source_ready")) for row in proposals)
    state = "PASS_AI_PROPOSAL_SOURCE_READY" if ready else ("HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED" if proposals else "HOLD_AI_PROPOSAL_NO_CANDIDATE")
    out = _base_output(state, context_sha, now)
    out.update(
        {
            "provider": "GEMINI",
            "model": model,
            "proposal_count": len(proposals),
            "source_ready_count": ready,
            "proposals": proposals,
            "available_sources": list(context["available_sources"]),
            "context_sha256": stable_sha(context),
            "ai_call_made": True,
            "ai_call_succeeded": True,
            "reused": False,
            "retry_after_ms": 0,
        }
    )
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, True


def _base_output(state: str, context_sha: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "explore_context_sha256": context_sha,
        "proposal_count": 0,
        "source_ready_count": 0,
        "proposals": [],
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--tick", action="store_true")
    ns = ap.parse_args()
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = validate_policy(policy)
    edge = read_json(Path(str(cfg["acquisition_state_path"])))
    factory = read_json(Path(str(cfg["factory_path"])))
    pool = read_json(Path(str(cfg["survivor_pool_path"])))
    improvement = read_json(Path(str(cfg["improvement_evidence_path"])))
    previous = read_json(Path(str(cfg["proposal_state_path"])))

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    def caller(prompt: str) -> tuple[str, Mapping[str, Any]]:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY_MISSING")
        return call_gemini(
            api_key,
            [str(v) for v in cfg["models"]],
            prompt,
            int(cfg["max_output_tokens"]),
            float(cfg["temperature"]),
        )

    result, should_write = proposal_tick(
        cfg,
        edge=edge,
        factory=factory,
        pool=pool,
        improvement=improvement,
        previous=previous,
        ai_caller=caller,
    )
    if result is None:
        print(json.dumps({"state": "HOLD_AI_PROPOSAL_NOT_REQUIRED", "written": False}, sort_keys=True))
        return 0
    if should_write or not isinstance(previous, Mapping) or previous.get("receipt_sha256") != result.get("receipt_sha256"):
        atomic_json_write(Path(str(cfg["proposal_state_path"])), result)
        written = True
    else:
        written = False
    print(
        json.dumps(
            {
                "state": result["state"],
                "proposal_count": int(result.get("proposal_count") or 0),
                "source_ready_count": int(result.get("source_ready_count") or 0),
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
