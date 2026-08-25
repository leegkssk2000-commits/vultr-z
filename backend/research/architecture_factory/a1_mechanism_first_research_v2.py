#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_mechanism_first_research_v1 as v1
from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as af

SCHEMA = "zel.a1_mechanism_first_research.v2"
DEFAULT_FALLBACK_MODEL = "allam-2-7b"


def _compact_prompt(prompt: str) -> str:
    marker = "\nCONTEXT="
    if marker not in prompt:
        return prompt[:12000]
    head, tail = prompt.split(marker, 1)
    suffix = ""
    if "\nCOMMON_READY_NEW_ARCHITECTURE_REQUIRED:" in tail:
        raw_context, extra = tail.split("\nCOMMON_READY_NEW_ARCHITECTURE_REQUIRED:", 1)
        suffix = "\nCOMMON_READY_NEW_ARCHITECTURE_REQUIRED:" + extra
    else:
        raw_context = tail
    try:
        context = json.loads(raw_context)
    except Exception:
        return prompt[:12000]

    compact_sources = []
    for raw in context.get("external_evidence") or []:
        if not isinstance(raw, Mapping):
            continue
        compact_sources.append({
            "id": raw.get("id"),
            "tier": raw.get("tier"),
            "source_type": raw.get("source_type"),
            "claim": str(raw.get("claim") or "")[:240],
            "applicable_families": list(raw.get("applicable_families") or [])[:6],
        })
    compact_targets = []
    for raw in context.get("current_failure_targets") or []:
        if not isinstance(raw, Mapping):
            continue
        compact_targets.append({
            "strategy_id": raw.get("strategy_id"),
            "status": raw.get("status"),
            "completed_trades": raw.get("completed_trades"),
            "gross_expectancy_bps": raw.get("gross_expectancy_bps"),
            "net_expectancy_bps": raw.get("net_expectancy_bps"),
            "profit_factor": raw.get("profit_factor"),
            "win_rate": raw.get("win_rate"),
            "drawdown_bps": raw.get("drawdown_bps"),
            "cost_insufficient": raw.get("cost_insufficient"),
        })
    compact = {
        "objective": context.get("objective"),
        "verified_round_trip_cost_bps_reference": context.get("verified_round_trip_cost_bps_reference"),
        "available_source_vocabulary": context.get("available_source_vocabulary"),
        "current_failure_targets": compact_targets,
        "external_evidence": compact_sources,
        "constraints": context.get("constraints"),
        "provider_compaction": "CLAIMS_TRUNCATED_FOR_GROQ_TPM_ONLY; EVIDENCE_IDS_AND_CAUSAL_FIELDS_PRESERVED",
    }
    return head + marker + af.canonical(compact) + suffix


def _groq_once(prompt: str, model: str, max_tokens: int = 3000) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY_MISSING")
    from groq import Groq
    client = Groq(api_key=key)
    comp = client.chat.completions.create(
        model=model,
        temperature=0.12,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt + "\nReturn one JSON object only."}],
    )
    text = (comp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("GROQ_FACTORY_JSON_MISSING")
    parsed = json.loads(text[start:end + 1])
    return model, parsed, {
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha": hashlib.sha256(text.encode()).hexdigest(),
    }


def compact_groq_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    compact = _compact_prompt(prompt)
    primary = os.environ.get("GROQ_MODEL", "").strip() or af.DEFAULT_GROQ_MODEL
    fallback = os.environ.get("GROQ_FALLBACK_MODEL", "").strip() or DEFAULT_FALLBACK_MODEL
    errors: list[str] = []
    for model in dict.fromkeys([primary, fallback]):
        try:
            actual, parsed, lineage = _groq_once(compact, model, max_tokens=3000)
            lineage["compact_prompt"] = "true"
            lineage["fallback_used"] = "true" if model != primary else "false"
            return actual, parsed, lineage
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{str(exc)[:300]}")
    raise RuntimeError("GROQ_COMPACT_GENERATOR_FAILED:" + " | ".join(errors))


def run(output: Path) -> dict[str, Any]:
    old = af.call_groq_generator
    try:
        af.call_groq_generator = compact_groq_generator
        result = v1.run(output)
    finally:
        af.call_groq_generator = old
    result["schema_version"] = SCHEMA
    result["provider_resilience"] = {
        "groq_prompt_compaction": True,
        "groq_generation_max_tokens": 3000,
        "groq_fallback_model": os.environ.get("GROQ_FALLBACK_MODEL", "").strip() or DEFAULT_FALLBACK_MODEL,
        "reason": "Avoid generator loss from 8k TPM overflow without weakening evidence, guard, or promotion gates.",
    }
    result["receipt_sha256"] = af.sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    context = {
        "objective": "x",
        "verified_round_trip_cost_bps_reference": 14.0,
        "available_source_vocabulary": ["ohlcv", "volume"],
        "current_failure_targets": [{"strategy_id": "x", "status": "A1_FAIL", "completed_trades": 20, "net_expectancy_bps": -1}],
        "external_evidence": [{"id": "F1", "tier": "paper", "source_type": "paper", "claim": "A" * 5000, "applicable_families": ["trend"]}],
        "constraints": {"threshold_sweep": False},
    }
    p = "HEAD\nCONTEXT=" + json.dumps(context) + "\nCOMMON_READY_NEW_ARCHITECTURE_REQUIRED:test"
    compact = _compact_prompt(p)
    assert len(compact) < len(p)
    assert "F1" in compact and "COMMON_READY_NEW_ARCHITECTURE_REQUIRED" in compact
    assert "provider_compaction" in compact
    print("PASS_A1_MECHANISM_FIRST_RESEARCH_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_mechanism_first_research_raw.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    n = r.get("next_experiment_candidate") or {}
    print(json.dumps({
        "state": r.get("state"),
        "new_ready": r.get("new_architecture_ready_count"),
        "new_source_wait": r.get("new_architecture_source_wait_count"),
        "legacy_backlog": r.get("legacy_repair_backlog_count"),
        "next": n.get("candidate_id"),
        "generators": r.get("generator_status"),
        "provider_resilience": r.get("provider_resilience"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
