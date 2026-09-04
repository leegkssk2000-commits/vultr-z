#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
FAILURE = ROOT / "backend/research/prep/rr_exit_true_fresh6_observer_latest.json"
CONTRACT = ROOT / "backend/research/contracts/g5_exit_research_contract_v1.json"
CURRENT = ROOT / "backend/research/prep/g5_exit_ai_research_latest.json"
SCHEMA = "zel.g5.exit_ai_research.v1"
DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.7-flash"
MAX_REQUESTS = 2
ALLOWED = {
    "TIME_DECAY_EXIT",
    "VOLATILITY_ADAPTIVE_STOP",
    "MFE_RUNNER",
    "PARTIAL_TRAIL",
    "REGIME_CONDITIONED_EXIT",
}


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def maybe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read(path)
    except Exception:
        return None


def failure_signature(failure: Mapping[str, Any]) -> dict[str, Any]:
    candidate = failure.get("candidate") if isinstance(failure.get("candidate"), Mapping) else {}
    native = failure.get("native_control") if isinstance(failure.get("native_control"), Mapping) else {}
    return {
        "state": failure.get("state"),
        "strategy_id": failure.get("strategy_id"),
        "lane_id": failure.get("lane_id"),
        "validation_T": failure.get("validation_T"),
        "candidate": {k: candidate.get(k) for k in ("trades", "wins", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps")},
        "native": {k: native.get(k) for k in ("trades", "wins", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps")},
        "frozen_nominal_rr": failure.get("frozen_nominal_rr"),
        "frozen_sl_r": failure.get("frozen_sl_r"),
        "frozen_tp_r": failure.get("frozen_tp_r"),
        "strict_checks": failure.get("strict_checks"),
        "next": failure.get("next"),
    }


def model_candidates() -> list[str]:
    raw = [
        os.environ.get("GEMINI_EXIT_RESEARCH_MODEL") or "",
        os.environ.get("GEMINI_WEB_RESEARCH_MODEL") or "",
        os.environ.get("GEMINI_MODEL") or "",
        DEFAULT_MODEL,
    ]
    out: list[str] = []
    for x in raw:
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def prompt_for(sig: Mapping[str, Any]) -> str:
    return f"""You are researching exit architecture for a crypto perpetual-futures system. This is G5 observer-only research: entry edge is frozen, no live/order authority, no promotion, and your output has zero formal credit.

Observed true prospective failure signature:
{json.dumps(sig, sort_keys=True)}

The prior fixed RR geometry produced an apparent pre-preregister success but failed the true post-freeze 6-trade prospective test and worsened loss versus native. Do not rescue RR_GEOMETRY by changing TP/SL numbers.

Use Google Search grounding and return ONE JSON object only. Requirements:
1. Diagnose mechanisms that can make extreme fixed reward:risk look good in a small holdout and fail prospectively.
2. Rank these five distinct families for investigation, without numeric parameter tuning: TIME_DECAY_EXIT, VOLATILITY_ADAPTIVE_STOP, MFE_RUNNER, PARTIAL_TRAIL, REGIME_CONDITIONED_EXIT.
3. For each ranked family return family_id, mechanism, why_matches_failure, required_data, causal_test, primary_risk.
4. Propose at most one genuinely distinct new exit family, with family_id, mechanism, required_data, causal_test, why_distinct. It must not be fixed TP/SL or RR geometry.
5. Explicitly list do_not_do items covering hindsight thresholds, historical-union promotion, entry mutation, and future-data inference.
6. Prefer primary/technical/academic/exchange-quality sources. Do not claim any family will be profitable.

Schema: {{"diagnosis":"...","ranked_families":[...],"new_family":{{...}} or null,"do_not_do":[...]}}"""


def extract_text(payload: Mapping[str, Any]) -> str:
    for cand in payload.get("candidates") or []:
        if not isinstance(cand, Mapping):
            continue
        content = cand.get("content") if isinstance(cand.get("content"), Mapping) else {}
        parts = content.get("parts") or []
        text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, Mapping))
        if text.strip():
            return text.strip()
    raise RuntimeError("GEMINI_EMPTY_RESPONSE")


def parse_json_text(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:].lstrip()
    x = json.loads(s)
    if not isinstance(x, dict):
        raise RuntimeError("AI_JSON_OBJECT_REQUIRED")
    return x


def grounding(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    cand = next((x for x in payload.get("candidates") or [] if isinstance(x, Mapping)), {})
    g = cand.get("groundingMetadata") if isinstance(cand, Mapping) and isinstance(cand.get("groundingMetadata"), Mapping) else {}
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in g.get("groundingChunks") or []:
        web = chunk.get("web") if isinstance(chunk, Mapping) and isinstance(chunk.get("web"), Mapping) else {}
        uri, title = str(web.get("uri") or ""), str(web.get("title") or "")
        key = (uri, title)
        if (uri or title) and key not in seen:
            seen.add(key); sources.append({"uri": uri, "title": title})
    return sources, [str(x) for x in g.get("webSearchQueries") or []]


def usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    u = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), Mapping) else {}
    return {
        "input_tokens": int(u.get("promptTokenCount") or 0),
        "output_tokens": int(u.get("candidatesTokenCount") or 0),
        "total_tokens": int(u.get("totalTokenCount") or 0),
        "estimated_cost_eur": None,
        "cost_authority_missing": True,
    }


def validate_research(x: Mapping[str, Any]) -> None:
    ranked = x.get("ranked_families")
    if not isinstance(ranked, list) or not (3 <= len(ranked) <= 5):
        raise RuntimeError("AI_RANKED_FAMILIES_COUNT_INVALID")
    ids: list[str] = []
    for row in ranked:
        if not isinstance(row, Mapping):
            raise RuntimeError("AI_FAMILY_OBJECT_REQUIRED")
        fid = str(row.get("family_id") or "")
        if fid not in ALLOWED or fid in ids:
            raise RuntimeError(f"AI_FAMILY_ID_INVALID:{fid}")
        ids.append(fid)
        for key in ("mechanism", "why_matches_failure", "required_data", "causal_test", "primary_risk"):
            if not row.get(key):
                raise RuntimeError(f"AI_FAMILY_FIELD_MISSING:{fid}:{key}")
    new = x.get("new_family")
    if new is not None:
        if not isinstance(new, Mapping):
            raise RuntimeError("AI_NEW_FAMILY_OBJECT_REQUIRED")
        fid = str(new.get("family_id") or "")
        if not fid or fid in ALLOWED or "RR" in fid.upper():
            raise RuntimeError(f"AI_NEW_FAMILY_NOT_DISTINCT:{fid}")
        for key in ("mechanism", "required_data", "causal_test", "why_distinct"):
            if not new.get(key):
                raise RuntimeError(f"AI_NEW_FAMILY_FIELD_MISSING:{key}")
    if not x.get("diagnosis") or not isinstance(x.get("do_not_do"), list):
        raise RuntimeError("AI_DIAGNOSIS_OR_GUARD_MISSING")


def call_gemini(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    api_base = (os.environ.get("GEMINI_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    body = {
        "systemInstruction": {"parts": [{"text": "Return source-grounded JSON only. Never infer holdout/future outcomes and never claim profitability."}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 6000, "responseMimeType": "application/json"},
    }
    data = json.dumps(body, separators=(",", ":")).encode()
    attempts: list[dict[str, Any]] = []
    last_error = ""
    for model in model_candidates():
        if len(attempts) >= MAX_REQUESTS:
            break
        trace = {"request_no": len(attempts) + 1, "model": model}
        try:
            req = urllib.request.Request(f"{api_base}/models/{model}:generateContent", data=data, headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                trace["http_status"] = int(getattr(resp, "status", 200) or 200)
            text = extract_text(payload)
            parsed = parse_json_text(text)
            validate_research(parsed)
            sources, queries = grounding(payload)
            trace["outcome"] = "SUCCESS"; attempts.append(trace)
            return parsed, {
                "provider": "gemini",
                "model": model,
                "request_count": len(attempts),
                "attempts": attempts,
                "source_count": len(sources),
                "sources": sources[:12],
                "web_search_queries": queries,
                "usage": usage(payload),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "raw_response_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"[:600]
            trace["outcome"] = "ERROR"; trace["error"] = last_error; attempts.append(trace)
            continue
    raise RuntimeError(f"GEMINI_EXIT_RESEARCH_FAILED:{last_error}")


def run(*, failure_path: Path, current_path: Path, output: Path, allow_network: bool) -> dict[str, Any]:
    failure = read(failure_path)
    contract = read(CONTRACT)
    sig = failure_signature(failure)
    sig_sha = stable(sig)
    current = maybe_read(current_path)
    if current and current.get("failure_signature_sha256") == sig_sha and current.get("state") == "PASS_SOURCE_GROUNDED_EXIT_MECHANISM_RESEARCH":
        result = dict(current)
        result["cache_hit"] = True
        result["provider_call_this_run"] = False
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        return result
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "HOLD_NO_NETWORK",
        "stage": "G5",
        "failure_signature": sig,
        "failure_signature_sha256": sig_sha,
        "legacy_rr_geometry_rejected": contract["search_rules"]["legacy_rr_geometry_family_rejected"],
        "formal_credit": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "cache_hit": False,
        "provider_call_this_run": False,
    }
    if allow_network:
        try:
            research, provider = call_gemini(prompt_for(sig))
            result["provider_call_this_run"] = True
            result["provider"] = provider
            result["research"] = research
            if int(provider.get("source_count") or 0) >= int(contract["paid_ai_gate"]["minimum_grounded_sources"]):
                result["state"] = "PASS_SOURCE_GROUNDED_EXIT_MECHANISM_RESEARCH"
            else:
                result["state"] = "HOLD_GROUNDING_SOURCES_INSUFFICIENT"
        except Exception as exc:
            result["provider_call_this_run"] = True
            result["state"] = "HOLD_PAID_AI_PROVIDER_ERROR"
            result["provider_error"] = f"{type(exc).__name__}:{exc}"[:800]
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    f = {"state": "FAIL", "strategy_id": "trend_rider", "lane_id": "x", "validation_T": 6, "candidate": {"net_pnl_bps": -10}, "native_control": {"net_pnl_bps": -5}, "frozen_nominal_rr": 20, "frozen_sl_r": 3, "frozen_tp_r": 60, "strict_checks": {}, "next": "route"}
    sig = failure_signature(f)
    assert stable(sig) == stable(failure_signature(f))
    good = {"diagnosis": "x", "ranked_families": [
        {"family_id": "TIME_DECAY_EXIT", "mechanism": "a", "why_matches_failure": "b", "required_data": ["x"], "causal_test": "c", "primary_risk": "d"},
        {"family_id": "MFE_RUNNER", "mechanism": "a", "why_matches_failure": "b", "required_data": ["x"], "causal_test": "c", "primary_risk": "d"},
        {"family_id": "PARTIAL_TRAIL", "mechanism": "a", "why_matches_failure": "b", "required_data": ["x"], "causal_test": "c", "primary_risk": "d"},
    ], "new_family": None, "do_not_do": ["x"]}
    validate_research(good)
    assert MAX_REQUESTS == 2
    print("PASS_G5_EXIT_AI_RESEARCH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure", type=Path, default=FAILURE)
    ap.add_argument("--current", type=Path, default=CURRENT)
    ap.add_argument("--output", type=Path, default=Path("out/g5_exit_ai_research_latest.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(failure_path=args.failure, current_path=args.current, output=args.output, allow_network=not args.no_network)
    print(json.dumps({"state": r["state"], "provider_call": r.get("provider_call_this_run"), "source_count": (r.get("provider") or {}).get("source_count"), "cache_hit": r.get("cache_hit")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
