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
import backend.research.architecture_factory.a1_research_factory_v3 as v3
import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af

SCHEMA = "zel.a1_research_factory.v4"
COMMON_READY = {"ohlcv", "volume"}


def identity_lock_candidates(
    raw: Any,
    strategy_id: str,
    source_ids: set[str],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Freeze repair identity/lineage before the generic architecture validator.

    The generator still owns the economic semantics. V4 owns only fields that are
    already fixed by the selected READY_COMMON backlog row: mode, exact strategy,
    one changed axis, required source vocabulary, and admissible evidence lineage.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("candidates"), list):
        raise RuntimeError("GENERATOR_SHAPE_INVALID")
    ready_rows = v3._READY_BY_STRATEGY.get(strategy_id) or []
    ready_rows = [
        dict(x) for x in ready_rows[:3]
        if isinstance(x, Mapping) and str(x.get("axis") or "").strip()
    ]
    if not ready_rows:
        raise RuntimeError("NO_READY_COMMON_AXIS_FOR_IDENTITY_LOCK")

    locked: list[dict[str, Any]] = []
    dropped_no_lineage = 0
    for idx, candidate in enumerate(raw.get("candidates") or []):
        if not isinstance(candidate, Mapping):
            continue
        selected = ready_rows[idx % len(ready_rows)]
        axis = str(selected.get("axis") or "").strip()

        required_sources = [
            str(x) for x in (selected.get("required_sources") or [])
            if str(x) in COMMON_READY
        ]
        if not required_sources:
            required_sources = [
                str(x) for x in (candidate.get("required_sources") or [])
                if str(x) in COMMON_READY
            ]
        if not required_sources:
            required_sources = ["ohlcv"]

        selected_lineage = [
            str(x) for x in (selected.get("source_ids") or [])
            if str(x) in source_ids
        ]
        raw_lineage = [
            str(x) for x in (candidate.get("evidence_ids") or [])
            if str(x) in source_ids
        ]
        evidence_ids = selected_lineage or raw_lineage
        if not evidence_ids:
            dropped_no_lineage += 1
            continue

        item = dict(candidate)
        item["candidate_id"] = str(item.get("candidate_id") or f"identity-lock-{idx + 1}")
        item["mode"] = "REPAIR"
        item["strategy_id"] = strategy_id
        item["changed_axis"] = axis
        item["required_sources"] = sorted(set(required_sources))
        item["evidence_ids"] = list(dict.fromkeys(evidence_ids))
        if not str(item.get("architecture_family") or "").strip():
            item["architecture_family"] = f"existing:{strategy_id}"
        locked.append(item)

    return {"candidates": locked}, {
        "raw_generated_count": len(raw.get("candidates") or []),
        "identity_locked_count": len(locked),
        "identity_lock_dropped_no_lineage": dropped_no_lineage,
    }


def strict_ai_scout_v4(
    strategy_id: str,
    ledger_row: Mapping[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = v2.compact_evidence(evidence_rows)
    prompt, source_ids, allowed_axes = v3.repair_prompt(strategy_id, ledger_row, evidence_rows)
    generated: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}

    for provider, fn in (("openai", af.call_openai_generator), ("groq", v2.call_groq_compact)):
        diag = {
            "raw_generated_count": 0,
            "identity_locked_count": 0,
            "identity_lock_dropped_no_lineage": 0,
            "validated_count": 0,
        }
        try:
            model, raw, lineage = fn(prompt)
            locked_raw, lock_diag = identity_lock_candidates(raw, strategy_id, source_ids)
            diag.update(lock_diag)
            got = af.validate_candidates(locked_raw, provider, source_ids, {strategy_id})
            got = [
                x for x in got
                if x.get("mode") == "REPAIR"
                and x.get("strategy_id") == strategy_id
                and str(x.get("changed_axis") or "") in allowed_axes
                and set(x.get("required_sources") or []).issubset(COMMON_READY)
            ]
            diag["validated_count"] = len(got)
            providers[provider] = {
                "successful": bool(got),
                "model": model,
                **lineage,
                **diag,
                "candidate_count": len(got),
                "identity_lock_applied_before_validator": True,
                "strict_repair_only": True,
            }
            generated.extend(got)
        except Exception as exc:  # noqa: BLE001
            providers[provider] = {
                "successful": False,
                "error": af.safe_error(exc),
                **diag,
                "identity_lock_applied_before_validator": True,
                "strict_repair_only": True,
            }

    generated = af.dedup(sorted(generated, key=lambda x: -af.base_score(x)), v1.DEDUP_THRESHOLD)[:3]
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix=f"a1-rf-v4-{strategy_id}-") as td:
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
                "identity_lock_applied_before_validator": True,
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
        "identity_lock_applied_before_validator": True,
    }


def _flow_counts(ai_results: Mapping[str, Any]) -> dict[str, int]:
    totals = {
        "raw_generated": 0,
        "identity_locked": 0,
        "validated": 0,
        "reviewed": 0,
        "eligible": 0,
    }
    for block in ai_results.values():
        if not isinstance(block, Mapping):
            continue
        providers = block.get("providers") or {}
        if isinstance(providers, Mapping):
            for p in providers.values():
                if not isinstance(p, Mapping):
                    continue
                totals["raw_generated"] += int(p.get("raw_generated_count") or 0)
                totals["identity_locked"] += int(p.get("identity_locked_count") or 0)
                totals["validated"] += int(p.get("validated_count") or 0)
        rows = [x for x in (block.get("reviewed") or []) if isinstance(x, Mapping)]
        totals["reviewed"] += len(rows)
        totals["eligible"] += sum(1 for x in rows if x.get("eligible_for_experiment_queue") is True)
    return totals


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = v1.AI_STRATEGY_LIMIT) -> dict[str, Any]:
    old_priority, old_scout = v1.priority_targets, v1.ai_scout
    try:
        v1.priority_targets = v3.strict_priority_targets
        v1.ai_scout = strict_ai_scout_v4
        result = dict(v1.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v1.priority_targets = old_priority
        v1.ai_scout = old_scout

    direct = v3.reviewed_bridge(result.get("ai_scout_results") or {})
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
    result["candidate_flow_counts"] = _flow_counts(result.get("ai_scout_results") or {})
    result["schema_version"] = SCHEMA
    result["state"] = (
        "PASS_RESEARCH_FACTORY_V4_IDENTITY_LOCK_REPAIR_READY"
        if direct else "HOLD_RESEARCH_FACTORY_V4_NO_REVIEWED_REPAIR"
    )
    result["queue_bridge"] = {
        "ready_common_first": True,
        "strict_exact_strategy_repair": True,
        "deterministic_identity_lock_before_validator": True,
        "new_architecture_separated_from_repair_queue": True,
        "reviewed_candidate_survives_backlog_top5_truncation": True,
        "advanced_source_candidates_preserved": True,
        "groq_prompt_compacted": True,
        "groq_max_tokens": v2.GROQ_MAX_TOKENS,
        "common_sources": sorted(COMMON_READY),
    }
    result["policy"]["ready_common_first"] = True
    result["policy"]["strict_exact_strategy_repair"] = True
    result["policy"]["deterministic_identity_lock_before_validator"] = True
    result["policy"]["new_architecture_separated_from_repair_queue"] = True
    result["policy"]["reviewed_bridge_bypasses_backlog_truncation"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    old = v3._READY_BY_STRATEGY
    try:
        v3._READY_BY_STRATEGY = {
            "x": [{
                "axis": "VOLATILITY_REGIME_OWNER_ONLY",
                "source_gate": "READY_COMMON",
                "required_sources": ["ohlcv"],
                "source_ids": ["R1"],
                "score": 4.0,
            }]
        }
        raw = {"candidates": [{
            "candidate_id": "bad-identity",
            "mode": "NEW_ARCHITECTURE",
            "strategy_id": "NEW",
            "architecture_family": "existing repair",
            "changed_axis": "WRONG_AXIS",
            "mechanism": "A lagged volatility state may gate a frozen signal without changing its geometry.",
            "payer": "liquidity demand across volatility states",
            "entry_event": "the existing signal occurs in a completed-bar volatility state",
            "direction_rule": "preserve existing strategy direction rule",
            "native_horizon": "preserve the existing strategy native horizon",
            "regime_owner": "trade only in the selected observable volatility state",
            "invalidation": "prospective performance fails when the ownership state is applied",
            "exit_logic": "preserve existing exit logic",
            "time_stop_rationale": "preserve existing time-stop rationale",
            "turnover_cost_budget": "must clear the existing verified cost reference prospectively",
            "required_sources": ["funding"],
            "evidence_ids": ["BAD"],
            "expected_move_cost_multiple_target": 2.0,
            "falsification": "one bounded replay rejects the ownership change if net expectancy does not improve",
            "forbidden_changes": ["fees", "best-horizon selection", "post-outcome loss deletion"],
            "why_distinct": "changes only regime ownership",
        }]}
        locked, diag = identity_lock_candidates(raw, "x", {"R1"})
        row = locked["candidates"][0]
        assert row["mode"] == "REPAIR" and row["strategy_id"] == "x"
        assert row["changed_axis"] == "VOLATILITY_REGIME_OWNER_ONLY"
        assert row["required_sources"] == ["ohlcv"] and row["evidence_ids"] == ["R1"]
        validated = af.validate_candidates(locked, "selftest", {"R1"}, {"x"})
        assert len(validated) == 1 and diag["identity_locked_count"] == 1
        assert validated[0]["mode"] == "REPAIR" and validated[0]["strategy_id"] == "x"
    finally:
        v3._READY_BY_STRATEGY = old
    print("PASS_A1_RESEARCH_FACTORY_V4_IDENTITY_LOCK_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v4.json"))
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
        "candidate_flow_counts": result.get("candidate_flow_counts"),
        "ai_targets": result.get("ai_scout_priority_strategy_ids"),
        "next_experiment_candidate": result.get("next_experiment_candidate"),
        "receipt_sha256": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
