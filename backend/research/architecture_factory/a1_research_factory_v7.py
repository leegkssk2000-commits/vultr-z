#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_research_factory_v5 as v5
import backend.research.architecture_factory.a1_research_factory_v6 as v6
import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af
import backend.research.architecture_factory.gemini_provider_v1 as gemini

SCHEMA = "zel.a1_research_factory.v7"
_BASE_SCOUT = v5.strict_ai_scout_v5


def _gemini_fallback_review(candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = af.critic_payload(candidate)
    return gemini.call_gemini_critic(payload)


def strict_ai_scout_v7(
    strategy_id: str,
    ledger_row: Mapping[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(_BASE_SCOUT(strategy_id, ledger_row, evidence_rows))
    reviewed = [dict(x) for x in (result.get("reviewed") or []) if isinstance(x, Mapping)]
    fallback_attempts = fallback_passes = fallback_rejects = 0
    gemini_available = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    for candidate in reviewed:
        passes = int(candidate.get("independent_passes") or 0)
        rejects = int(candidate.get("independent_rejects") or 0)
        reviews = dict(candidate.get("cross_reviews") or {})
        if passes >= 2 or rejects > 0 or not gemini_available:
            candidate["cross_reviews"] = reviews
            continue

        # Use Gemini only as a missing-quorum substitute. It does not replace an explicit reject.
        fallback_attempts += 1
        try:
            review = _gemini_fallback_review(candidate)
        except Exception as exc:  # noqa: BLE001
            review = {
                "successful": False,
                "error": af.safe_error(exc),
                "review_contract": "A5_PRE_REPLAY_FALLBACK_V7",
            }
        reviews["gemini_fallback"] = review
        decision = str(review.get("decision") or "")
        if review.get("successful") and decision in {"PASS", "PASS_TO_REPLAY", "PASS_TO_PREREGISTER"}:
            passes += 1
            fallback_passes += 1
        elif review.get("successful") and decision == "REJECT":
            rejects += 1
            fallback_rejects += 1

        candidate["cross_reviews"] = reviews
        candidate["independent_passes"] = passes
        candidate["independent_rejects"] = rejects
        candidate["eligible_for_experiment_queue"] = passes >= 2 and rejects == 0
        candidate["score"] = round(af.base_score(candidate) + passes * 2.5 - rejects * 4.0, 4)
        candidate["review_quorum_policy"] = "TWO_INDEPENDENT_PASS_ZERO_REJECT_WITH_GEMINI_FALLBACK"

    reviewed.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("candidate_id") or "")))
    result["reviewed"] = reviewed[:3]
    result["gemini_fallback_review"] = {
        "available": gemini_available,
        "attempt_count": fallback_attempts,
        "pass_count": fallback_passes,
        "reject_count": fallback_rejects,
        "only_when_quorum_missing": True,
        "cannot_override_explicit_reject": True,
    }
    return result


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = 5) -> dict[str, Any]:
    old = v5.strict_ai_scout_v5
    try:
        v5.strict_ai_scout_v5 = strict_ai_scout_v7
        result = dict(v6.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit))
    finally:
        v5.strict_ai_scout_v5 = old

    ai_results = result.get("ai_scout_results") or {}
    fallback_attempts = fallback_passes = fallback_rejects = 0
    if isinstance(ai_results, Mapping):
        for block in ai_results.values():
            if not isinstance(block, Mapping):
                continue
            diag = block.get("gemini_fallback_review") or {}
            if not isinstance(diag, Mapping):
                continue
            fallback_attempts += int(diag.get("attempt_count") or 0)
            fallback_passes += int(diag.get("pass_count") or 0)
            fallback_rejects += int(diag.get("reject_count") or 0)

    # v6/v5 already rebuild the direct reviewed bridge after each scout call. Rebuild it
    # once more so Gemini-completed quorum candidates become queue-eligible in this receipt.
    direct = []
    if isinstance(ai_results, Mapping):
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
                row["origin"] = "MULTI_AI_SCOUT_STRICT_REPAIR_V7"
                row["status"] = "AI_REVIEWED_READY_COMMON"
                direct.append(row)
    direct.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("strategy_id") or ""), str(x.get("candidate_id") or "")))
    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in direct:
        key = str(row.get("candidate_sha256") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        dedup.append(row)
    direct = dedup

    existing = [x for x in (result.get("experiment_queue") or []) if isinstance(x, Mapping)]
    direct_keys = {str(x.get("candidate_sha256") or "") for x in direct if x.get("candidate_sha256")}
    merged = list(direct)
    for row in existing:
        key = str(row.get("candidate_sha256") or "")
        if key and key in direct_keys:
            continue
        merged.append(dict(row))

    result["experiment_queue"] = merged[:100]
    result["experiment_queue_count"] = len(result["experiment_queue"])
    result["reviewed_ready_common_count"] = len(direct)
    result["ready_common_queue_count"] = sum(1 for x in result["experiment_queue"] if x.get("source_gate") == "READY_COMMON")
    result["next_experiment_candidate"] = direct[0] if direct else None
    result["schema_version"] = SCHEMA
    result["state"] = "PASS_RESEARCH_FACTORY_V7_REVIEW_QUORUM_READY" if direct else "HOLD_RESEARCH_FACTORY_V7_NO_ELIGIBLE_REPAIR"
    result["a5_review_quorum"] = {
        "required_independent_passes": 2,
        "maximum_rejects": 0,
        "gemini_fallback_only_when_quorum_missing": True,
        "gemini_fallback_cannot_override_reject": True,
        "fallback_attempt_count": fallback_attempts,
        "fallback_pass_count": fallback_passes,
        "fallback_reject_count": fallback_rejects,
    }
    result["policy"]["gemini_missing_quorum_fallback"] = True
    result["policy"]["explicit_reject_never_overridden_by_fallback"] = True
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert _BASE_SCOUT is not strict_ai_scout_v7
    fake = {
        "candidate_id": "x",
        "mode": "REPAIR",
        "strategy_id": "trend_rider",
        "architecture_family": "existing:trend_rider",
        "changed_axis": "VOLATILITY_REGIME_OWNER_ONLY",
        "mechanism": "completed-bar volatility state controls ownership",
        "entry_event": "completed-bar state transition",
        "native_horizon": "intraday",
        "regime_owner": "trade only in the owned state",
        "falsification": "bounded replay fails to improve after-cost expectancy",
        "evidence_ids": ["E1"],
        "required_sources": ["ohlcv"],
        "expected_move_cost_multiple_target": 2.0,
    }
    payload = af.critic_payload(fake)
    assert payload["strategy_id"] == "trend_rider"
    assert payload["execution_authority"] == "NONE" and payload["order_authority"] == "BLOCKED"
    print("PASS_A1_RESEARCH_FACTORY_V7_GEMINI_QUORUM_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v7.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-strategy-limit", type=int, default=5)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, network=not args.no_network, ai=not args.no_ai, ai_strategy_limit=max(0, args.ai_strategy_limit))
    print(json.dumps({
        "state": r.get("state"),
        "targets": (r.get("a5_no_idle") or {}).get("targets_this_run"),
        "reviewed_ready_common": r.get("reviewed_ready_common_count"),
        "quorum": r.get("a5_review_quorum"),
        "next": r.get("next_experiment_candidate"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
