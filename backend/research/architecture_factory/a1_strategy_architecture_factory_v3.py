#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import (
    EVIDENCE,
    LEDGER,
    base_score,
    critic_payload,
    dedup,
    evidence_compact,
    generator_prompt,
    openai_critic,
    read_json,
    safe_error,
    subprocess_review,
    target_rows,
    validate_candidates,
)
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import harden_candidate, sha
from backend.research.architecture_factory.gemini_provider_v1 import (
    call_gemini_critic,
    call_gemini_generator,
    economic_rebuild_enabled,
)


def _review_gemini_candidate(c: Mapping[str, Any], work: Path, env: Mapping[str, str]) -> dict[str, Any]:
    reviews: dict[str, Any] = {}
    try:
        reviews["openai"] = openai_critic(c)
    except Exception as exc:
        reviews["openai"] = {"successful": False, "error": safe_error(exc)}
    reviews["groq"] = subprocess_review("scripts/strategy11_groq_redteam.py", c, work, env, "groq")
    reviews["workers_ai"] = subprocess_review("scripts/strategy11_workers_ai_guard.py", c, work, env, "workers")
    passes = 0
    rejects = 0
    for name, row in reviews.items():
        if name == c.get("provider"):
            continue
        decision = str(row.get("decision") or "")
        if row.get("successful") and decision in {"PASS", "PASS_TO_REPLAY", "PASS_TO_PREREGISTER"}:
            passes += 1
        if row.get("successful") and decision == "REJECT":
            rejects += 1
    return {
        **c,
        "cross_reviews": reviews,
        "independent_passes": passes,
        "independent_rejects": rejects,
        "score": round(base_score(c) + passes * 2.5 - rejects * 4.0, 4),
    }


def _add_gemini_review(c: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(c)
    reviews = dict(row.get("cross_reviews") or {})
    try:
        reviews["gemini"] = call_gemini_critic(critic_payload(row))
    except Exception as exc:
        reviews["gemini"] = {"successful": False, "error": safe_error(exc)}
    passes = 0
    rejects = 0
    for name, review in reviews.items():
        if name == row.get("provider"):
            continue
        decision = str(review.get("decision") or "")
        if review.get("successful") and decision in {"PASS", "PASS_TO_REPLAY", "PASS_TO_PREREGISTER"}:
            passes += 1
        if review.get("successful") and decision == "REJECT":
            rejects += 1
    row["cross_reviews"] = reviews
    row["independent_passes"] = passes
    row["independent_rejects"] = rejects
    row["score"] = round(base_score(row) + passes * 2.5 - rejects * 4.0, 4)
    return row


def _parallel_g2_enabled() -> bool:
    return os.environ.get("G2_PARALLEL_RESEARCH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def run(output: Path) -> dict[str, Any]:
    from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import run as run_v2

    with tempfile.TemporaryDirectory(prefix="a1-factory-v3-base-") as td:
        base_path = Path(td) / "v2.json"
        base = run_v2(base_path)

    ledger = read_json(LEDGER)
    done_count = int(ledger.get("done_count") or 0)
    parallel_g2 = _parallel_g2_enabled()
    gemini_enabled = economic_rebuild_enabled(done_count) or (
        parallel_g2
        and bool(os.environ.get("GEMINI_API_KEY", "").strip())
        and os.environ.get("GEMINI_ECONOMIC_REBUILD_ENABLED", "").strip().lower() not in {"0", "false", "no", "off"}
    )
    reviewed = [dict(x) for x in (base.get("all_reviewed_candidates") or [])]
    gemini_state: dict[str, Any] = {
        "enabled": gemini_enabled,
        "activation_rule": "GEN1 done_count>=25 OR explicit G2 parallel research; GEMINI_API_KEY required",
        "done_count": done_count,
        "parallel_g2_research": parallel_g2,
        "purpose": "G2_PARALLEL_ARCHITECTURE_RESEARCH_WITH_GEN1_PASSIVE_COMPLETION",
        "generator": {"successful": False, "state": "KEY_OR_ENABLEMENT_MISSING" if not gemini_enabled else "READY"},
        "critic_reviewed_count": 0,
    }

    if gemini_enabled:
        evidence = read_json(EVIDENCE)
        targets = target_rows(ledger)
        source_rows = evidence_compact(evidence)
        source_ids = {str(x.get("id")) for x in source_rows}
        target_ids = {str(x["strategy_id"]) for x in targets}
        context = {
            "objective": "G2 parallel economic architecture research: find robust realistic-cost Net+ mechanisms while Gen1 unfinished strategies continue passive evidence clocks",
            "verified_round_trip_cost_bps_reference": 14.0,
            "available_source_vocabulary": ["ohlcv", "candles", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow", "derived_regime_features"],
            "current_failure_targets": targets,
            "external_evidence": source_rows,
            "constraints": {
                "gen1_future_results_visible_for_g2_parameter_tuning": False,
                "baseline_mutation": False,
                "threshold_sweep": False,
                "best_horizon_cherry_pick": False,
                "fee_reduction": False,
                "sealed_holdout_visibility": False,
                "new_architecture_allowed": True,
                "indicators_allowed_only_with_causal_role": True,
                "economic_objective": "realistic-cost net profit first",
            },
        }
        prompt = generator_prompt(context)
        try:
            model, raw, lineage = call_gemini_generator(prompt)
            gemini_candidates = validate_candidates(raw, "gemini", source_ids, target_ids)
            gemini_state["generator"] = {"successful": True, "model": model, **lineage, "candidate_count": len(gemini_candidates)}
            env = os.environ.copy()
            with tempfile.TemporaryDirectory(prefix="a1-gemini-candidates-") as td:
                root = Path(td)
                for idx, candidate in enumerate(gemini_candidates):
                    work = root / str(idx)
                    work.mkdir()
                    reviewed.append(_review_gemini_candidate(candidate, work, env))
        except Exception as exc:
            gemini_state["generator"] = {"successful": False, "state": "CALL_FAILED", "error": safe_error(exc)}

        upgraded = []
        for candidate in reviewed:
            if candidate.get("provider") == "gemini":
                upgraded.append(candidate)
            else:
                upgraded.append(_add_gemini_review(candidate))
        reviewed = upgraded
        gemini_state["critic_reviewed_count"] = sum(
            1 for x in reviewed if (x.get("cross_reviews") or {}).get("gemini") is not None
        )

    combined = dedup(sorted(reviewed, key=lambda x: -float(x.get("score") or 0.0)), 0.85)[:12]
    hardened = [harden_candidate(x) for x in combined]
    hardened.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))
    top3 = hardened[:3]

    result = dict(base)
    result["schema_version"] = "zel.a1_strategy_architecture_factory.v3"
    result["all_reviewed_candidates"] = hardened
    result["top3"] = top3
    result["generated_after_dedup"] = len(hardened)
    result["gemini"] = gemini_state
    result["gemini_economic_rebuild_only"] = False
    result["g2_parallel_research_enabled"] = parallel_g2
    result["gen1_completion_mode"] = "PASSIVE_UNCHANGED"
    result["alpha_proof_ready_count"] = sum(1 for x in hardened if x.get("alpha_proof_candidate_ready"))
    result["eligible_for_preregistration_count"] = 0
    result["state"] = (
        "PASS_ARCHITECTURE_FACTORY_TOP3_READY_FOR_ALPHA_PROOF"
        if any(x.get("alpha_proof_candidate_ready") for x in top3)
        else "HOLD_ARCHITECTURE_FACTORY_NO_ALPHA_PROOF_CANDIDATE"
    )
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    from backend.research.architecture_factory.gemini_provider_v1 import self_test as gemini_self_test
    assert gemini_self_test() == 0
    print("PASS_A1_STRATEGY_ARCHITECTURE_FACTORY_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_strategy_architecture_factory_v3.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result["state"],
        "done_count": result.get("gemini", {}).get("done_count"),
        "g2_parallel_research_enabled": result.get("g2_parallel_research_enabled"),
        "gemini_enabled": result.get("gemini", {}).get("enabled"),
        "gemini_generator": result.get("gemini", {}).get("generator"),
        "alpha_proof_ready_count": result.get("alpha_proof_ready_count"),
        "top3": [{"id": x.get("candidate_id"), "provider": x.get("provider"), "family": x.get("architecture_family"), "score": x.get("score")} for x in result.get("top3") or []],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
