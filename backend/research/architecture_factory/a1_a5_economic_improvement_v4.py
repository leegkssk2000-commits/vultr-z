#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v1 as v1
from backend.research.architecture_factory import a1_a5_economic_improvement_v3 as v3
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
SUPPLEMENTAL = ROOT / "backend/research/contracts/a1_trend_rider_online_expansion_v1.json"
SCHEMA = "zel.a1_a5_economic_improvement.v4"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
DELTA_METRICS = [
    "win_rate",
    "net_expectancy_bps",
    "net_pnl_bps",
    "profit_factor",
    "payoff",
    "drawdown_bps",
    "trades",
    "trade_retention_pct",
]


def _supplemental() -> dict[str, Any]:
    value = json.loads(SUPPLEMENTAL.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("TREND_RIDER_SUPPLEMENTAL_OBJECT_REQUIRED")
    if value.get("schema_version") != "zel.a1.trend_rider.online_expansion.v1":
        raise RuntimeError("TREND_RIDER_SUPPLEMENTAL_SCHEMA_MISMATCH")
    if value.get("strategy_id") != "trend_rider":
        raise RuntimeError("TREND_RIDER_SUPPLEMENTAL_STRATEGY_MISMATCH")
    if value.get("baseline_identity") != BASELINE_IDENTITY:
        raise RuntimeError("TREND_RIDER_SUPPLEMENTAL_BASELINE_MISMATCH")
    acceptance = value.get("acceptance_contract") or {}
    if acceptance.get("same_original_fresh_baseline_required") is not True:
        raise RuntimeError("TREND_RIDER_SAME_BASELINE_GUARD_MISSING")
    if acceptance.get("a1_a2_a3_gate_order_preserved") is not True:
        raise RuntimeError("TREND_RIDER_A1_A2_A3_ORDER_GUARD_MISSING")
    return value


def _supplemental_evidence(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in doc.get("external_evidence") or []:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            continue
        out.append({
            "id": str(raw.get("id")),
            "tier": str(raw.get("tier") or "external_primary"),
            "source_type": "TREND_RIDER_ORIGINAL_FRESH_EXTERNAL_EVIDENCE",
            "identifier": str(raw.get("identifier") or ""),
            "title": str(raw.get("title") or ""),
            "claim": str(raw.get("claim_used") or ""),
            "limitations": str(raw.get("limitations") or "Mechanism hypothesis only; numeric parameters are not imported."),
            "allowed_use": [str(x) for x in (raw.get("allowed_use") or [])],
            "baseline_identity": BASELINE_IDENTITY,
            "promotion_authority": False,
        })
    return out


def _ready_sources(readiness: Mapping[str, Any]) -> set[str]:
    ready = {k for k, raw in readiness.items() if isinstance(raw, Mapping) and raw.get("ready") is True}
    ready.update({"ohlcv", "volume"})
    return ready


def _supplemental_axes(doc: Mapping[str, Any], readiness: Mapping[str, Any]) -> list[dict[str, Any]]:
    ready = _ready_sources(readiness)
    out: list[dict[str, Any]] = []
    for raw in doc.get("repair_axes") or []:
        if not isinstance(raw, Mapping):
            continue
        axis = str(raw.get("axis") or "").strip()
        required = {str(x) for x in (raw.get("required_sources") or [])}
        if not axis or not required or not required.issubset(ready):
            continue
        if str(raw.get("source_lane") or "") != "READY_COMMON":
            continue
        out.append({
            "axis": axis,
            "mechanism": str(raw.get("mechanism") or ""),
            "falsification": str(raw.get("falsification") or ""),
            "required_sources": sorted(required),
            "priority": 20000.0 + float(raw.get("priority") or 0),
            "source_lane": "READY_COMMON",
            "external_evidence_ids": [str(x) for x in (raw.get("evidence_ids") or [])],
            "baseline_identity": BASELINE_IDENTITY,
            "origin": "TREND_RIDER_ORIGINAL_FRESH_ONLINE_EXPANSION",
        })
    out.sort(key=lambda x: (-float(x["priority"]), str(x["axis"])))
    return out


def _merge_axes(primary: Mapping[str, list[dict[str, Any]]], supplemental: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out = {str(sid): [dict(x) for x in rows] for sid, rows in primary.items()}
    current = out.setdefault("trend_rider", [])
    best: dict[str, dict[str, Any]] = {str(x.get("axis") or ""): dict(x) for x in current if x.get("axis")}
    for row in supplemental:
        axis = str(row.get("axis") or "")
        old = best.get(axis)
        if old is None or float(row.get("priority") or 0) > float(old.get("priority") or 0):
            best[axis] = dict(row)
    out["trend_rider"] = sorted(best.values(), key=lambda x: (-float(x.get("priority") or 0), str(x.get("axis") or "")))
    return out


def _context_guard() -> dict[str, Any]:
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "same_original_fresh_baseline_required": True,
        "derivative_lineages_not_baseline": [
            "trend_rider_one_bar_delayed_fill_v1",
            "trend_rider_delayed_fill_long_only_v1",
        ],
        "required_delta_metrics": DELTA_METRICS,
        "win_rate_is_not_standalone_acceptance_target": True,
        "one_axis_per_generation": True,
        "a1_a2_a3_gate_order_preserved": True,
        "fresh_prospective_validation_required": True,
    }


def _wrap_prompt(original):
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
        context["trend_rider_original_fresh_improvement_contract"] = _context_guard()
        tr_axes = axes.get("trend_rider") if isinstance(axes, Mapping) else None
        if isinstance(tr_axes, list):
            prioritized = [
                str(x.get("axis") or "")
                for x in tr_axes
                if isinstance(x, Mapping) and x.get("origin") == "TREND_RIDER_ORIGINAL_FRESH_ONLINE_EXPANSION"
            ]
            context["trend_rider_original_fresh_priority_axes"] = prioritized
            context.setdefault("constraints", {})["trend_rider_must_prefer_first_available_original_fresh_priority_axis"] = True
            context["constraints"]["trend_rider_candidate_must_not_claim_delayed_fill_or_long_only_as_original_baseline"] = True
            context["constraints"]["same_baseline_numeric_improvement_claim_requires_direct_ab_receipt"] = True
        return head + marker + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return wrapped


def run(output: Path) -> dict[str, Any]:
    doc = _supplemental()
    original_allowed_axes = v1.allowed_axes
    original_contract_evidence = v1.contract_evidence
    original_prompt = v3._prompt

    def allowed_axes_with_original_fresh(c: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
        primary = original_allowed_axes(c, readiness)
        return _merge_axes(primary, _supplemental_axes(doc, readiness))

    def contract_evidence_with_original_fresh(c: Mapping[str, Any]) -> list[dict[str, Any]]:
        primary = original_contract_evidence(c)
        seen = {str(x.get("id") or "") for x in primary}
        for row in _supplemental_evidence(doc):
            if row["id"] not in seen:
                primary.append(row)
                seen.add(row["id"])
        return primary

    try:
        v1.allowed_axes = allowed_axes_with_original_fresh
        v1.contract_evidence = contract_evidence_with_original_fresh
        v3._prompt = _wrap_prompt(original_prompt)
        result = dict(v3.run(output))
    finally:
        v1.allowed_axes = original_allowed_axes
        v1.contract_evidence = original_contract_evidence
        v3._prompt = original_prompt

    readiness = result.get("source_history_readiness") or {}
    supplemental_ready = _supplemental_axes(doc, readiness if isinstance(readiness, Mapping) else {})
    allowed = result.get("allowed_axes_by_strategy") or {}
    trend_allowed = allowed.get("trend_rider") if isinstance(allowed, Mapping) else []
    trend_allowed = trend_allowed if isinstance(trend_allowed, list) else []
    consumed_axes = [
        str(x.get("axis") or "")
        for x in trend_allowed
        if isinstance(x, Mapping) and x.get("origin") == "TREND_RIDER_ORIGINAL_FRESH_ONLINE_EXPANSION"
    ]

    result["schema_version"] = SCHEMA
    result["trend_rider_original_fresh_online_expansion"] = {
        **_context_guard(),
        "external_evidence_count": len(_supplemental_evidence(doc)),
        "registered_axis_count": len(doc.get("repair_axes") or []),
        "ready_common_axis_count": len(supplemental_ready),
        "ready_common_axes": [str(x.get("axis") or "") for x in supplemental_ready],
        "economic_consumer_axis_count": len(consumed_axes),
        "economic_consumer_axes": consumed_axes,
        "consumer_connected": bool(consumed_axes),
        "direct_same_baseline_ab_receipt_present": False,
        "numeric_improvement_vs_59pct_baseline_claim_allowed": False,
        "next_required_proof": "DIRECT_SAME_ORIGINAL_FRESH_W123_PARENT_CHILD_AB_RECEIPT",
    }
    result.setdefault("policy", {})["trend_rider_original_fresh_online_expansion_consumed"] = True
    result["policy"]["same_original_fresh_baseline_required_for_59pct_improvement_claim"] = True
    result["policy"]["delayed_fill_or_long_only_cannot_substitute_for_original_fresh_baseline"] = True
    result["policy"]["a1_a2_a3_gate_order_preserved"] = True
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
    doc = _supplemental()
    evidence = _supplemental_evidence(doc)
    readiness = {"ohlcv": {"ready": True}, "volume": {"ready": True}, "funding": {"ready": False}, "open_interest": {"ready": False}}
    axes = _supplemental_axes(doc, readiness)
    names = [str(x["axis"]) for x in axes]
    assert doc["baseline_identity"] == BASELINE_IDENTITY
    assert len(evidence) >= 4
    assert names[:5] == [
        "LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY",
        "MULTIHORIZON_TREND_CONSENSUS_ONLY",
        "MOMENTUM_CONFIRMATION_OWNER_ONLY",
        "EMA_SLOPE_REVERSAL_EXIT_ONLY",
        "VOLATILITY_ADAPTIVE_TRAIL_ONLY",
    ], names
    assert "FUNDING_SENTIMENT_CONTEXT_ONLY" not in names
    assert "OI_CONFIRMATION_CONTEXT_ONLY" not in names
    merged = _merge_axes({"trend_rider": [{"axis": "OLD", "priority": 1.0}]}, axes)
    assert merged["trend_rider"][0]["axis"] == "LONG_SHORT_ASYMMETRIC_CAPITAL_ONLY"
    guard = _context_guard()
    assert guard["same_original_fresh_baseline_required"] is True
    assert guard["a1_a2_a3_gate_order_preserved"] is True
    assert "win_rate" in guard["required_delta_metrics"] and "drawdown_bps" in guard["required_delta_metrics"]
    assert v3.AUTH["execution_authority"] == "NONE" and v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V4_SELF_TEST")
    print("PASS_TREND_RIDER_ORIGINAL_FRESH_59PCT_CONSUMER_BINDING")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v4.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    tr = result["trend_rider_original_fresh_online_expansion"]
    print(json.dumps({
        "state": result.get("state"),
        "development_pass": result.get("development_economic_pass_count"),
        "trend_rider_original_fresh": tr,
        "paid": result.get("paid_request_count"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
