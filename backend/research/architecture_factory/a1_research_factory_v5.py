#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_research_factory_v1 as v1
import backend.research.architecture_factory.a1_research_factory_v2 as v2
import backend.research.architecture_factory.a1_research_factory_v3 as v3
import backend.research.architecture_factory.a1_research_factory_v4 as v4
import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as af

SCHEMA = "zel.a1_research_factory.v5"
COMMON_READY = {"ohlcv", "volume"}
REVIEW_DECISIONS = {"PASS_TO_REPLAY", "HOLD", "REJECT"}
PLACEHOLDER_EXACT = {
    "why money exists and who pays",
    "market participant/inefficiency",
    "entry-time observable event",
    "long/short/both rule",
    "natural holding horizon",
    "when it should and should not trade",
    "causal invalidation",
    "exit rationale without tuned thresholds",
    "why time stop fits mechanism",
    "why expected move can dominate verified costs",
    "one bounded prospective kill test",
    "why not duplicate of current family",
}

_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["PASS_TO_REPLAY", "HOLD", "REJECT"]},
        "blocker_codes": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "single_axis": {"type": "boolean"},
        "source_ready": {"type": "boolean"},
        "falsifiable": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["decision", "blocker_codes", "single_axis", "source_ready", "falsifiable", "reason"],
}


def semantic_quality_guard(candidate: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Reject generator-contract placeholders without judging economic outcomes."""
    fields = (
        "mechanism", "payer", "entry_event", "direction_rule", "native_horizon",
        "regime_owner", "invalidation", "exit_logic", "time_stop_rationale",
        "turnover_cost_budget", "falsification", "why_distinct",
    )
    for key in fields:
        text = " ".join(str(candidate.get(key) or "").strip().lower().split())
        if text in PLACEHOLDER_EXACT:
            return False, f"GENERATOR_CONTRACT_PLACEHOLDER:{key}"
    for key in ("mechanism", "entry_event", "regime_owner", "falsification"):
        if len(str(candidate.get(key) or "").strip()) < 24:
            return False, f"SEMANTIC_SPEC_TOO_SHORT:{key}"
    return True, None


def _source_context(candidate: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {str(x) for x in (candidate.get("evidence_ids") or [])}
    rows = []
    for raw in v2.compact_evidence(evidence_rows, limit=32):
        if str(raw.get("id") or "") not in wanted:
            continue
        rows.append({
            "id": raw.get("id"),
            "tier": raw.get("tier"),
            "source_type": raw.get("source_type"),
            "identifier": raw.get("identifier"),
            "title": raw.get("title"),
            "claim": raw.get("claim"),
            "extractable_axes": raw.get("extractable_axes") or [],
        })
    return rows


def _review_payload(candidate: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "review_stage": "PRE_REPLAY_DESIGN_REVIEW",
        "decision_semantics": {
            "PASS_TO_REPLAY": "single-axis, source-ready, sufficiently specified and falsifiable; permits bounded replay only",
            "HOLD": "missing or ambiguous design/source/lineage specification prevents a valid replay",
            "REJECT": "contradictory, non-falsifiable, forbidden, leaky, or actually multi-axis design",
        },
        "deterministic_facts": {
            "mode": candidate.get("mode"),
            "strategy_id": candidate.get("strategy_id"),
            "changed_axes": [candidate.get("changed_axis")],
            "changed_axis_count": 1,
            "identity_locked_before_validator": candidate.get("identity_lock_applied_before_validator") is True,
            "required_sources": candidate.get("required_sources") or [],
            "ready_common_sources": sorted(COMMON_READY),
            "required_sources_ready": set(candidate.get("required_sources") or []).issubset(COMMON_READY),
            "lineage_complete": bool(candidate.get("evidence_ids")),
            "candidate_sha256": candidate.get("candidate_sha256"),
        },
        "candidate": {
            key: candidate.get(key)
            for key in (
                "architecture_family", "changed_axis", "mechanism", "payer", "entry_event",
                "direction_rule", "native_horizon", "regime_owner", "invalidation", "exit_logic",
                "time_stop_rationale", "turnover_cost_budget", "required_sources", "evidence_ids",
                "expected_move_cost_multiple_target", "falsification", "forbidden_changes", "why_distinct",
            )
        },
        "source_evidence": _source_context(candidate, evidence_rows),
        "authority": {
            "research_only": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }


def _review_prompt(candidate: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> str:
    payload = _review_payload(candidate, evidence_rows)
    return (
        "You are an independent pre-replay falsification reviewer for a research-only trading repair. "
        "This is NOT an empirical performance review and PASS_TO_REPLAY is NOT promotion. "
        "The deterministic_facts section has already verified the exact repair identity, one changed axis, source readiness, and lineage membership. "
        "Do not HOLD merely because prospective PnL, win rate, or replay results do not exist yet; generating those results is the next bounded experiment. "
        "Do not infer extra changed axes from explanatory prose when changed_axis_count=1; instead reject only if the proposal itself explicitly alters additional control dimensions. "
        "Assess whether the mechanism is causally coherent enough to test, the entry/regime semantics are replayable from the listed ready sources, the falsification is bounded, and no forbidden/leaky change is embedded. "
        "PASS_TO_REPLAY only when those design conditions are satisfied. HOLD only for a concrete missing specification/source/lineage item that prevents replay. "
        "REJECT for contradiction, non-falsifiability, leakage, trade deletion, threshold rescue, best-horizon selection, fee rescue, or an actual multi-axis repair. "
        "Return exactly one JSON object matching this contract: "
        + json.dumps({
            "decision": "PASS_TO_REPLAY|HOLD|REJECT",
            "blocker_codes": ["STRING"],
            "single_axis": True,
            "source_ready": True,
            "falsifiable": True,
            "reason": "one concise sentence",
        }, sort_keys=True)
        + "\nPAYLOAD=" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _validate_review(value: Any) -> dict[str, Any]:
    required = {"decision", "blocker_codes", "single_axis", "source_ready", "falsifiable", "reason"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise RuntimeError("REVIEW_SCHEMA_MISMATCH")
    decision = str(value.get("decision") or "")
    if decision not in REVIEW_DECISIONS:
        raise RuntimeError("REVIEW_DECISION_INVALID")
    blockers = value.get("blocker_codes")
    if not isinstance(blockers, list) or len(blockers) > 8 or not all(isinstance(x, str) for x in blockers):
        raise RuntimeError("REVIEW_BLOCKERS_INVALID")
    for key in ("single_axis", "source_ready", "falsifiable"):
        if not isinstance(value.get(key), bool):
            raise RuntimeError(f"REVIEW_BOOL_INVALID:{key}")
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise RuntimeError("REVIEW_REASON_MISSING")
    if decision == "PASS_TO_REPLAY" and (blockers or not value["single_axis"] or not value["source_ready"] or not value["falsifiable"]):
        raise RuntimeError("REVIEW_PASS_CONTRACT_INVALID")
    return {
        "decision": decision,
        "blocker_codes": [str(x)[:80] for x in blockers],
        "single_axis": bool(value["single_axis"]),
        "source_ready": bool(value["source_ready"]),
        "falsifiable": bool(value["falsifiable"]),
        "reason": reason[:1200],
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("REVIEW_JSON_MISSING")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("REVIEW_NOT_OBJECT")
    return value


def openai_repair_review(candidate: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    model = os.environ.get("OPENAI_REVIEW_MODEL", "").strip() or os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5-mini"
    prompt = _review_prompt(candidate, evidence_rows)
    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "instructions": "Return only the required pre-replay design-review JSON. No tools or external web.",
        "input": prompt,
        "max_output_tokens": 1200,
        "text": {"format": {"type": "json_schema", "name": "a1_repair_design_review_v5", "strict": True, "schema": _REVIEW_SCHEMA}},
    }
    if model.lower().startswith("gpt-5"):
        body["reasoning"] = {"effort": "minimal"}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            response = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"OPENAI_REVIEW_HTTP_{exc.code}:{detail}") from exc
    text = af.extract_openai_text(response)
    review = _validate_review(json.loads(text))
    return {
        "successful": True,
        "model": model,
        **review,
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
        "review_contract": "PRE_REPLAY_DESIGN_V5",
    }


def groq_repair_review(candidate: Mapping[str, Any], evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY_MISSING")
    from groq import Groq

    model = os.environ.get("GROQ_REVIEW_MODEL", "").strip() or af.DEFAULT_GROQ_MODEL
    prompt = _review_prompt(candidate, evidence_rows)
    comp = Groq(api_key=key).chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt + "\nReturn one JSON object only."}],
    )
    text = (comp.choices[0].message.content or "").strip()
    review = _validate_review(_parse_json_object(text))
    return {
        "successful": True,
        "model": model,
        **review,
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
        "review_contract": "PRE_REPLAY_DESIGN_V5",
    }


def strict_ai_scout_v5(
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
            "quality_guard_passed_count": 0,
            "quality_guard_dropped_count": 0,
        }
        try:
            model, raw, lineage = fn(prompt)
            locked_raw, lock_diag = v4.identity_lock_candidates(raw, strategy_id, source_ids)
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
            quality: list[dict[str, Any]] = []
            quality_failures: list[str] = []
            for candidate in got:
                ok, reason = semantic_quality_guard(candidate)
                if ok:
                    quality.append(candidate)
                else:
                    quality_failures.append(str(reason))
            diag["quality_guard_passed_count"] = len(quality)
            diag["quality_guard_dropped_count"] = len(got) - len(quality)
            providers[provider] = {
                "successful": bool(quality),
                "model": model,
                **lineage,
                **diag,
                "candidate_count": len(quality),
                "quality_guard_failures": quality_failures[:6],
                "identity_lock_applied_before_validator": True,
                "pre_replay_review_contract": "V5",
                "strict_repair_only": True,
            }
            generated.extend(quality)
        except Exception as exc:  # noqa: BLE001
            providers[provider] = {
                "successful": False,
                "error": af.safe_error(exc),
                **diag,
                "identity_lock_applied_before_validator": True,
                "pre_replay_review_contract": "V5",
                "strict_repair_only": True,
            }

    generated = af.dedup(sorted(generated, key=lambda x: -af.base_score(x)), v1.DEDUP_THRESHOLD)[:3]
    reviewed: list[dict[str, Any]] = []
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix=f"a1-rf-v5-{strategy_id}-") as td:
        root = Path(td)
        for idx, candidate in enumerate(generated):
            work = root / str(idx)
            work.mkdir()
            candidate = {**candidate, "identity_lock_applied_before_validator": True}
            reviews: dict[str, Any] = {}
            try:
                reviews["openai"] = openai_repair_review(candidate, evidence_rows)
            except Exception as exc:  # noqa: BLE001
                reviews["openai"] = {"successful": False, "error": af.safe_error(exc), "review_contract": "PRE_REPLAY_DESIGN_V5"}
            try:
                reviews["groq"] = groq_repair_review(candidate, evidence_rows)
            except Exception as exc:  # noqa: BLE001
                reviews["groq"] = {"successful": False, "error": af.safe_error(exc), "review_contract": "PRE_REPLAY_DESIGN_V5"}
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
                "pre_replay_review_contract": "V5",
            })

    reviewed.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("candidate_id") or "")))
    return {
        "strategy_id": strategy_id,
        "providers": providers,
        "reviewed": reviewed[:3],
        "compact_evidence_count": len(evidence),
        "groq_generator_max_tokens": v2.GROQ_MAX_TOKENS,
        "groq_review_model": os.environ.get("GROQ_REVIEW_MODEL", "").strip() or af.DEFAULT_GROQ_MODEL,
        "allowed_ready_common_axes": sorted(allowed_axes),
        "strict_repair_only": True,
        "identity_lock_applied_before_validator": True,
        "pre_replay_review_contract": "V5",
    }


def _flow_counts(ai_results: Mapping[str, Any]) -> dict[str, int]:
    totals = {
        "raw_generated": 0,
        "identity_locked": 0,
        "validated": 0,
        "quality_guard_passed": 0,
        "quality_guard_dropped": 0,
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
                totals["quality_guard_passed"] += int(p.get("quality_guard_passed_count") or 0)
                totals["quality_guard_dropped"] += int(p.get("quality_guard_dropped_count") or 0)
        rows = [x for x in (block.get("reviewed") or []) if isinstance(x, Mapping)]
        totals["reviewed"] += len(rows)
        totals["eligible"] += sum(1 for x in rows if x.get("eligible_for_experiment_queue") is True)
    return totals


def run(output: Path, *, network: bool = True, ai: bool = True, ai_strategy_limit: int = v1.AI_STRATEGY_LIMIT) -> dict[str, Any]:
    old_priority, old_scout = v1.priority_targets, v1.ai_scout
    try:
        v1.priority_targets = v3.strict_priority_targets
        v1.ai_scout = strict_ai_scout_v5
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
        "PASS_RESEARCH_FACTORY_V5_REVIEWED_REPAIR_READY"
        if direct else "HOLD_RESEARCH_FACTORY_V5_NO_ELIGIBLE_REPAIR"
    )
    result["queue_bridge"] = {
        "ready_common_first": True,
        "strict_exact_strategy_repair": True,
        "deterministic_identity_lock_before_validator": True,
        "semantic_placeholder_guard": True,
        "pre_replay_review_contract_aligned": True,
        "groq_review_model_separated_from_generator_model": True,
        "new_architecture_separated_from_repair_queue": True,
        "reviewed_candidate_survives_backlog_top5_truncation": True,
        "advanced_source_candidates_preserved": True,
        "common_sources": sorted(COMMON_READY),
    }
    result["policy"]["ready_common_first"] = True
    result["policy"]["strict_exact_strategy_repair"] = True
    result["policy"]["deterministic_identity_lock_before_validator"] = True
    result["policy"]["semantic_placeholder_guard"] = True
    result["policy"]["pre_replay_review_contract_aligned"] = True
    result["policy"]["new_architecture_separated_from_repair_queue"] = True
    result["policy"]["reviewed_bridge_bypasses_backlog_truncation"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    good = {
        "mechanism": "Lagged realized volatility changes the probability that the frozen entry signal receives directional follow-through.",
        "payer": "aggressive takers during volatility expansion",
        "entry_event": "the frozen signal fires after a completed-bar volatility-state classification",
        "direction_rule": "preserve existing direction rule",
        "native_horizon": "preserve the existing intraday holding horizon",
        "regime_owner": "permit the frozen signal only in the selected completed-bar volatility state",
        "invalidation": "the ownership state does not improve prospective after-cost expectancy",
        "exit_logic": "preserve existing exit geometry",
        "time_stop_rationale": "preserve the existing native time stop",
        "turnover_cost_budget": "the bounded replay must clear the existing verified cost reference",
        "falsification": "reject this repair if the frozen one-axis replay fails to improve prospective after-cost expectancy",
        "why_distinct": "only volatility-state ownership changes",
    }
    assert semantic_quality_guard(good) == (True, None)
    bad = dict(good); bad["mechanism"] = "why money exists and who pays"
    ok, reason = semantic_quality_guard(bad)
    assert ok is False and reason == "GENERATOR_CONTRACT_PLACEHOLDER:mechanism"
    review = _validate_review({
        "decision": "PASS_TO_REPLAY", "blocker_codes": [], "single_axis": True,
        "source_ready": True, "falsifiable": True, "reason": "bounded replay is structurally specified",
    })
    assert review["decision"] == "PASS_TO_REPLAY"
    try:
        _validate_review({
            "decision": "PASS_TO_REPLAY", "blocker_codes": ["MISSING"], "single_axis": True,
            "source_ready": True, "falsifiable": True, "reason": "invalid pass",
        })
    except RuntimeError:
        pass
    else:
        raise AssertionError("PASS_WITH_BLOCKER_ACCEPTED")
    print("PASS_A1_RESEARCH_FACTORY_V5_REVIEW_CONTRACT_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_v5.json"))
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
