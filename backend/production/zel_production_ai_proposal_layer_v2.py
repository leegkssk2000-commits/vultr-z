from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.production import zel_production_ai_proposal_layer_v1 as v1
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = v1.SCHEMA
POOL_SCHEMA = "zel.production_survivor_pool.v1"
CATALOG_SCHEMA = "zel.production_survivor_catalog.v1"
QUARANTINE_SCHEMA = "zel.production_survivor_quarantine.v1"
DEFAULT_POLICY = v1.DEFAULT_POLICY
TRIGGER_POOL_REFILL = "SURVIVOR_POOL_REFILL"


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"AI_PROPOSAL_V2_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"AI_PROPOSAL_V2_{label}_RECEIPT_MISMATCH")
    return claimed


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    cfg = v1.validate_policy(policy)
    for key in ("survivor_catalog_path", "quarantine_path"):
        if not str(cfg.get(key) or "").strip():
            raise RuntimeError(f"AI_PROPOSAL_V2_PATH_MISSING:{key}")
    if cfg.get("pool_refill_trigger_enabled") is not True:
        raise RuntimeError("AI_PROPOSAL_V2_POOL_REFILL_TRIGGER_DISABLED")
    if int(cfg.get("pool_refill_target_total") or 0) != 5:
        raise RuntimeError("AI_PROPOSAL_V2_POOL_REFILL_TARGET_DRIFT")
    if cfg.get("pool_refill_selection_rule") != "STRUCTURAL_DEFICIT_ONLY_NO_METRIC_RERANK":
        raise RuntimeError("AI_PROPOSAL_V2_POOL_REFILL_RULE_DRIFT")
    return cfg


def _pool_status(pool: Mapping[str, Any] | None, target: int) -> dict[str, Any] | None:
    if not isinstance(pool, Mapping):
        return None
    if pool.get("schema_version") != POOL_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_V2_POOL_SCHEMA_INVALID")
    receipt = _verified_receipt(pool, "POOL")
    active = pool.get("active")
    reserve = pool.get("reserve")
    if not isinstance(active, list) or not isinstance(reserve, list):
        raise RuntimeError("AI_PROPOSAL_V2_POOL_ROWS_INVALID")
    active_count = int(pool.get("active_count") or 0)
    reserve_count = int(pool.get("reserve_count") or 0)
    if active_count != len(active) or reserve_count != len(reserve):
        raise RuntimeError("AI_PROPOSAL_V2_POOL_COUNT_MISMATCH")
    total = active_count + reserve_count
    if total > target:
        raise RuntimeError("AI_PROPOSAL_V2_POOL_COUNT_OVER_TARGET")
    target_state = str(pool.get("state") or "") == "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2"
    if target_state != (total == target):
        raise RuntimeError("AI_PROPOSAL_V2_POOL_STATE_TARGET_MISMATCH")
    return {
        "receipt_sha256": receipt,
        "state": str(pool.get("state") or ""),
        "active_count": active_count,
        "reserve_count": reserve_count,
        "total_count": total,
        "deficit_count": target - total,
        "family_ids": sorted({str(x.get("family_id") or "") for x in active + reserve if isinstance(x, Mapping) and str(x.get("family_id") or "")}),
        "quarantined_identity_count": int(pool.get("quarantined_identity_count") or 0),
        "quarantined_candidate_count": int(pool.get("quarantined_candidate_count") or 0),
    }


def _catalog_context(catalog: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(catalog, Mapping):
        return None
    if catalog.get("schema_version") != CATALOG_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_V2_CATALOG_SCHEMA_INVALID")
    receipt = _verified_receipt(catalog, "CATALOG")
    rows = catalog.get("survivors")
    if not isinstance(rows, list):
        raise RuntimeError("AI_PROPOSAL_V2_CATALOG_ROWS_INVALID")
    return {
        "receipt_sha256": receipt,
        "family_ids": sorted({str(x.get("family_id") or "") for x in rows if isinstance(x, Mapping) and str(x.get("family_id") or "")}),
        "family_count": len(rows),
    }


def _quarantine_context(quarantine: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(quarantine, Mapping):
        return {"receipt_sha256": None, "family_ids": [], "entry_count": 0}
    if quarantine.get("schema_version") != QUARANTINE_SCHEMA:
        raise RuntimeError("AI_PROPOSAL_V2_QUARANTINE_SCHEMA_INVALID")
    receipt = _verified_receipt(quarantine, "QUARANTINE")
    rows = quarantine.get("entries")
    if not isinstance(rows, list):
        raise RuntimeError("AI_PROPOSAL_V2_QUARANTINE_ROWS_INVALID")
    return {
        "receipt_sha256": receipt,
        "family_ids": sorted({str(x.get("family_id") or "") for x in rows if isinstance(x, Mapping) and str(x.get("family_id") or "")}),
        "entry_count": len(rows),
    }


def _merge_forbidden_families(context: dict[str, Any], family_ids: set[str]) -> None:
    rows = [dict(x) for x in context.get("families") or [] if isinstance(x, Mapping)]
    existing = {str(x.get("family_id") or "") for x in rows}
    for family_id in sorted(family_ids - existing):
        rows.append(
            {
                "family_id": family_id,
                "strategy_id": "",
                "status": "EXISTING_OR_QUARANTINED_DO_NOT_DUPLICATE",
                "mechanism": None,
                "symbols": [],
                "source_flags": {},
                "reactivation_allowed": False,
            }
        )
    context["families"] = rows


def build_pool_refill_context(
    policy: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    factory: Mapping[str, Any],
    pool: Mapping[str, Any],
    improvement: Mapping[str, Any] | None,
    catalog: Mapping[str, Any],
    quarantine: Mapping[str, Any] | None,
) -> dict[str, Any]:
    cfg = validate_policy(policy)
    target = int(cfg["pool_refill_target_total"])
    pool_ctx = _pool_status(pool, target)
    if pool_ctx is None:
        raise RuntimeError("AI_PROPOSAL_V2_POOL_MISSING")
    catalog_ctx = _catalog_context(catalog)
    if catalog_ctx is None:
        raise RuntimeError("AI_PROPOSAL_V2_CATALOG_MISSING")
    quarantine_ctx = _quarantine_context(quarantine)
    context = v1.build_context(cfg, edge=edge, factory=factory, pool=pool, improvement=improvement)
    forbidden = set(pool_ctx["family_ids"]) | set(catalog_ctx["family_ids"]) | set(quarantine_ctx["family_ids"])
    _merge_forbidden_families(context, forbidden)
    structural = {
        "trigger_kind": TRIGGER_POOL_REFILL,
        "pool_receipt_sha256": pool_ctx["receipt_sha256"],
        "catalog_receipt_sha256": catalog_ctx["receipt_sha256"],
        "quarantine_receipt_sha256": quarantine_ctx["receipt_sha256"],
        "target_total": target,
        "active_count": pool_ctx["active_count"],
        "reserve_count": pool_ctx["reserve_count"],
        "deficit_count": pool_ctx["deficit_count"],
        "forbidden_family_ids": sorted(forbidden),
        "available_sources": context["available_sources"],
        "families": context["families"],
    }
    context["explore_context_sha256"] = stable_sha(structural)
    context["trigger_kind"] = TRIGGER_POOL_REFILL
    context["pool_refill"] = {
        "target_total": target,
        "active_count": pool_ctx["active_count"],
        "reserve_count": pool_ctx["reserve_count"],
        "deficit_count": pool_ctx["deficit_count"],
        "selection_rule": cfg["pool_refill_selection_rule"],
        "pool_receipt_sha256": pool_ctx["receipt_sha256"],
        "catalog_receipt_sha256": catalog_ctx["receipt_sha256"],
        "quarantine_receipt_sha256": quarantine_ctx["receipt_sha256"],
        "forbidden_family_ids": sorted(forbidden),
    }
    return context


def pool_refill_prompt(context: Mapping[str, Any], candidate_budget: int) -> str:
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
        "The verified 3+2 survivor pool is structurally underfilled, so the system needs new independent economic-family candidates to replenish capacity. "
        f"Propose at most {candidate_budget} distinct economic hypotheses. "
        "Do NOT duplicate any existing, terminal, or quarantined family in the supplied context. "
        "Do NOT claim profitability, choose a winner, grant survivor/selection/promotion/execution/order authority, provide code or patches, "
        "or propose numeric thresholds, parameter sweeps, stop/TP tuning, leverage, or sizing. "
        "Prefer causal mechanisms using currently available verified native sources. Each proposal must have one bounded falsification test. "
        "Return strict JSON only.\n\n"
        f"CONTEXT={json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def _pool_refill_tick(
    cfg: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    factory: Mapping[str, Any],
    pool: Mapping[str, Any],
    improvement: Mapping[str, Any] | None,
    catalog: Mapping[str, Any],
    quarantine: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    ai_caller: Callable[[str], tuple[str, Mapping[str, Any]]] | None,
    now_ms: int,
) -> tuple[dict[str, Any] | None, bool]:
    pool_ctx = _pool_status(pool, int(cfg["pool_refill_target_total"]))
    if pool_ctx is None or int(pool_ctx["deficit_count"]) <= 0:
        return None, False
    if not isinstance(catalog, Mapping):
        out = v1._base_output("HOLD_AI_PROPOSAL_POOL_REFILL_CATALOG_MISSING", stable_sha({"pool": pool_ctx}), now_ms)
        out["trigger_kind"] = TRIGGER_POOL_REFILL
        return out, False
    context = build_pool_refill_context(
        cfg,
        edge=edge,
        factory=factory,
        pool=pool,
        improvement=improvement,
        catalog=catalog,
        quarantine=quarantine,
    )
    context_sha = str(context["explore_context_sha256"])
    if isinstance(previous, Mapping) and previous.get("schema_version") == SCHEMA and previous.get("explore_context_sha256") == context_sha:
        retry_after = int(previous.get("retry_after_ms") or 0)
        if previous.get("ai_call_succeeded") is True or now_ms < retry_after:
            return dict(previous), False
    if ai_caller is None:
        out = v1._base_output("HOLD_AI_PROPOSAL_CALLER_UNAVAILABLE", context_sha, now_ms)
        out["trigger_kind"] = TRIGGER_POOL_REFILL
        return out, False
    budget = min(int(cfg["candidate_budget"]), int(context["pool_refill"]["deficit_count"]))
    try:
        model, raw = ai_caller(pool_refill_prompt(context, budget))
        proposals = v1.validate_ai_response(raw, policy=cfg, context=context)
        if len(proposals) > budget:
            raise RuntimeError("AI_PROPOSAL_V2_POOL_REFILL_DEFICIT_BUDGET_EXCEEDED")
    except Exception as exc:  # noqa: BLE001
        out = v1._base_output("HOLD_AI_PROPOSAL_CALL_FAILED", context_sha, now_ms)
        out.update(
            {
                "trigger_kind": TRIGGER_POOL_REFILL,
                "pool_refill_deficit_count": int(context["pool_refill"]["deficit_count"]),
                "error_class": type(exc).__name__,
                "error_code": str(exc)[:500],
                "retry_after_ms": now_ms + int(cfg["proposal_retry_cooldown_ms"]),
                "ai_call_made": True,
                "ai_call_succeeded": False,
            }
        )
        out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
        return out, True
    ready = sum(bool(row.get("source_ready")) for row in proposals)
    state = "PASS_AI_PROPOSAL_SOURCE_READY" if ready else ("HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED" if proposals else "HOLD_AI_PROPOSAL_NO_CANDIDATE")
    out = v1._base_output(state, context_sha, now_ms)
    out.update(
        {
            "trigger_kind": TRIGGER_POOL_REFILL,
            "provider": "GEMINI",
            "model": model,
            "proposal_count": len(proposals),
            "source_ready_count": ready,
            "proposals": proposals,
            "available_sources": list(context["available_sources"]),
            "context_sha256": stable_sha(context),
            "pool_refill_deficit_count": int(context["pool_refill"]["deficit_count"]),
            "pool_refill_target_total": int(context["pool_refill"]["target_total"]),
            "pool_receipt_sha256": context["pool_refill"]["pool_receipt_sha256"],
            "catalog_receipt_sha256": context["pool_refill"]["catalog_receipt_sha256"],
            "quarantine_receipt_sha256": context["pool_refill"]["quarantine_receipt_sha256"],
            "ai_call_made": True,
            "ai_call_succeeded": True,
            "reused": False,
            "retry_after_ms": 0,
        }
    )
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, True


def proposal_tick(
    policy: Mapping[str, Any],
    *,
    edge: Mapping[str, Any] | None,
    factory: Mapping[str, Any] | None,
    pool: Mapping[str, Any] | None,
    improvement: Mapping[str, Any] | None,
    catalog: Mapping[str, Any] | None,
    quarantine: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    ai_caller: Callable[[str], tuple[str, Mapping[str, Any]]] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    edge_trigger = isinstance(edge, Mapping) and str(edge.get("state") or "") in set(map(str, cfg["trigger_states"]))
    if edge_trigger:
        return v1.proposal_tick(
            cfg,
            edge=edge,
            factory=factory,
            pool=pool,
            improvement=improvement,
            previous=previous,
            ai_caller=ai_caller,
            now_ms=now,
        )
    if not isinstance(edge, Mapping) or edge.get("schema_version") != v1.EDGE_SCHEMA:
        return None, False
    if not isinstance(factory, Mapping):
        return None, False
    if not isinstance(pool, Mapping):
        return None, False
    return _pool_refill_tick(
        cfg,
        edge=edge,
        factory=factory,
        pool=pool,
        improvement=improvement,
        catalog=catalog,
        quarantine=quarantine,
        previous=previous,
        ai_caller=ai_caller,
        now_ms=now,
    )


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
    catalog = read_json(Path(str(cfg["survivor_catalog_path"])))
    quarantine = read_json(Path(str(cfg["quarantine_path"])))
    previous = read_json(Path(str(cfg["proposal_state_path"])))
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    def caller(prompt: str) -> tuple[str, Mapping[str, Any]]:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY_MISSING")
        return v1.call_gemini(
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
        catalog=catalog,
        quarantine=quarantine,
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
                "trigger_kind": result.get("trigger_kind", "EDGE_CATALOG_EXHAUSTED"),
                "proposal_count": int(result.get("proposal_count") or 0),
                "source_ready_count": int(result.get("source_ready_count") or 0),
                "pool_refill_deficit_count": int(result.get("pool_refill_deficit_count") or 0),
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
