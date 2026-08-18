from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_openai_critic_v1 import call_openai_critic

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
EVIDENCE = ROOT / "backend/research/architecture_factory/a1_free_evidence_sweep_v1.json"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_WORKERS_MODEL = "@cf/meta/llama-3.1-8b-instruct"


def canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(v: Any) -> str:
    return hashlib.sha256(canonical(v).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def safe_error(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    for marker in ("sk-", "gsk_", "cfut_", "AIza"):
        if marker in text:
            return f"{type(exc).__name__}:REDACTED"
    return f"{type(exc).__name__}:{text[:900]}"


def target_rows(ledger: Mapping[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    rows = []
    for sid, raw in (ledger.get("strategies") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        trades = int(raw.get("completed_trades") or 0)
        gross = raw.get("gross_expectancy_bps")
        net = raw.get("net_expectancy_bps")
        status = str(raw.get("status") or "")
        terminal = status.startswith("A1_") and status not in {"A1_SURVIVOR", "A1_EXACT25_BASELINE_SWEEP_ACTIVE"}
        early_negative = trades >= 3 and isinstance(net, (int, float)) and float(net) < 0
        cost_insufficient = trades >= 3 and isinstance(gross, (int, float)) and float(gross) > 0 and isinstance(net, (int, float)) and float(net) < 0
        if not (terminal or early_negative or cost_insufficient):
            continue
        priority = 0
        if cost_insufficient:
            priority += 100
        if terminal:
            priority += 30
        priority += min(trades, 30)
        if isinstance(gross, (int, float)) and gross < 0:
            priority -= min(abs(float(gross)), 80) / 10
        rows.append({
            "strategy_id": sid,
            "status": status,
            "completed_trades": trades,
            "gross_expectancy_bps": gross,
            "net_expectancy_bps": net,
            "profit_factor": raw.get("profit_factor"),
            "payoff": raw.get("payoff"),
            "win_rate": raw.get("win_rate"),
            "drawdown_bps": raw.get("drawdown_bps"),
            "verified_pretrade_cost_bps": raw.get("verified_pretrade_cost_bps"),
            "terminal": terminal,
            "cost_insufficient": cost_insufficient,
            "priority": priority,
        })
    rows.sort(key=lambda x: (-float(x["priority"]), x["strategy_id"]))
    return rows[:limit]


def evidence_compact(e: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in e.get("sources") or []:
        if not isinstance(row, Mapping):
            continue
        out.append({
            "id": row.get("id"), "tier": row.get("tier"), "source_type": row.get("source_type"),
            "identifier": row.get("identifier"), "claim": row.get("claim"),
            "applicable_families": row.get("applicable_families") or [], "limitations": row.get("limitations"),
        })
    return out


def generator_contract() -> dict[str, Any]:
    return {
        "candidates": [{
            "candidate_id": "string",
            "mode": "REPAIR|NEW_ARCHITECTURE",
            "strategy_id": "existing strategy id or NEW",
            "architecture_family": "string",
            "changed_axis": "exactly one causal axis id",
            "mechanism": "why money exists and who pays",
            "payer": "market participant/inefficiency",
            "entry_event": "entry-time observable event",
            "direction_rule": "long/short/both rule",
            "native_horizon": "natural holding horizon",
            "regime_owner": "when it should and should not trade",
            "invalidation": "causal invalidation",
            "exit_logic": "exit rationale without tuned thresholds",
            "time_stop_rationale": "why time stop fits mechanism",
            "turnover_cost_budget": "why expected move can dominate verified costs",
            "required_sources": ["ohlcv|volume|funding|basis|open_interest|l2_order_book|trade_flow"],
            "evidence_ids": ["F1"],
            "expected_move_cost_multiple_target": 2.0,
            "falsification": "one bounded prospective kill test",
            "forbidden_changes": ["fees", "best-horizon selection", "post-outcome loss deletion"],
            "why_distinct": "why not duplicate of current family",
        }]
    }


def generator_prompt(context: Mapping[str, Any]) -> str:
    return (
        "You are a strategy-architecture researcher, not a parameter tuner. Generate exactly 4 research candidates. "
        "At least 2 must be genuinely NEW_ARCHITECTURE candidates with a natural expected-move horizon large enough to plausibly dominate the verified round-trip cost; do not concentrate only on 5m scalps. "
        "At most 2 may be REPAIR candidates for existing families, and each repair must change exactly ONE causal axis. "
        "Use only entry-time observable data from the available source vocabulary. Never lower fees, cherry-pick a horizon after outcomes, delete losers after outcomes, expose or infer sealed holdout outcomes, or bundle multiple repair axes. "
        "Community sources are hypothesis-only; primary sources must anchor the mechanism. Numeric entry thresholds are forbidden at this generation stage. "
        "Target expected_move_cost_multiple_target >= 2.0 when economically plausible, but treat it as a design objective, never as evidence of achieved performance. "
        "Return JSON only matching this shape: " + canonical(generator_contract()) + "\nCONTEXT=" + canonical(context)
    )


def validate_candidates(value: Any, provider: str, evidence_ids: set[str], target_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("candidates"), list):
        raise RuntimeError("GENERATOR_SHAPE_INVALID")
    out = []
    for idx, row in enumerate(value["candidates"]):
        if not isinstance(row, Mapping):
            continue
        mode = str(row.get("mode") or "")
        sid = str(row.get("strategy_id") or "")
        axis = str(row.get("changed_axis") or "").strip()
        evid = [str(x) for x in (row.get("evidence_ids") or [])]
        req = [str(x) for x in (row.get("required_sources") or [])]
        if mode not in {"REPAIR", "NEW_ARCHITECTURE"} or not axis or not evid or not all(x in evidence_ids for x in evid):
            continue
        if mode == "REPAIR" and sid not in target_ids:
            continue
        if mode == "NEW_ARCHITECTURE":
            sid = "NEW"
        multiple = row.get("expected_move_cost_multiple_target")
        try:
            multiple = float(multiple)
        except (TypeError, ValueError):
            multiple = 0.0
        item = {
            "candidate_id": str(row.get("candidate_id") or f"{provider}-{idx+1}"),
            "provider": provider,
            "mode": mode,
            "strategy_id": sid,
            "architecture_family": str(row.get("architecture_family") or "")[:160],
            "changed_axis": axis[:160],
            "mechanism": str(row.get("mechanism") or "")[:1800],
            "payer": str(row.get("payer") or "")[:800],
            "entry_event": str(row.get("entry_event") or "")[:1000],
            "direction_rule": str(row.get("direction_rule") or "")[:600],
            "native_horizon": str(row.get("native_horizon") or "")[:600],
            "regime_owner": str(row.get("regime_owner") or "")[:1000],
            "invalidation": str(row.get("invalidation") or "")[:1000],
            "exit_logic": str(row.get("exit_logic") or "")[:1000],
            "time_stop_rationale": str(row.get("time_stop_rationale") or "")[:800],
            "turnover_cost_budget": str(row.get("turnover_cost_budget") or "")[:1000],
            "required_sources": req,
            "evidence_ids": evid,
            "expected_move_cost_multiple_target": multiple,
            "falsification": str(row.get("falsification") or "")[:1200],
            "forbidden_changes": [str(x) for x in (row.get("forbidden_changes") or [])],
            "why_distinct": str(row.get("why_distinct") or "")[:1000],
        }
        if not all(item[k] for k in ("architecture_family", "mechanism", "entry_event", "native_horizon", "regime_owner", "falsification")):
            continue
        item["candidate_sha256"] = sha(item)
        out.append(item)
    if not out:
        raise RuntimeError("NO_VALID_GENERATED_CANDIDATES")
    return out


def extract_openai_text(payload: Mapping[str, Any]) -> str:
    parts = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for part in item.get("content") or []:
            if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("OPENAI_FACTORY_EMPTY_RESPONSE")
    return text


def call_openai_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5-mini"
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    body = {
        "model": model, "store": False,
        "instructions": "Return only the requested strategy architecture JSON. No tools or external web.",
        "input": prompt, "max_output_tokens": 5000,
        "reasoning": {"effort": "minimal"},
        "text": {"format": {"type": "json_schema", "name": "a1_architecture_factory", "strict": False,
                 "schema": {"type": "object", "properties": {"candidates": {"type": "array", "items": {"type": "object"}}}, "required": ["candidates"], "additionalProperties": False}}},
    }
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=canonical(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"OPENAI_FACTORY_HTTP_{exc.code}:{detail}") from exc
    text = extract_openai_text(payload)
    return model, json.loads(text), {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(), "response_sha": hashlib.sha256(text.encode()).hexdigest()}


def call_groq_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY_MISSING")
    from groq import Groq
    model = os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
    client = Groq(api_key=key)
    comp = client.chat.completions.create(model=model, temperature=0.15, max_tokens=4500,
        messages=[{"role": "user", "content": prompt + "\nReturn one JSON object only."}])
    text = (comp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("GROQ_FACTORY_JSON_MISSING")
    parsed = json.loads(text[start:end+1])
    return model, parsed, {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(), "response_sha": hashlib.sha256(text.encode()).hexdigest()}


def token_vector(candidate: Mapping[str, Any]) -> Counter[str]:
    text = " ".join(str(candidate.get(k) or "") for k in ("architecture_family", "changed_axis", "mechanism", "entry_event", "regime_owner", "native_horizon"))
    return Counter(re.findall(r"[a-z0-9_]+", text.lower()))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v*v for v in a.values())); nb = math.sqrt(sum(v*v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def dedup(candidates: list[dict[str, Any]], threshold: float = 0.85) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in candidates:
        v = token_vector(candidate)
        if any(cosine(v, token_vector(old)) > threshold for old in kept):
            continue
        kept.append(candidate)
    return kept


def critic_payload(c: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": c.get("strategy_id") or "NEW",
        "candidate_axis": c.get("changed_axis"), "changed_axes": [c.get("changed_axis")],
        "lineage_complete": bool(c.get("evidence_ids")),
        "hypothesis": {"axis": c.get("changed_axis"), "mechanism": c.get("mechanism"), "falsification": c.get("falsification"),
                       "required_data": c.get("required_sources"), "native_horizon": c.get("native_horizon")},
        "evidence": {"axis_sources": c.get("evidence_ids"), "design_cost_multiple_target": c.get("expected_move_cost_multiple_target")},
        "lineage": {"candidate_sha": c.get("candidate_sha256"), "source_ids": c.get("evidence_ids")},
        "research_only": True, "promotion_authority": False, "protected_mutations": 0,
        "execution_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "runtime_bound": False,
    }


def openai_critic(c: Mapping[str, Any]) -> dict[str, Any]:
    proposer = {"status": "PASS", "proposals": [{"proposal_type": "FEATURE_AUGMENTATION" if c.get("mode") == "REPAIR" else "NEW_ARCHITECTURE",
        "family_id": str(c.get("architecture_family") or "candidate")[:48], "economic_mechanism": c.get("mechanism"),
        "required_sources": c.get("required_sources") or [], "causal_reason": c.get("payer"), "falsification_test": c.get("falsification"),
        "expected_horizon": c.get("native_horizon")}]} 
    model = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5-mini"
    actual, receipt = call_openai_critic(os.environ.get("OPENAI_API_KEY", "").strip(), model, proposer, timeout_sec=60, max_output_tokens=1000)
    return {"successful": True, "model": actual, "decision": receipt.get("decision"), "reason": receipt.get("reason"),
            "input_sha": receipt.get("input_sha"), "prompt_sha": receipt.get("prompt_sha"), "response_sha": receipt.get("response_sha")}


def subprocess_review(script: str, c: Mapping[str, Any], work: Path, env: Mapping[str, str], kind: str) -> dict[str, Any]:
    inp = work / f"{kind}_input.json"; out = work / f"{kind}_output.json"
    inp.write_text(json.dumps(critic_payload(c), sort_keys=True), encoding="utf-8")
    cmd = [sys.executable, script, "--input", str(inp), "--output", str(out)]
    if kind == "workers":
        cmd += ["--model", os.environ.get("WORKERS_AI_MODEL", "").strip() or DEFAULT_WORKERS_MODEL]
    cp = subprocess.run(cmd, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    data = read_json(out) if out.is_file() else {}
    review = data.get("review") if isinstance(data.get("review"), Mapping) else {}
    decision = review.get("decision")
    return {"successful": cp.returncode == 0, "decision": decision, "model": data.get("actual_model") or data.get("model"),
            "reason": review.get("reason"), "input_sha": data.get("input_sha"), "prompt_sha": data.get("prompt_sha"),
            "response_sha": data.get("response_sha"), "error": None if cp.returncode == 0 else (data.get("blocker_code") or cp.stderr[-800:])}


def base_score(c: Mapping[str, Any]) -> float:
    score = min(float(c.get("expected_move_cost_multiple_target") or 0), 4.0) * 2
    score += min(len(c.get("evidence_ids") or []), 4) * 0.8
    score += 2.0 if c.get("mode") == "NEW_ARCHITECTURE" else 1.0
    score += 1.0 if len(c.get("required_sources") or []) <= 3 else 0.0
    return score


def run(output: Path) -> dict[str, Any]:
    ledger, evidence = read_json(LEDGER), read_json(EVIDENCE)
    targets = target_rows(ledger)
    source_rows = evidence_compact(evidence)
    source_ids = {str(x.get("id")) for x in source_rows}
    target_ids = {str(x["strategy_id"]) for x in targets}
    verified_cost = 14.0
    context = {
        "objective": "find first robust after-cost survivor faster; prefer mechanism diversity and larger move/cost geometry",
        "verified_round_trip_cost_bps_reference": verified_cost,
        "available_source_vocabulary": ["ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"],
        "current_failure_targets": targets,
        "external_evidence": source_rows,
        "constraints": {"baseline_mutation": False, "threshold_sweep": False, "best_horizon_cherry_pick": False,
                        "fee_reduction": False, "sealed_holdout_visibility": False, "new_architecture_allowed": True},
    }
    prompt = generator_prompt(context)
    generators: dict[str, Any] = {}; candidates: list[dict[str, Any]] = []
    for provider, fn in (("openai", call_openai_generator), ("groq", call_groq_generator)):
        try:
            model, raw, lineage = fn(prompt)
            got = validate_candidates(raw, provider, source_ids, target_ids)
            generators[provider] = {"successful": True, "model": model, **lineage, "candidate_count": len(got)}
            candidates.extend(got)
        except Exception as exc:
            generators[provider] = {"successful": False, "error": safe_error(exc)}
    candidates = dedup(sorted(candidates, key=lambda x: -base_score(x)))[:6]
    env = os.environ.copy(); reviews = []
    with tempfile.TemporaryDirectory(prefix="a1-architecture-factory-") as td:
        root = Path(td)
        for i, c in enumerate(candidates):
            work = root / str(i); work.mkdir()
            provider_reviews: dict[str, Any] = {}
            # Cross-review: never count the generator provider as the only independent reviewer.
            try:
                provider_reviews["openai"] = openai_critic(c)
            except Exception as exc:
                provider_reviews["openai"] = {"successful": False, "error": safe_error(exc)}
            provider_reviews["groq"] = subprocess_review("scripts/strategy11_groq_redteam.py", c, work, env, "groq")
            provider_reviews["workers_ai"] = subprocess_review("scripts/strategy11_workers_ai_guard.py", c, work, env, "workers")
            passes = 0; rejects = 0
            for name, r in provider_reviews.items():
                if name == c.get("provider"):
                    continue
                decision = str(r.get("decision") or "")
                if r.get("successful") and decision in {"PASS", "PASS_TO_REPLAY"}:
                    passes += 1
                if r.get("successful") and decision == "REJECT":
                    rejects += 1
            economic_design_score = base_score(c)
            final_score = economic_design_score + passes * 2.5 - rejects * 4.0
            reviews.append({**c, "cross_reviews": provider_reviews, "independent_passes": passes,
                            "independent_rejects": rejects, "score": round(final_score, 4),
                            "eligible_for_preregistration": passes >= 2 and rejects == 0})
    reviews.sort(key=lambda x: (-float(x["score"]), x["candidate_id"]))
    top3 = reviews[:3]
    state = "PASS_ARCHITECTURE_FACTORY_TOP3_READY" if any(x.get("eligible_for_preregistration") for x in top3) else "HOLD_ARCHITECTURE_FACTORY_NO_ACCEPTABLE_CANDIDATE"
    result = {
        "schema_version": "zel.a1_strategy_architecture_factory.v1", "state": state,
        "baseline_ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
        "evidence_sweep_sha256": hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
        "targets": targets, "generators": generators, "generated_after_dedup": len(candidates),
        "dedup_cosine_threshold": 0.85, "top3": top3, "all_reviewed_candidates": reviews,
        "survivor_count_at_generation": int(ledger.get("survivor_count") or 0),
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    a = {"architecture_family": "momentum basis unwind", "changed_axis": "basis", "mechanism": "funding basis unwind", "entry_event": "basis", "regime_owner": "extreme basis", "native_horizon": "hours"}
    b = dict(a)
    c = {"architecture_family": "order flow reversal", "changed_axis": "flow", "mechanism": "exhaustion", "entry_event": "flow reversal", "regime_owner": "liquid", "native_horizon": "minutes"}
    assert cosine(token_vector(a), token_vector(b)) > 0.99
    assert cosine(token_vector(a), token_vector(c)) < 0.85
    assert len(dedup([a, b, c])) == 2
    print("PASS_A1_STRATEGY_ARCHITECTURE_FACTORY_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, default=Path("out/a1_strategy_architecture_factory.json")); ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({"state": result["state"], "generated_after_dedup": result["generated_after_dedup"],
                      "top3": [{"id": x["candidate_id"], "mode": x["mode"], "family": x["architecture_family"], "score": x["score"], "eligible": x["eligible_for_preregistration"]} for x in result["top3"]],
                      "generators": result["generators"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
