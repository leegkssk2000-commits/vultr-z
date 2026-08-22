#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_research_factory_v2 as v2
import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af

SCHEMA = "zel.a1_research_factory.v3"
COMMON_READY = {"ohlcv", "volume"}
_READY_BY_STRATEGY: dict[str, list[dict[str, Any]]] = {}


def strict_priority_targets(
    ledger: Mapping[str, Any], strategy_ids: list[str], backlogs: Mapping[str, Any], limit: int
) -> list[str]:
    global _READY_BY_STRATEGY
    _READY_BY_STRATEGY = {}
    for sid in strategy_ids:
        rows = backlogs.get(sid) if isinstance(backlogs, Mapping) else []
        ready = []
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                if raw.get("origin") == "SEALED_EXACT25_AXIS":
                    continue
                if raw.get("source_gate") != "READY_COMMON":
                    continue
                axis = str(raw.get("axis") or "").strip()
                if not axis:
                    continue
                ready.append(dict(raw))
        ready.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("axis") or "")))
        _READY_BY_STRATEGY[sid] = ready[:5]
    return v2.priority_targets(ledger, strategy_ids, backlogs, limit)


def repair_prompt(strategy_id: str, ledger_row: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> tuple[str, set[str], set[str]]:
    evidence = v2.compact_evidence(evidence_rows)
    source_ids = {str(x.get("id")) for x in evidence if x.get("id")}
    ready_rows = _READY_BY_STRATEGY.get(strategy_id) or []
    allowed_axes = {str(x.get("axis") or "").strip() for x in ready_rows if str(x.get("axis") or "").strip()}
    if not allowed_axes:
        raise RuntimeError("NO_READY_COMMON_AXIS_FOR_STRICT_REPAIR")
    context = {
        "objective": "Convert an existing source-ready backlog axis into one exact-strategy REPAIR candidate for deterministic replay.",
        "strategy_id": strategy_id,
        "verified_round_trip_cost_bps_reference": float(ledger_row.get("verified_pretrade_cost_bps") or 14.0),
        "current_strategy_state": {
            "status": ledger_row.get("status"),
            "completed_trades": ledger_row.get("completed_trades"),
            "gross_expectancy_bps": ledger_row.get("gross_expectancy_bps"),
            "net_expectancy_bps": ledger_row.get("net_expectancy_bps"),
            "profit_factor": ledger_row.get("profit_factor"),
            "drawdown_bps": ledger_row.get("drawdown_bps"),
        },
        "allowed_ready_common_axes": [
            {
                "axis": x.get("axis"),
                "mechanism": x.get("mechanism"),
                "required_sources": x.get("required_sources"),
                "source_ids": x.get("source_ids"),
                "score": x.get("score"),
            }
            for x in ready_rows[:3]
        ],
        "external_evidence": evidence,
        "hard_constraints": {
            "mode_must_equal": "REPAIR",
            "strategy_id_must_equal": strategy_id,
            "changed_axis_must_be_exactly_one_of": sorted(allowed_axes),
            "new_architecture_forbidden": True,
            "required_sources_must_be_subset_of": ["ohlcv", "volume"],
            "threshold_sweep": False,
            "best_horizon_cherry_pick": False,
            "fee_reduction": False,
            "sealed_holdout_visibility": False,
            "post_outcome_loss_deletion": False,
        },
    }
    contract = af.generator_contract()
    prompt = (
        f"STRICT READY_COMMON REPAIR ROUTE for strategy {strategy_id}. "
        "Generate exactly 3 candidates. Every candidate MUST have mode=REPAIR, MUST use the exact strategy_id supplied, "
        "MUST change exactly one axis copied verbatim from allowed_ready_common_axes, and MUST require only ohlcv and/or volume. "
        "NEW_ARCHITECTURE, strategy_id=NEW, changed_axis=none, additional axes, numeric threshold tuning, and holdout access are forbidden. "
        "Return JSON only matching this shape: "
        + json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\nCONTEXT="
        + json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return prompt, source_ids, allowed_axes


def strict_ai_scout(strategy_id: str, ledger_row: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = v2.compact_evidence(evidence_rows)
    prompt, source_ids, allowed_axes = repair_prompt(strategy_id, ledger_row, evidence_rows)
    generated: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}
    for provider, fn in (("openai", af.call_openai_generator), ("groq", v2.call_groq_compact)):
        try:
            model, raw, lineage = fn(prompt)
            got = af.validate_candidates(raw, provider, source_ids, {strategy_id})
            got = [
                x for x in got
                if x.get("mode") == "REPAIR"
                and x.get("strategy_id") == strategy_id
                and str(x.get("changed_axis") or "") in allowed_axes
                and set(x.get("required_sources") or []).issubset(COMMON_READY)
            ]
            providers[provider] = {
                "successful": True,
                "model": model,
                **lineage,
                "candidate_count": len(got),
                "strict_repair_only": True,
            }
            generated.extend(got)
        except Exception as exc:  # noqa: BLE001
            providers[provider] = {"successful": False, "error": af.safe_error(exc), "strict_repair_only": True}

    generated = af.dedup(sorted(generated, key=lambda x: -af.base_score(x)), v1.DEDUP_THRESHOLD)[:3]
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix=f"a1-rf-v3-{strategy_id}-") as td:
        root = Path(td)
        for idx, candidate in enumerate(generated):
            work = root / str(idx)
            work.mkdir()
            reviews: dict[str, Any] = {}
            try:
                reviews["openai"] = af.openai_critic(candidate)
            except Exception as exc:  # noqa: BLE001
                reviews["openai"] = {"successful": False, "error": af.safe_error(exc)}
            reviews["groq"] = af.subprocess_review("scripts/strategy11_groq_redteam.py", candidate, work, env, "groq")
            reviews["workers_ai"] = af.subprocess_review("scripts/strategy11_workers_ai_guard.py", candidate, work, env, "workers")
            passes = rejects = 0
            for name, review in reviews.items():
                if name == candidate.get("provider"):
                    continue
                decision = str(review.get("decision") or "")
                if review.get("successful") and decision in {"PASS", "PASS_TO_REPLAY"}:
                    passes += 1
                if review.get("successful") and decision == "REJECT":
                    rejects += 1
            reviewed.append({
                **candidate,
                "cross_reviews": reviews,
                "independent_passes": passes,
                "independent_rejects": rejects,
                "score": round(af.base_score(candidate) + passes * 2.5 - rejects * 4.0, 4),
                "source_gate": "READY_COMMON",
                "eligible_for_experiment_queue": passes >= 2 and rejects == 0,
                "strict_repair_identity": True,
            })
    reviewed.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("candidate_id") or "")))
    return {
        "strategy_id": strategy_id,
        "providers": providers,
        "reviewed": reviewed[:3],
        "compact_evidence_count": len(evidence),
        "groq_max_tokens": v2.GROQ_MAX_TOKENS,
        "allowed_ready_common_axes": sorted(allowed_axes),
        "strict_repair_only": True,
    }


def reviewed_bridge(ai_results: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid, block in ai_results.items():
        if not isinstance(block, Mapping):
            continue
        for raw in block.get("reviewed") or []:
            if not isinstance(raw, Mapping):
                continue
            if raw.get("eligible_for_experiment_queue") is not True:
                continue
            if raw.get("source_gate") != "READY_COMMON":
                continue
            if raw.get("mode") != "REPAIR" or raw.get("strategy_id") != sid:
                continue
            row = dict(raw)
            row["strategy_id"] = sid
            row["origin"] = "MULTI_AI_SCOUT_STRICT_REPAIR"
            row["status"] = "AI_REVIEWED_READY_COMMON"
            out.append(row)
    out.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("strategy_id") or ""), str(x.get("candidate_id") or "")))
    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        key = str(row.get("candidate_sha256") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        dedup.append(row)
    return dedup


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = v1.AI_STRATEGY_LIMIT) -> dict[str, Any]:
    old_priority, old_scout = v1.priority_targets, v1.ai_scout
    try:
        v1.priority_targets = strict_priority_targets
        v1.ai_scout = strict_ai_scout
        result = dict(v1.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v1.priority_targets = old_priority
        v1.ai_scout = old_scout

    direct = reviewed_bridge(result.get("ai_scout_results") or {})
    existing = [x for x in (result.get("experiment_queue") or []) if isinstance(x, Mapping)]
    seen = {str(x.get("candidate_sha256") or "") for x in direct if x.get("candidate_sha256")}
    merged = list(direct)
    for row in existing:
        key = str(row.get("candidate_sha256") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(dict(row))
    result["experiment_queue"] = merged[:100]
    result["experiment_queue_count"] = len(merged[:100])
    result["reviewed_ready_common_count"] = len(direct)
    result["ready_common_queue_count"] = sum(1 for x in merged[:100] if x.get("source_gate") == "READY_COMMON")
    result["next_experiment_candidate"] = direct[0] if direct else None
    result["schema_version"] = SCHEMA
    result["state"] = "PASS_RESEARCH_FACTORY_V3_STRICT_REPAIR_READY" if direct else "HOLD_RESEARCH_FACTORY_V3_NO_STRICT_REPAIR_PASS"
    result["queue_bridge"] = {
        "ready_common_first": True,
        "strict_exact_strategy_repair": True,
        "new_architecture_separated_from_repair_queue": True,
        "reviewed_candidate_survives_backlog_top5_truncation": True,
        "advanced_source_candidates_preserved": True,
        "groq_prompt_compacted": True,
        "groq_max_tokens": v2.GROQ_MAX_TOKENS,
        "common_sources": sorted(COMMON_READY),
    }
    result["policy"]["ready_common_first"] = True
    result["policy"]["strict_exact_strategy_repair"] = True
    result["policy"]["new_architecture_separated_from_repair_queue"] = True
    result["policy"]["reviewed_bridge_bypasses_backlog_truncation"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    global _READY_BY_STRATEGY
    _READY_BY_STRATEGY = {"x": [{"axis": "VOLATILITY_REGIME_OWNER_ONLY", "source_gate": "READY_COMMON", "score": 4.0}]}
    prompt, _, axes = repair_prompt("x", {"verified_pretrade_cost_bps": 14.0}, [{"id": "R1", "title": "volatility", "claim": "volatility regime"}])
    assert "NEW_ARCHITECTURE" in prompt and "forbidden" in prompt.lower()
    assert axes == {"VOLATILITY_REGIME_OWNER_ONLY"}
    bridge = reviewed_bridge({"x": {"reviewed": [{
        "mode": "REPAIR", "strategy_id": "x", "source_gate": "READY_COMMON", "eligible_for_experiment_queue": True,
        "candidate_sha256": "abc", "candidate_id": "c", "score": 10.0,
    }]}})
    assert len(bridge) == 1 and bridge[0]["strategy_id"] == "x"
    bridge2 = reviewed_bridge({"x": {"reviewed": [{
        "mode": "NEW_ARCHITECTURE", "strategy_id": "NEW", "source_gate": "READY_COMMON", "eligible_for_experiment_queue": True,
        "candidate_sha256": "def", "candidate_id": "n", "score": 99.0,
    }]}})
    assert bridge2 == []
    print("PASS_A1_RESEARCH_FACTORY_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v3.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-strategy-limit", type=int, default=v1.AI_STRATEGY_LIMIT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, network=not args.no_network, ai=not args.no_ai, ai_strategy_limit=max(0, args.ai_strategy_limit))
    print(json.dumps({
        "state": result["state"],
        "sources": result.get("external_source_count"),
        "new_discovered": result.get("new_discovered_source_count"),
        "ready_common_queue_count": result.get("ready_common_queue_count"),
        "reviewed_ready_common_count": result.get("reviewed_ready_common_count"),
        "ai_targets": result.get("ai_scout_priority_strategy_ids"),
        "next_experiment_candidate": result.get("next_experiment_candidate"),
        "receipt_sha256": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
