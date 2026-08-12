from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.production.zel_production_ai_proposal_layer_v1 import (
    SCHEMA,
    build_context,
    call_gemini,
    proposal_prompt,
    validate_ai_response,
    validate_policy,
)
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

TRIGGER_ERROR = "AI_PROPOSAL_REQUIRED_SOURCE_OUTSIDE_VOCAB"
REPAIR_SCHEMA = "zel.production_ai_proposal_repair.v1"


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_AUTHORITY_INVALID")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_INVALID")
    if row.get("live_trade_authority") != "BLOCKED" or row.get("exchange_order_submitted") is not False:
        raise RuntimeError(f"{prefix}_LIVE_INVALID")


def corrective_prompt(context: Mapping[str, Any], candidate_budget: int, vocabulary: list[str]) -> str:
    allowed = sorted(map(str, vocabulary))
    return (
        proposal_prompt(context, candidate_budget)
        + "\n\nCORRECTIVE_RETRY_CONTRACT="
        + json.dumps(
            {
                "reason": TRIGGER_ERROR,
                "attempt": 1,
                "max_corrective_attempts": 1,
                "allowed_source_vocabulary_exact": allowed,
                "required_sources_rule": "EVERY_REQUIRED_SOURCE_MUST_BE_EXACT_MEMBER_OF_ALLOWED_SOURCE_VOCABULARY",
                "outside_vocabulary_sources": "FORBIDDEN",
                "source_aliases": "FORBIDDEN",
                "silent_source_substitution": "FORBIDDEN",
                "numeric_thresholds": "FORBIDDEN",
                "selection_promotion_execution_order_authority": "FORBIDDEN",
                "response": "STRICT_JSON_ONLY",
            },
            sort_keys=True,
        )
    )


def _base(state: str, context_sha: str, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "repair_schema_version": REPAIR_SCHEMA,
        "state": state,
        "action": "hold",
        "explore_context_sha256": context_sha,
        "proposal_count": 0,
        "source_ready_count": 0,
        "proposals": [],
        "ai_call_made": True,
        "ai_call_succeeded": False,
        "repair_attempted": True,
        "repair_attempt_count": 1,
        "repair_trigger_error_code": TRIGGER_ERROR,
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


def repair_tick(
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

    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return None, False
    _authority_guard(previous, "AI_PROPOSAL_REPAIR_PREVIOUS")
    if previous.get("state") != "HOLD_AI_PROPOSAL_CALL_FAILED" or previous.get("error_code") != TRIGGER_ERROR:
        return None, False
    if previous.get("ai_call_made") is not True or previous.get("ai_call_succeeded") is not False:
        raise RuntimeError("AI_PROPOSAL_REPAIR_TRIGGER_RECEIPT_INVALID")
    if previous.get("repair_attempted") is True:
        return dict(previous), False
    if not isinstance(edge, Mapping) or not isinstance(factory, Mapping):
        return None, False
    if str(edge.get("state") or "") not in set(map(str, cfg["trigger_states"])):
        return None, False

    context = build_context(cfg, edge=edge, factory=factory, pool=pool, improvement=improvement)
    context_sha = str(context["explore_context_sha256"])
    if str(previous.get("explore_context_sha256") or "") != context_sha:
        return None, False
    if ai_caller is None:
        out = _base("HOLD_AI_PROPOSAL_CORRECTIVE_CALLER_UNAVAILABLE", context_sha, now)
        out["error_class"] = "RuntimeError"
        out["error_code"] = "AI_PROPOSAL_CORRECTIVE_CALLER_UNAVAILABLE"
        out["retry_after_ms"] = now + int(cfg["proposal_retry_cooldown_ms"])
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out, True

    prompt = corrective_prompt(context, int(cfg["candidate_budget"]), list(cfg["source_vocabulary"]))
    try:
        model, raw = ai_caller(prompt)
        proposals = validate_ai_response(raw, policy=cfg, context=context)
    except Exception as exc:  # noqa: BLE001
        out = _base("HOLD_AI_PROPOSAL_CORRECTIVE_RETRY_FAILED", context_sha, now)
        out["error_class"] = type(exc).__name__
        out["error_code"] = str(exc)[:500]
        out["retry_after_ms"] = now + int(cfg["proposal_retry_cooldown_ms"])
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out, True

    ready = sum(bool(row.get("source_ready")) for row in proposals)
    state = "PASS_AI_PROPOSAL_SOURCE_READY" if ready else (
        "HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED" if proposals else "HOLD_AI_PROPOSAL_NO_CANDIDATE"
    )
    out = _base(state, context_sha, now)
    out.update(
        {
            "provider": "GEMINI",
            "model": model,
            "proposal_count": len(proposals),
            "source_ready_count": ready,
            "proposals": proposals,
            "available_sources": list(context["available_sources"]),
            "context_sha256": stable_sha(context),
            "ai_call_succeeded": True,
            "retry_after_ms": 0,
        }
    )
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, True


def _sanitized_proposal_status(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, Mapping) or row.get("schema_version") != SCHEMA:
        return None
    proposals = row.get("proposals")
    safe_rows: list[dict[str, Any]] = []
    if isinstance(proposals, list):
        for raw in proposals:
            if not isinstance(raw, Mapping):
                continue
            safe_rows.append(
                {
                    "proposal_id": str(raw.get("proposal_id") or ""),
                    "family_id": str(raw.get("family_id") or ""),
                    "proposal_type": str(raw.get("proposal_type") or ""),
                    "required_sources": sorted(map(str, raw.get("required_sources") or [])),
                    "missing_sources": sorted(map(str, raw.get("missing_sources") or [])),
                    "source_ready": bool(raw.get("source_ready")),
                }
            )
    return {
        "state": str(row.get("state") or ""),
        "proposal_count": int(row.get("proposal_count") or 0),
        "source_ready_count": int(row.get("source_ready_count") or 0),
        "repair_attempted": bool(row.get("repair_attempted")),
        "ai_call_succeeded": bool(row.get("ai_call_succeeded")),
        "proposals": safe_rows,
        "receipt_sha256": row.get("receipt_sha256"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-shot corrective retry for invalid AI proposal source vocabulary")
    ap.add_argument("--policy", type=Path, default=Path("config/zel_production_ai_proposal_layer_v1.json"))
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    proposal_path = Path(str(cfg["proposal_state_path"]))
    previous = read_json(proposal_path)
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

    result, should_write = repair_tick(
        cfg,
        edge=read_json(Path(str(cfg["acquisition_state_path"]))),
        factory=read_json(Path(str(cfg["factory_path"]))),
        pool=read_json(Path(str(cfg["survivor_pool_path"]))),
        improvement=read_json(Path(str(cfg["improvement_evidence_path"]))),
        previous=previous,
        ai_caller=caller,
    )
    if result is None:
        print(
            json.dumps(
                {
                    "state": "HOLD_AI_PROPOSAL_CORRECTIVE_RETRY_NOT_REQUIRED",
                    "written": False,
                    "persisted_proposal": _sanitized_proposal_status(previous),
                },
                sort_keys=True,
            )
        )
        return 0
    if should_write:
        atomic_json_write(proposal_path, result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "proposal_count": int(result.get("proposal_count") or 0),
                "source_ready_count": int(result.get("source_ready_count") or 0),
                "repair_attempted": bool(result.get("repair_attempted")),
                "ai_call_succeeded": bool(result.get("ai_call_succeeded")),
                "written": bool(should_write),
                "receipt_sha256": result.get("receipt_sha256"),
                "persisted_proposal": _sanitized_proposal_status(result),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
