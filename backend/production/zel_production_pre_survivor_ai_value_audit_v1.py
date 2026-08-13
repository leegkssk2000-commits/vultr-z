from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_improvement_controller_v1 import stable_sha

SCHEMA = "zel.production_pre_survivor_ai_value_audit.v1"
EVENT_SCHEMA = "zel.production_pre_survivor_ai_value_event.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_ai_value_audit_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_ai_value_audit_v1.json")
METRIC_KEYS = ("trade_count", "win_rate_pct", "net_expectancy", "profit_factor", "net_pnl", "max_dd_pct")


def safety() -> dict[str, Any]:
    return {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }


def authority_guard(row: Mapping[str, Any], prefix: str) -> None:
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
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_NON_PAPER_FORBIDDEN")
    if policy.get("value_role") != "OBSERVER_ONLY_REALIZED_RESEARCH_VALUE_NOT_ROUTE":
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_ROLE_DRIFT")
    required = ("next_hypothesis_path", "comparison_path", "incumbent_path", "history_path", "output_path")
    paths = []
    for key in required:
        value = str(policy.get(key) or "").strip()
        if not value:
            raise RuntimeError(f"PRE_SURVIVOR_AI_VALUE_PATH_MISSING:{key}")
        paths.append(value)
    if len(paths) != len(set(paths)):
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_PATH_COLLISION")
    authority_guard(policy, "PRE_SURVIVOR_AI_VALUE_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_MUTATION_FORBIDDEN")
    return dict(policy)


def finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"PRE_SURVIVOR_AI_VALUE_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"PRE_SURVIVOR_AI_VALUE_NUMERIC_NONFINITE:{label}")
    return out


def preferred_rows(comparison: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = comparison.get("comparisons")
    if not isinstance(rows, list):
        rows = [comparison] if comparison.get("research_preference") else []
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping) or raw.get("research_preference") != "CHALLENGER_RESEARCH_PREFERRED":
            continue
        delta = raw.get("delta_challenger_minus_reference")
        if not isinstance(delta, Mapping):
            raise RuntimeError("PRE_SURVIVOR_AI_VALUE_PREFERRED_DELTA_MISSING")
        item = {key: finite(delta.get(key), key) for key in METRIC_KEYS}
        item["challenger_family_id"] = str(raw.get("challenger_family_id") or "")
        out.append(item)
    return out


def build_event(
    policy: Mapping[str, Any],
    *,
    next_hypothesis: Mapping[str, Any],
    comparison: Mapping[str, Any],
    incumbent: Mapping[str, Any] | None,
) -> dict[str, Any]:
    validate_policy(policy)
    authority_guard(next_hypothesis, "PRE_SURVIVOR_AI_VALUE_NEXT_HYPOTHESIS")
    authority_guard(comparison, "PRE_SURVIVOR_AI_VALUE_COMPARISON")
    if isinstance(incumbent, Mapping):
        authority_guard(incumbent, "PRE_SURVIVOR_AI_VALUE_INCUMBENT")
    next_receipt = str(next_hypothesis.get("receipt_sha256") or "")
    comparison_receipt = str(comparison.get("receipt_sha256") or "")
    incumbent_receipt = str(incumbent.get("receipt_sha256") or "") if isinstance(incumbent, Mapping) else ""
    if not next_receipt or not comparison_receipt:
        raise RuntimeError("PRE_SURVIVOR_AI_VALUE_SOURCE_RECEIPT_MISSING")
    preferred = preferred_rows(comparison)
    fingerprint = stable_sha({
        "next_hypothesis_receipt_sha256": next_receipt,
        "comparison_receipt_sha256": comparison_receipt,
        "incumbent_receipt_sha256": incumbent_receipt,
        "provider": str(next_hypothesis.get("provider") or ""),
        "model": str(next_hypothesis.get("model") or ""),
        "current_family_id": str(next_hypothesis.get("current_family_id") or ""),
    })
    event = {
        "schema_version": EVENT_SCHEMA,
        "event_fingerprint_sha256": fingerprint,
        "provider": str(next_hypothesis.get("provider") or ""),
        "model": str(next_hypothesis.get("model") or ""),
        "current_family_id": str(next_hypothesis.get("current_family_id") or ""),
        "ai_call_made": bool(next_hypothesis.get("ai_call_made")),
        "ai_call_succeeded": bool(next_hypothesis.get("ai_call_succeeded")),
        "proposal_count": int(next_hypothesis.get("proposal_count") or 0),
        "source_ready_count": int(next_hypothesis.get("source_ready_count") or 0),
        "template_ready_count": int(next_hypothesis.get("template_ready_count") or 0),
        "comparison_count": int(comparison.get("comparison_count") or 0),
        "preferred_challenger_count": len(preferred),
        "preferred_challenger_family_ids": [str(row["challenger_family_id"]) for row in preferred],
        "preferred_deltas": preferred,
        "incumbent_family_id": str(incumbent.get("family_id") or "") if isinstance(incumbent, Mapping) else "",
        "incumbent_generation": int(incumbent.get("generation") or 0) if isinstance(incumbent, Mapping) else 0,
        "next_hypothesis_receipt_sha256": next_receipt,
        "comparison_receipt_sha256": comparison_receipt,
        "incumbent_receipt_sha256": incumbent_receipt,
        "attribution_scope": "AI_GENERATED_CHALLENGER_ASSOCIATED_RESEARCH_VALUE_NOT_CAUSAL_PNL_ATTRIBUTION",
        **safety(),
    }
    event["receipt_sha256"] = stable_sha(event)
    return event


def aggregate(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(history)
    success = sum(bool(row.get("ai_call_succeeded")) for row in rows)
    preferred_epochs = sum(int(row.get("preferred_challenger_count") or 0) > 0 for row in rows)
    preferred_count = sum(int(row.get("preferred_challenger_count") or 0) for row in rows)
    sums = {key: 0.0 for key in METRIC_KEYS}
    samples = 0
    models: dict[str, dict[str, int]] = {}
    for row in rows:
        model_key = f"{str(row.get('provider') or 'UNKNOWN')}:{str(row.get('model') or 'UNKNOWN')}"
        slot = models.setdefault(model_key, {"epochs": 0, "successful_calls": 0, "preferred_epochs": 0, "preferred_challengers": 0})
        slot["epochs"] += 1
        slot["successful_calls"] += int(bool(row.get("ai_call_succeeded")))
        slot["preferred_epochs"] += int(int(row.get("preferred_challenger_count") or 0) > 0)
        slot["preferred_challengers"] += int(row.get("preferred_challenger_count") or 0)
        for delta in row.get("preferred_deltas") or []:
            if not isinstance(delta, Mapping):
                continue
            samples += 1
            for key in METRIC_KEYS:
                sums[key] += float(delta.get(key) or 0.0)
    source_ready = sum(int(row.get("source_ready_count") or 0) for row in rows)
    return {
        "generation_count": len(rows),
        "ai_call_made_count": sum(bool(row.get("ai_call_made")) for row in rows),
        "ai_call_succeeded_count": success,
        "proposal_count_total": sum(int(row.get("proposal_count") or 0) for row in rows),
        "source_ready_count_total": source_ready,
        "template_ready_count_total": sum(int(row.get("template_ready_count") or 0) for row in rows),
        "comparison_count_total": sum(int(row.get("comparison_count") or 0) for row in rows),
        "preferred_challenger_count": preferred_count,
        "preferred_epoch_count": preferred_epochs,
        "preferred_epoch_rate_pct": 100.0 * preferred_epochs / len(rows) if rows else 0.0,
        "source_ready_per_successful_call": source_ready / success if success else 0.0,
        "preferred_challenger_per_successful_call": preferred_count / success if success else 0.0,
        "preferred_delta_sample_count": samples,
        "preferred_delta_sum": sums,
        "preferred_delta_average": {key: sums[key] / samples if samples else 0.0 for key in METRIC_KEYS},
        "model_breakdown": models,
    }


def audit_tick(
    policy: Mapping[str, Any],
    *,
    next_hypothesis: Mapping[str, Any],
    comparison: Mapping[str, Any],
    incumbent: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    try:
        event = build_event(cfg, next_hypothesis=next_hypothesis, comparison=comparison, incumbent=incumbent)
    except Exception as exc:
        out = {"schema_version": SCHEMA, "state": "HOLD_PRE_SURVIVOR_AI_VALUE_SOURCE_INVALID", "value_role": cfg["value_role"], "error_class": type(exc).__name__, "error_code": str(exc)[:500], "history_append_required": False, "attribution_scope": "AI_GENERATED_CHALLENGER_ASSOCIATED_RESEARCH_VALUE_NOT_CAUSAL_PNL_ATTRIBUTION", **safety()}
        out["receipt_sha256"] = stable_sha(out)
        return out, None
    seen = {str(row.get("event_fingerprint_sha256") or "") for row in history}
    append_required = event["event_fingerprint_sha256"] not in seen
    effective = list(history) + ([event] if append_required else [])
    if not event["ai_call_succeeded"]:
        state = "HOLD_PRE_SURVIVOR_AI_VALUE_AI_CALL_NOT_SUCCESSFUL"
    elif event["comparison_count"] <= 0:
        state = "HOLD_PRE_SURVIVOR_AI_VALUE_COMPARISON_NOT_READY"
    elif event["preferred_challenger_count"] > 0:
        state = "PASS_PRE_SURVIVOR_AI_VALUE_POSITIVE_RESEARCH_SIGNAL"
    else:
        state = "HOLD_PRE_SURVIVOR_AI_VALUE_NOT_YET_DEMONSTRATED"
    out = {"schema_version": SCHEMA, "state": state, "value_role": cfg["value_role"], "current_event_fingerprint_sha256": event["event_fingerprint_sha256"], "history_append_required": append_required, "aggregate": aggregate(effective), "attribution_scope": event["attribution_scope"], **safety()}
    out["receipt_sha256"] = stable_sha(out)
    return out, event if append_required else None


def self_test() -> None:
    policy = {"schema_version": POLICY_SCHEMA, "mode": "PAPER", "value_role": "OBSERVER_ONLY_REALIZED_RESEARCH_VALUE_NOT_ROUTE", "next_hypothesis_path": "/tmp/n", "comparison_path": "/tmp/c", "incumbent_path": "/tmp/i", "history_path": "/tmp/h", "output_path": "/tmp/o", "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "source_code_mutation_allowed": False, "self_modification_allowed": False}
    safe = safety()
    nxt = {"receipt_sha256": "n1", "provider": "GEMINI", "model": "fixture", "current_family_id": "f0", "ai_call_made": True, "ai_call_succeeded": True, "proposal_count": 1, "source_ready_count": 1, "template_ready_count": 1, **safe}
    comp = {"receipt_sha256": "c1", "comparison_count": 1, "comparisons": [{"research_preference": "CHALLENGER_RESEARCH_PREFERRED", "challenger_family_id": "f1", "delta_challenger_minus_reference": {"trade_count": 1, "win_rate_pct": 2.0, "net_expectancy": 0.1, "profit_factor": 0.2, "net_pnl": 1.5, "max_dd_pct": -0.4}}], **safe}
    inc = {"receipt_sha256": "i1", "family_id": "f1", "generation": 2, **safe}
    out, event = audit_tick(policy, next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[])
    assert out["state"] == "PASS_PRE_SURVIVOR_AI_VALUE_POSITIVE_RESEARCH_SIGNAL"
    assert event is not None and out["aggregate"]["preferred_challenger_count"] == 1
    out2, event2 = audit_tick(policy, next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[event])
    assert event2 is None and out2["aggregate"]["generation_count"] == 1
    bad = dict(nxt); bad["execution_authority"] = "LIVE"
    held, _ = audit_tick(policy, next_hypothesis=bad, comparison=comp, incumbent=inc, history=[])
    assert held["state"] == "HOLD_PRE_SURVIVOR_AI_VALUE_SOURCE_INVALID"
    print("PASS_PRE_SURVIVOR_AI_VALUE_AUDIT")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--self-test", action="store_true")
    ns = ap.parse_args(argv)
    if ns.self_test:
        self_test()
        return 0
    raise SystemExit("STATIC_ONLY_NOT_RUNTIME_WIRED")


if __name__ == "__main__":
    raise SystemExit(main())
