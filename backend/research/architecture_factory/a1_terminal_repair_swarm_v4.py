#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    openai_critic,
    read_json,
    safe_error,
    subprocess_review,
    validate_candidates,
)
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import harden_candidate
from backend.research.architecture_factory.a1_terminal_repair_swarm_v2 import (
    TERMINAL,
    canonical,
    fingerprint,
    prompt_for,
    sha,
)
from backend.research.architecture_factory.gemini_provider_v1 import (
    call_gemini_critic,
    call_gemini_generator,
    economic_rebuild_enabled,
)


def _review_candidate(c: Mapping[str, Any], work: Path, env: Mapping[str, str], include_gemini: bool) -> dict[str, Any]:
    reviews: dict[str, Any] = {}
    try:
        reviews["openai"] = openai_critic(c)
    except Exception as exc:
        reviews["openai"] = {"successful": False, "error": safe_error(exc)}
    reviews["groq"] = subprocess_review("scripts/strategy11_groq_redteam.py", c, work, env, "groq")
    reviews["workers_ai"] = subprocess_review("scripts/strategy11_workers_ai_guard.py", c, work, env, "workers")
    if include_gemini:
        try:
            reviews["gemini"] = call_gemini_critic(critic_payload(c))
        except Exception as exc:
            reviews["gemini"] = {"successful": False, "error": safe_error(exc)}
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
    source_ready = all(
        s in {"ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"}
        for s in (c.get("required_sources") or [])
    )
    row = {
        **c,
        "source_ready": source_ready,
        "cross_reviews": reviews,
        "independent_passes": passes,
        "independent_rejects": rejects,
        "score": round(base_score(c) + passes * 2.5 - rejects * 4.0, 4),
    }
    return harden_candidate(row)


def run(output: Path) -> dict[str, Any]:
    ledger, evidence = read_json(LEDGER), read_json(EVIDENCE)
    done_count = int(ledger.get("done_count") or 0)
    gemini_enabled = economic_rebuild_enabled(done_count)
    source_rows = evidence_compact(evidence)
    source_ids = {str(x.get("id")) for x in source_rows}
    terminals = [
        (sid, raw)
        for sid, raw in (ledger.get("strategies") or {}).items()
        if isinstance(raw, Mapping) and raw.get("status") in TERMINAL
    ]
    fps = [fingerprint(sid, raw) for sid, raw in terminals]
    generated: list[dict[str, Any]] = []
    providers: dict[str, Any] = {}

    from backend.research.architecture_factory.a1_strategy_architecture_factory_v1 import call_groq_generator, call_openai_generator

    for fp in fps:
        sid = fp["strategy_id"]
        prompt = prompt_for(fp, source_rows)
        providers[sid] = {}
        generator_fns = [("openai", call_openai_generator), ("groq", call_groq_generator)]
        if gemini_enabled:
            generator_fns.append(("gemini", call_gemini_generator))
        for provider, fn in generator_fns:
            try:
                model, raw, lineage = fn(prompt)
                rows = validate_candidates(raw, provider, source_ids, {sid})
                providers[sid][provider] = {"successful": True, "model": model, **lineage, "candidate_count": len(rows)}
                generated.extend(rows)
            except Exception as exc:
                providers[sid][provider] = {"successful": False, "error": safe_error(exc)}

    generated = dedup(sorted(generated, key=lambda x: -base_score(x)), 0.85)
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="a1-terminal-swarm-v4-") as td:
        root = Path(td)
        for idx, candidate in enumerate(generated):
            work = root / str(idx)
            work.mkdir()
            reviewed.append(_review_candidate(candidate, work, env, gemini_enabled))
    reviewed.sort(key=lambda x: (-float(x.get("score") or 0.0), str(x.get("candidate_id") or "")))

    by_strategy: dict[str, Any] = {}
    for fp in fps:
        sid = fp["strategy_id"]
        rows = [x for x in reviewed if x.get("strategy_id") == sid]
        by_strategy[sid] = {
            "fingerprint": fp,
            "repair_top3": [x for x in rows if x.get("mode") == "REPAIR"][:3],
            "new_architecture": [x for x in rows if x.get("mode") == "NEW_ARCHITECTURE"][:2],
        }

    result = {
        "schema_version": "zel.a1_terminal_repair_swarm.v4",
        "baseline_ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
        "evidence_sweep_sha256": hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
        "ledger_done_count": done_count,
        "survivor_count": int(ledger.get("survivor_count") or 0),
        "terminal_count": len(terminals),
        "terminal_strategy_ids": [sid for sid, _ in terminals],
        "queued_repair_count": sum(len(v["repair_top3"]) for v in by_strategy.values()),
        "queued_new_arch_count": sum(len(v["new_architecture"]) for v in by_strategy.values()),
        "alpha_proof_ready_count": sum(1 for x in reviewed if x.get("alpha_proof_candidate_ready")),
        "eligible_count": 0,
        "dedup_cosine_threshold": 0.85,
        "provider_state": providers,
        "strategies": by_strategy,
        "global_queue": reviewed,
        "gemini": {
            "enabled": gemini_enabled,
            "activation_rule": "done_count>=25 AND GEMINI_API_KEY present AND GEMINI_ECONOMIC_REBUILD_ENABLED not false",
            "purpose": "POST_25_ECONOMIC_REBUILD_ONLY",
        },
        "launch": {
            "state": "BLOCKED_UNTIL_PASS_ALPHA_PROOF_RECEIPT",
            "candidate": None,
            "reason": "Post-25 repair/replacement generation may use Gemini, OpenAI, Groq and Workers AI, but preregistration remains blocked until candidate-matched Alpha Proof PASS.",
        },
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "alpha_proof_required": True,
        "preregistration_requires_state": "PASS_ALPHA_PROOF_READY_FOR_FRESH_PROSPECTIVE",
        "preregistration_blocked_without_receipt": True,
    }
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert economic_rebuild_enabled(24) is False
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v4.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(canonical({
        "done_count": result["ledger_done_count"],
        "gemini_enabled": result["gemini"]["enabled"],
        "terminal_count": result["terminal_count"],
        "queued_repair_count": result["queued_repair_count"],
        "queued_new_arch_count": result["queued_new_arch_count"],
        "alpha_proof_ready_count": result["alpha_proof_ready_count"],
        "eligible_count": result["eligible_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
