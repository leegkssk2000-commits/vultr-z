#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af

SCHEMA = "zel.a1_research_factory.v2"
COMMON_READY = {"ohlcv", "volume"}
COMPACT_EVIDENCE_LIMIT = 8
COMPACT_CLAIM_CHARS = 360
GROQ_MAX_TOKENS = 1800


def compact_evidence(rows: list[dict[str, Any]], limit: int = COMPACT_EVIDENCE_LIMIT) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows[: max(0, int(limit))]:
        if not isinstance(raw, Mapping):
            continue
        out.append({
            "id": raw.get("id"),
            "tier": raw.get("tier"),
            "source_type": raw.get("source_type"),
            "identifier": raw.get("identifier"),
            "title": str(raw.get("title") or "")[:240],
            "claim": str(raw.get("claim") or "")[:COMPACT_CLAIM_CHARS],
            "extractable_axes": list(raw.get("extractable_axes") or [])[:6],
        })
    return out


def ready_common_count(backlog: Any) -> int:
    if not isinstance(backlog, list):
        return 0
    return sum(
        1
        for row in backlog
        if isinstance(row, Mapping)
        and row.get("origin") != "SEALED_EXACT25_AXIS"
        and row.get("source_gate") == "READY_COMMON"
    )


def priority_targets(
    ledger: Mapping[str, Any], strategy_ids: list[str], backlogs: Mapping[str, Any], limit: int
) -> list[str]:
    """V2: consume immediately testable OHLCV/volume backlogs before blocked-source ideas."""
    states = ledger.get("strategies") or {}
    ranked: list[tuple[float, str]] = []
    for sid in strategy_ids:
        raw = states.get(sid) if isinstance(states, Mapping) else {}
        raw = raw if isinstance(raw, Mapping) else {}
        backlog = backlogs.get(sid) if isinstance(backlogs, Mapping) else []
        ready = ready_common_count(backlog)
        status = str(raw.get("status") or "")
        terminal = status.startswith("A1_") and status not in {"A1_SURVIVOR", "A1_EXACT25_BASELINE_SWEEP_ACTIVE"}
        trades = min(int(raw.get("completed_trades") or 0), 25)
        # READY_COMMON is the dominant term so a source-ready strategy cannot be starved
        # by higher-scoring ideas that still require unavailable history.
        score = ready * 1000.0 + (100.0 if terminal else 0.0) + trades
        ranked.append((score, sid))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [sid for _, sid in ranked[: max(0, int(limit))]]


def call_groq_compact(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY_MISSING")
    from groq import Groq

    model = os.environ.get("GROQ_MODEL", "").strip() or af.DEFAULT_GROQ_MODEL
    client = Groq(api_key=key)
    comp = client.chat.completions.create(
        model=model,
        temperature=0.1,
        max_tokens=GROQ_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt + "\nReturn one JSON object only."}],
    )
    text = (comp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        import re
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("GROQ_FACTORY_JSON_MISSING")
    import hashlib
    return model, json.loads(text[start : end + 1]), {
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
    }


def ai_scout(strategy_id: str, ledger_row: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = compact_evidence(evidence_rows)
    source_ids = {str(x.get("id")) for x in evidence if x.get("id")}
    context = {
        "objective": (
            "Unblock the immediate one-axis experiment queue for this exact strategy. "
            "Generate only candidates that can be replayed now from OHLCV and/or volume; "
            "do not request funding, basis, open_interest, l2_order_book or trade_flow in this READY_COMMON pass."
        ),
        "verified_round_trip_cost_bps_reference": float(ledger_row.get("verified_pretrade_cost_bps") or 14.0),
        "available_source_vocabulary": ["ohlcv", "volume"],
        "current_failure_targets": [{
            "strategy_id": strategy_id,
            "status": ledger_row.get("status"),
            "completed_trades": ledger_row.get("completed_trades"),
            "gross_expectancy_bps": ledger_row.get("gross_expectancy_bps"),
            "net_expectancy_bps": ledger_row.get("net_expectancy_bps"),
            "profit_factor": ledger_row.get("profit_factor"),
            "drawdown_bps": ledger_row.get("drawdown_bps"),
        }],
        "external_evidence": evidence,
        "constraints": {
            "baseline_mutation": False,
            "threshold_sweep": False,
            "best_horizon_cherry_pick": False,
            "fee_reduction": False,
            "sealed_holdout_visibility": False,
            "one_axis_per_repair": True,
            "required_sources_must_be_subset_of": ["ohlcv", "volume"],
        },
    }
    prompt = (
        "READY_COMMON HARD ROUTE: every emitted candidate MUST require only OHLCV and/or volume. "
        "A candidate requesting any other source is invalid for this pass. "
        + af.generator_prompt(context)
    )
    generated: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}
    for provider, fn in (("openai", af.call_openai_generator), ("groq", call_groq_compact)):
        try:
            model, raw, lineage = fn(prompt)
            got = af.validate_candidates(raw, provider, source_ids, {strategy_id})
            got = [x for x in got if set(x.get("required_sources") or []).issubset(COMMON_READY)]
            providers[provider] = {
                "successful": True,
                "model": model,
                **lineage,
                "candidate_count": len(got),
                "ready_common_only": True,
            }
            generated.extend(got)
        except Exception as exc:  # noqa: BLE001
            providers[provider] = {"successful": False, "error": af.safe_error(exc), "ready_common_only": True}

    generated = af.dedup(sorted(generated, key=lambda x: -af.base_score(x)), v1.DEDUP_THRESHOLD)[:3]
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix=f"a1-rf-v2-{strategy_id}-") as td:
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
            score = af.base_score(candidate) + passes * 2.5 - rejects * 4.0
            reviewed.append({
                **candidate,
                "cross_reviews": reviews,
                "independent_passes": passes,
                "independent_rejects": rejects,
                "score": round(score, 4),
                "source_gate": "READY_COMMON",
                "eligible_for_experiment_queue": passes >= 2 and rejects == 0,
            })
    reviewed.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("candidate_id") or "")))
    return {
        "strategy_id": strategy_id,
        "providers": providers,
        "reviewed": reviewed[:3],
        "compact_evidence_count": len(evidence),
        "groq_max_tokens": GROQ_MAX_TOKENS,
    }


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = v1.AI_STRATEGY_LIMIT) -> dict[str, Any]:
    old_priority, old_scout = v1.priority_targets, v1.ai_scout
    try:
        v1.priority_targets = priority_targets
        v1.ai_scout = ai_scout
        result = dict(v1.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v1.priority_targets = old_priority
        v1.ai_scout = old_scout

    queue = [x for x in (result.get("experiment_queue") or []) if isinstance(x, Mapping)]
    ready = [x for x in queue if x.get("source_gate") == "READY_COMMON"]
    eligible_ready = [x for x in ready if x.get("eligible_for_experiment_queue") is True]
    next_candidate = eligible_ready[0] if eligible_ready else None
    result["schema_version"] = SCHEMA
    result["state"] = "PASS_RESEARCH_FACTORY_V2_EXPERIMENT_READY" if next_candidate else "HOLD_RESEARCH_FACTORY_V2_NO_REVIEWED_READY_COMMON"
    result["ready_common_queue_count"] = len(ready)
    result["reviewed_ready_common_count"] = len(eligible_ready)
    result["next_experiment_candidate"] = next_candidate
    result["queue_bridge"] = {
        "ready_common_first": True,
        "advanced_source_candidates_preserved": True,
        "groq_prompt_compacted": True,
        "groq_max_tokens": GROQ_MAX_TOKENS,
        "common_sources": sorted(COMMON_READY),
    }
    result["policy"]["ready_common_first"] = True
    result["policy"]["advanced_source_backlog_preserved"] = True
    result["policy"]["groq_prompt_compaction_only"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    backlog = {
        "a": [{"origin": "CONTINUOUS_EVIDENCE_DISCOVERY", "source_gate": "READY_COMMON"}],
        "b": [{"origin": "MULTI_AI_SCOUT", "source_gate": "NEEDS_SOURCE_HISTORY_GATE"}],
    }
    ledger = {"strategies": {"a": {"status": "UNTESTED", "completed_trades": 0}, "b": {"status": "A1_ECONOMIC_FAIL", "completed_trades": 25}}}
    assert priority_targets(ledger, ["a", "b"], backlog, 2)[0] == "a"
    compact = compact_evidence([{"id": "X", "claim": "z" * 900, "title": "t"}])
    assert len(compact) == 1 and len(compact[0]["claim"]) == COMPACT_CLAIM_CHARS
    assert ready_common_count(backlog["a"]) == 1
    print("PASS_A1_RESEARCH_FACTORY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v2.json"))
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
