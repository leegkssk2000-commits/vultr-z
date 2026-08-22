#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v3 as v3
from backend.research.architecture_factory import a1_a5_economic_improvement_v4 as v4
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

SCHEMA = "zel.a1_a5_economic_improvement.v5"
ORIGIN = "TREND_RIDER_ORIGINAL_FRESH_ONLINE_EXPANSION"
DEDICATED_EVALUATOR_AXES = {"LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY"}


def _fresh_rows(axes: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = axes.get("trend_rider") if isinstance(axes, Mapping) else None
    if not isinstance(rows, list):
        return []
    return [dict(x) for x in rows if isinstance(x, Mapping) and x.get("origin") == ORIGIN]


def _split_axes(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dedicated = [x for x in rows if str(x.get("axis") or "") in DEDICATED_EVALUATOR_AXES]
    generic = [x for x in rows if str(x.get("axis") or "") not in DEDICATED_EVALUATOR_AXES]
    return dedicated, generic


def _wrap_prompt_v5(original):
    def wrapped(kind, fps, axes, evidence, readiness, prior, selected=None):
        text = original(kind, fps, axes, evidence, readiness, prior, selected)
        marker = "\nCONTEXT="
        if marker not in text:
            return text
        head, raw = text.split(marker, 1)
        try:
            context = json.loads(raw)
        except Exception:
            return text

        context["trend_rider_original_fresh_improvement_contract"] = v4._context_guard()
        fresh = _fresh_rows(axes)
        dedicated, generic = _split_axes(fresh)
        context["trend_rider_original_fresh_all_remaining_axes"] = [str(x.get("axis") or "") for x in fresh]
        context["trend_rider_dedicated_evaluator_pending_axes"] = [str(x.get("axis") or "") for x in dedicated]
        context["trend_rider_generic_dsl_priority_axes"] = [str(x.get("axis") or "") for x in generic]

        constraints = context.setdefault("constraints", {})
        constraints["trend_rider_candidate_must_not_claim_delayed_fill_or_long_only_as_original_baseline"] = True
        constraints["same_baseline_numeric_improvement_claim_requires_direct_ab_receipt"] = True
        constraints["trend_rider_long_short_capital_axis_requires_dedicated_evaluator"] = True

        if generic:
            chosen = dict(generic[0])
            allowed = context.get("allowed_untried_axes_by_strategy")
            if isinstance(allowed, Mapping):
                narrowed = {str(k): v for k, v in allowed.items()}
                narrowed["trend_rider"] = [chosen]
                context["allowed_untried_axes_by_strategy"] = narrowed
            context["trend_rider_generic_dsl_exact_next_axis"] = str(chosen.get("axis") or "")
            constraints["trend_rider_candidate_must_use_exact_generic_dsl_next_axis"] = True

        return head + marker + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return wrapped


def _candidate_axes(result: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("initial_candidates", "second_step_candidates"):
        for row in result.get(key) or []:
            if not isinstance(row, Mapping) or str(row.get("strategy_id") or "") != "trend_rider":
                continue
            axis = str(row.get("changed_axis") or "")
            if axis and axis not in out:
                out.append(axis)
    return out


def run(output: Path) -> dict[str, Any]:
    doc = v4._supplemental()
    readiness_before = v3.v1.source_readiness()
    ready_before = v4._supplemental_axes(doc, readiness_before)
    prior_doc = v3._read(v3.LATEST)
    prior_map = v3._economic_prior_attempts(v3.v1.a5_order(v3.v1.contract()))
    prior_trend = set(prior_map.get("trend_rider") or [])
    pre_remaining = [x for x in ready_before if str(x.get("axis") or "") not in prior_trend]
    _, pre_generic = _split_axes(pre_remaining)
    expected_axis = str(pre_generic[0].get("axis") or "") if pre_generic else None

    old_wrap = v4._wrap_prompt
    try:
        v4._wrap_prompt = _wrap_prompt_v5
        result = dict(v4.run(output))
    finally:
        v4._wrap_prompt = old_wrap

    observed = _candidate_axes(result)
    wrong = [x for x in observed if x in {str(r.get("axis") or "") for r in pre_generic} and expected_axis and x != expected_axis]
    if wrong:
        raise RuntimeError(f"TREND_RIDER_GENERIC_PRIORITY_VIOLATION:expected={expected_axis}:observed={','.join(wrong)}")

    attempted = set(((result.get("economic_attempted_axes") or {}).get("trend_rider") or []))
    readiness = result.get("source_history_readiness") or {}
    ready = v4._supplemental_axes(doc, readiness if isinstance(readiness, Mapping) else {})
    remaining = [x for x in ready if str(x.get("axis") or "") not in attempted]
    dedicated_remaining, generic_remaining = _split_axes(remaining)
    tr = dict(result.get("trend_rider_original_fresh_online_expansion") or {})
    tr.update({
        "priority_selection_enforced": True,
        "generic_dsl_expected_axis_this_run": expected_axis,
        "generic_dsl_candidate_axes_this_run": observed,
        "generic_dsl_next_axis": str(generic_remaining[0].get("axis") or "") if generic_remaining else None,
        "generic_dsl_remaining_axes": [str(x.get("axis") or "") for x in generic_remaining],
        "dedicated_evaluator_pending_axes": [str(x.get("axis") or "") for x in dedicated_remaining],
        "long_short_capital_axis_route": "DEDICATED_EVALUATOR_REQUIRED_NOT_GENERIC_DSL",
        "direct_same_baseline_ab_receipt_present": False,
        "numeric_improvement_vs_59pct_baseline_claim_allowed": False,
        "next_required_proof": "DEVELOPMENT_PASS_THEN_DIRECT_SAME_ORIGINAL_FRESH_W123_PARENT_CHILD_AB_RECEIPT",
    })
    result["trend_rider_original_fresh_online_expansion"] = tr
    result["schema_version"] = SCHEMA
    result.setdefault("policy", {})["trend_rider_original_fresh_generic_axis_priority_enforced"] = True
    result["policy"]["trend_rider_long_short_capital_axis_requires_dedicated_evaluator"] = True
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    def fake(kind, fps, axes, evidence, readiness, prior, selected=None):
        return "HEAD\nCONTEXT=" + json.dumps({"allowed_untried_axes_by_strategy": axes, "constraints": {}}, separators=(",", ":"))

    axes = {
        "trend_rider": [
            {"axis": "LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY", "origin": ORIGIN},
            {"axis": "MULTIHORIZON_TREND_CONSENSUS_ONLY", "origin": ORIGIN},
            {"axis": "MOMENTUM_CONFIRMATION_OWNER_ONLY", "origin": ORIGIN},
            {"axis": "MULTISPEED_TREND_OWNER_ONLY"},
        ],
        "break_and_continue": [{"axis": "X"}],
    }
    text = _wrap_prompt_v5(fake)("INITIAL_A5_REPAIR_BATCH", [], axes, [], {}, {}, None)
    ctx = json.loads(text.split("\nCONTEXT=", 1)[1])
    tr = ctx["allowed_untried_axes_by_strategy"]["trend_rider"]
    assert [x["axis"] for x in tr] == ["MULTIHORIZON_TREND_CONSENSUS_ONLY"]
    assert ctx["trend_rider_dedicated_evaluator_pending_axes"] == ["LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY"]
    assert ctx["constraints"]["trend_rider_candidate_must_use_exact_generic_dsl_next_axis"] is True
    assert DEDICATED_EVALUATOR_AXES == {"LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY"}
    assert v3.AUTH["execution_authority"] == "NONE" and v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V5_SELF_TEST")
    print("PASS_TREND_RIDER_ORIGINAL_FRESH_GENERIC_PRIORITY_GUARD")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v5.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    tr = r["trend_rider_original_fresh_online_expansion"]
    print(json.dumps({
        "state": r.get("state"),
        "development_pass": r.get("development_economic_pass_count"),
        "trend_rider_expected_axis": tr.get("generic_dsl_expected_axis_this_run"),
        "trend_rider_candidate_axes": tr.get("generic_dsl_candidate_axes_this_run"),
        "trend_rider_next_axis": tr.get("generic_dsl_next_axis"),
        "paid": r.get("paid_request_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
