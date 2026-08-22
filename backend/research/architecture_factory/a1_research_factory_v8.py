#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_research_factory_v7 as v7
from backend.research.architecture_factory.a1_research_depth_retry_guard_v1 import audit as depth_audit

ROOT = Path(__file__).resolve().parents[3]
SUPPLEMENT = ROOT / "backend/research/contracts/a1_high_value_evidence_supplement_v1.json"
BLACKLIST = ROOT / "backend/research/contracts/a1_research_mistake_blacklist_v1.json"
ROADMAP = ROOT / "backend/research/contracts/a1_a5_evidence_backed_roadmap_v1.json"
SCHEMA = "zel.a1_research_factory.v8"
_BASE_NORMALIZE = v1.normalize_static_sources


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def normalize_static_sources_v8(mapping: Mapping[str, Any], free: Mapping[str, Any], youtube: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = list(_BASE_NORMALIZE(mapping, free, youtube))
    supplement = _read(SUPPLEMENT)
    for raw in supplement.get("sources") or []:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            continue
        rows.append({**dict(raw), "source_origin": "high_value_curated_supplement"})
    return v1.dedup_sources(rows)


def _roadmap_by_strategy() -> dict[str, dict[str, Any]]:
    roadmap = _read(ROADMAP)
    return {
        str(x.get("strategy_id")): dict(x)
        for x in (roadmap.get("a5_next_axes") or [])
        if isinstance(x, Mapping) and x.get("strategy_id")
    }


def _known_no_effect_axes() -> dict[str, set[str]]:
    bl = _read(BLACKLIST)
    out: dict[str, set[str]] = {}
    for row in bl.get("known_attempts") or []:
        if not isinstance(row, Mapping) or row.get("terminal_class") not in {"NO_EFFECT", "ECONOMIC_FAIL"}:
            continue
        sid = str(row.get("strategy_id") or "")
        axis = str(row.get("axis") or "")
        if sid and "|" not in sid and axis:
            out.setdefault(sid, set()).add(axis)
    # Known alias: the original direct break test names the same relative-volume mechanism two ways.
    if "break_and_continue" in out and "TRADE_FLOW_REL_VOLUME_CONFIRMATION_ONLY" in out["break_and_continue"]:
        out["break_and_continue"].add("RELATIVE_VOLUME_CONFIRMATION_ONLY")
    return out


def _payer_or_source_defect(candidate: Mapping[str, Any]) -> list[str]:
    defects: list[str] = []
    text = " ".join(str(candidate.get(k) or "") for k in ("mechanism", "payer", "entry_event", "why_distinct")).lower()
    required = {str(x) for x in (candidate.get("required_sources") or [])}
    if "liquidity providers pay" in text or "liquidity provider pays" in text or "providers pay via spread" in text:
        defects.append("MICROSTRUCTURE_PAYER_INVERSION")
    micro_terms = ("order book", "order-book", "adverse selection", "depth", "trade flow", "trade-flow")
    if any(x in text for x in micro_terms) and not ({"l2_order_book", "trade_flow"} & required):
        defects.append("SOURCE_GRANULARITY_MISMATCH")
    return defects


def _candidate_guard(candidate: Mapping[str, Any], roadmap: Mapping[str, Mapping[str, Any]], no_effect: Mapping[str, set[str]]) -> tuple[bool, list[str], bool]:
    sid = str(candidate.get("strategy_id") or "")
    axis = str(candidate.get("changed_axis") or candidate.get("axis") or "")
    reasons: list[str] = []
    if axis in no_effect.get(sid, set()):
        reasons.append("TERMINAL_SAME_IDENTITY_RETRY")
    if int(candidate.get("independent_rejects") or 0) > 0:
        reasons.append("EXPLICIT_REVIEW_REJECT")
    if int(candidate.get("independent_passes") or 0) < 2:
        reasons.append("REVIEW_QUORUM_MISSING")
    if candidate.get("source_gate") != "READY_COMMON":
        reasons.append("SOURCE_GATE_NOT_READY")
    if len({str(x) for x in (candidate.get("evidence_ids") or []) if str(x)}) < 3:
        reasons.append("EVIDENCE_SUPPORT_LT3")
    reasons.extend(_payer_or_source_defect(candidate))

    plan = roadmap.get(sid) or {}
    expected = str(plan.get("next_axis") or "")
    aligned = axis == expected
    if sid == "break_and_continue" and axis == "LIQUIDITY_REGIME_OWNER_ONLY" and expected == "OHLCV_ACTIVITY_LIQUIDITY_PROXY_OWNER_ONLY":
        # Only allow this contract alias when the mechanism stays an observable OHLCV/activity proxy
        # and does not make L2/adverse-selection claims.
        aligned = not _payer_or_source_defect(candidate)
    return not reasons, reasons, aligned


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = 5) -> dict[str, Any]:
    depth = depth_audit()
    if depth.get("state") != "PASS_RESEARCH_DEPTH_RETRY_GUARD":
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_RESEARCH_FACTORY_V8_DEPTH_GUARD",
            "depth_retry_guard": depth,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
        }
        result["receipt_sha256"] = v1.sha(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return result

    old_normalize = v1.normalize_static_sources
    try:
        v1.normalize_static_sources = normalize_static_sources_v8
        result = dict(v7.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v1.normalize_static_sources = old_normalize

    roadmap = _roadmap_by_strategy()
    no_effect = _known_no_effect_axes()
    guarded_queue: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for raw in result.get("experiment_queue") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        eligible, reasons, aligned = _candidate_guard(row, roadmap, no_effect)
        row["v8_guard_pass"] = eligible
        row["v8_guard_reasons"] = reasons
        row["v8_roadmap_aligned"] = aligned
        diagnostics.append({
            "strategy_id": row.get("strategy_id"),
            "candidate_id": row.get("candidate_id"),
            "axis": row.get("changed_axis") or row.get("axis"),
            "guard_pass": eligible,
            "roadmap_aligned": aligned,
            "reasons": reasons,
        })
        if eligible:
            guarded_queue.append(row)

    aligned = [x for x in guarded_queue if x.get("v8_roadmap_aligned") is True]
    aligned.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("strategy_id") or ""), str(x.get("candidate_id") or "")))
    guarded_queue.sort(key=lambda x: (x.get("v8_roadmap_aligned") is not True, -float(x.get("score") or 0), str(x.get("strategy_id") or "")))

    result["schema_version"] = SCHEMA
    result["depth_retry_guard"] = depth
    result["high_value_supplement_bound"] = True
    result["terminal_retry_guard_bound"] = True
    result["candidate_guard_diagnostics"] = diagnostics[:100]
    result["experiment_queue"] = guarded_queue[:100]
    result["experiment_queue_count"] = len(result["experiment_queue"])
    result["roadmap_aligned_queue_count"] = len(aligned)
    result["next_experiment_candidate"] = aligned[0] if aligned else None
    result["state"] = "PASS_RESEARCH_FACTORY_V8_DEPTH_RETRY_SAFE_READY" if aligned else "HOLD_RESEARCH_FACTORY_V8_NO_ROADMAP_ALIGNED_CANDIDATE"
    result["policy"]["minimum_candidate_evidence_documents"] = 3
    result["policy"]["known_terminal_same_identity_retry_forbidden"] = True
    result["policy"]["source_granularity_must_match_mechanism"] = True
    result["policy"]["microstructure_payer_inversion_rejected"] = True
    result["policy"]["roadmap_aligned_candidate_preferred_for_heavy_replay"] = True
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    depth = depth_audit()
    assert depth["state"] == "PASS_RESEARCH_DEPTH_RETRY_GUARD", depth
    roadmap = _roadmap_by_strategy()
    no_effect = _known_no_effect_axes()
    fake_bad = {
        "strategy_id": "break_and_continue", "changed_axis": "RELATIVE_VOLUME_CONFIRMATION_ONLY",
        "source_gate": "READY_COMMON", "independent_passes": 2, "independent_rejects": 0,
        "evidence_ids": ["R3", "R4", "HV6"], "required_sources": ["ohlcv", "volume"],
        "mechanism": "relative volume confirmation",
    }
    ok, reasons, _ = _candidate_guard(fake_bad, roadmap, no_effect)
    assert not ok and "TERMINAL_SAME_IDENTITY_RETRY" in reasons
    fake_micro = {
        "strategy_id": "keltner_trend", "changed_axis": "LIQUIDITY_REGIME_OWNER_ONLY",
        "source_gate": "READY_COMMON", "independent_passes": 2, "independent_rejects": 0,
        "evidence_ids": ["R4", "HV9", "HV12"], "required_sources": ["ohlcv", "volume"],
        "mechanism": "liquidity providers pay via spread after order book adverse selection",
    }
    ok, reasons, _ = _candidate_guard(fake_micro, roadmap, no_effect)
    assert not ok and "MICROSTRUCTURE_PAYER_INVERSION" in reasons and "SOURCE_GRANULARITY_MISMATCH" in reasons
    print("PASS_A1_RESEARCH_FACTORY_V8_DEPTH_RETRY_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v8.json"))
    p.add_argument("--no-network", action="store_true")
    p.add_argument("--no-ai", action="store_true")
    p.add_argument("--ai-strategy-limit", type=int, default=5)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, network=not args.no_network, ai=not args.no_ai, ai_strategy_limit=max(0, args.ai_strategy_limit))
    print(json.dumps({
        "state": result.get("state"),
        "depth_guard": (result.get("depth_retry_guard") or {}).get("state"),
        "external_sources": result.get("external_source_count"),
        "new_sources": result.get("new_discovered_source_count"),
        "roadmap_aligned_queue": result.get("roadmap_aligned_queue_count"),
        "next": result.get("next_experiment_candidate"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
