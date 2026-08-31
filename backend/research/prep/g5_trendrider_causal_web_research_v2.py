#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_causal_web_research_v1 as base

SCHEMA = "zel.g5.trendrider.causal_web_research.resilience.v2"
TRANSIENT_HTTP = {429, 500, 502, 503, 504}
ATTEMPTS_PER_MODEL = 2
MAX_REQUESTS = 4
TRANSIENT_CACHE_STATES = {"HOLD_WEB_RESEARCH_PROVIDER_ERROR"}
LAST_ATTEMPTS: list[dict[str, Any]] = []
LAST_MODELS: list[str] = []


def _dedup(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def model_candidates() -> list[str]:
    fallback = [x.strip() for x in (os.environ.get("GEMINI_WEB_RESEARCH_FALLBACK_MODELS") or "").split(",") if x.strip()]
    return _dedup([
        os.environ.get("GEMINI_WEB_RESEARCH_MODEL") or "",
        os.environ.get("GEMINI_MODEL") or "",
        base.DEFAULT_MODEL,
        *fallback,
    ])


def retryable_http(status: int) -> bool:
    return int(status) in TRANSIENT_HTTP


def transient_current(value: Mapping[str, Any] | None) -> bool:
    return bool(isinstance(value, Mapping) and str(value.get("state") or "") in TRANSIENT_CACHE_STATES and not value.get("selected_candidate"))


def _sleep_for(attempt_no: int) -> None:
    delay = 2.0 if attempt_no <= 1 else 5.0
    time.sleep(delay)


def _extract_grounding(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str], int]:
    first = next((x for x in payload.get("candidates") or [] if isinstance(x, Mapping)), {})
    grounding = first.get("groundingMetadata") if isinstance(first, Mapping) else {}
    grounding = grounding if isinstance(grounding, Mapping) else {}
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in grounding.get("groundingChunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        web = chunk.get("web")
        if not isinstance(web, Mapping):
            continue
        uri = str(web.get("uri") or "").strip()
        title = str(web.get("title") or "").strip()
        key = (uri, title)
        if not (uri or title) or key in seen:
            continue
        seen.add(key)
        sources.append({"uri": uri, "title": title})
    queries = [str(x) for x in grounding.get("webSearchQueries") or []]
    supports = len(grounding.get("groundingSupports") or [])
    return sources, queries, supports


def robust_call_grounded_gemini(prompt: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    global LAST_ATTEMPTS, LAST_MODELS
    LAST_ATTEMPTS = []
    LAST_MODELS = []

    base.paid_gate.configure_target(base.LANE_ID, "G5", base.TARGET_GATE)
    target = base.paid_gate.require_target_binding(provider="gemini")
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    api_base = (os.environ.get("GEMINI_API_BASE") or base.gemini.DEFAULT_GEMINI_API_BASE).strip().rstrip("/")
    bound, _ = base.paid_gate.bound_prompt(prompt, provider="gemini", purpose="BOUNDED_G4_OR_G5_CAUSAL_REPAIR")
    body = {
        "systemInstruction": {"parts": [{"text": "Use Google Search grounding. Return one compact JSON object and no markdown. Every recommendation must be source-grounded; never infer future/holdout outcomes."}]},
        "contents": [{"role": "user", "parts": [{"text": bound}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 6000, "responseMimeType": "application/json"},
    }
    payload_bytes = base.canonical(body).encode("utf-8")
    models = model_candidates()
    if not models:
        raise RuntimeError("GEMINI_MODEL_CANDIDATES_EMPTY")

    request_count = 0
    last_error = ""
    for model in models:
        if request_count >= MAX_REQUESTS:
            break
        LAST_MODELS.append(model)
        for model_attempt in range(1, ATTEMPTS_PER_MODEL + 1):
            if request_count >= MAX_REQUESTS:
                break
            request_count += 1
            url = f"{api_base}/models/{model}:generateContent"
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                method="POST",
            )
            trace: dict[str, Any] = {
                "request_no": request_count,
                "model": model,
                "model_attempt": model_attempt,
                "outcome": "PENDING",
                "http_status": None,
            }
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    trace["http_status"] = int(getattr(resp, "status", 200) or 200)
                text = base.gemini._extract_text(payload)
                parsed = base.gemini._extract_json(text)
                sources, queries, supports = _extract_grounding(payload)
                trace["outcome"] = "SUCCESS"
                trace["source_count"] = len(sources)
                LAST_ATTEMPTS.append(trace)
                meta = {
                    "provider": "gemini",
                    "model": model,
                    "request_count": request_count,
                    "prompt_sha256": hashlib.sha256(bound.encode("utf-8")).hexdigest(),
                    "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "web_search_queries": queries,
                    "sources": sources[:12],
                    "source_count": len(sources),
                    "grounding_support_count": supports,
                    "usage": base.gemini._usage_meta(payload),
                    "target_binding": target,
                    "attempts": list(LAST_ATTEMPTS),
                    "models_attempted": list(LAST_MODELS),
                    "retry_policy": {
                        "transient_http": sorted(TRANSIENT_HTTP),
                        "attempts_per_model": ATTEMPTS_PER_MODEL,
                        "max_requests": MAX_REQUESTS,
                    },
                    "last_error": None,
                }
                return text, parsed, meta
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:800]
                status = int(exc.code)
                retryable = retryable_http(status)
                last_error = f"HTTP_{status}:{detail}"
                trace.update({"outcome": "TRANSIENT_HTTP" if retryable else "HARD_HTTP", "http_status": status, "error": last_error})
                LAST_ATTEMPTS.append(trace)
                if not retryable:
                    raise RuntimeError(f"GEMINI_GROUNDED_RESEARCH_HTTP_{status}:{detail}") from exc
                if request_count < MAX_REQUESTS:
                    _sleep_for(model_attempt)
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
                last_error = f"{type(exc).__name__}:{exc}"[:800]
                trace.update({"outcome": "TRANSIENT_TRANSPORT", "error": last_error})
                LAST_ATTEMPTS.append(trace)
                if request_count < MAX_REQUESTS:
                    _sleep_for(model_attempt)
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"[:800]
                trace.update({"outcome": "HARD_RESPONSE", "error": last_error})
                LAST_ATTEMPTS.append(trace)
                raise

    raise RuntimeError(f"GEMINI_GROUNDED_RESEARCH_TRANSIENT_EXHAUSTED:{last_error or 'UNKNOWN'}")


def _write_result(out: Path, result: dict[str, Any]) -> None:
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(out: Path, *, forensic_path: Path, screen_path: Path, current_path: Path | None, allow_network: bool) -> dict[str, Any]:
    current = base.maybe_read(current_path)
    effective_current = current_path
    retry_shadow: Path | None = None
    if transient_current(current):
        retry_shadow = out.parent / ".g5_trendrider_causal_retry_current.json"
        retry_value = dict(current or {})
        retry_value["input_signature_sha256"] = "TRANSIENT_PROVIDER_RETRY_CACHE_BYPASS"
        retry_shadow.parent.mkdir(parents=True, exist_ok=True)
        retry_shadow.write_text(json.dumps(retry_value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        effective_current = retry_shadow

    original = base.call_grounded_gemini
    base.call_grounded_gemini = robust_call_grounded_gemini
    try:
        result = base.run(
            out,
            forensic_path=forensic_path,
            screen_path=screen_path,
            current_path=effective_current,
            allow_network=allow_network,
        )
    finally:
        base.call_grounded_gemini = original
        if retry_shadow is not None:
            retry_shadow.unlink(missing_ok=True)

    if str(result.get("state") or "") == "HOLD_WEB_RESEARCH_PROVIDER_ERROR" and LAST_ATTEMPTS:
        provider = dict(result.get("provider") or {})
        provider.update({
            "provider": "gemini",
            "request_count": len(LAST_ATTEMPTS),
            "source_count": int(provider.get("source_count") or 0),
            "sources": list(provider.get("sources") or []),
            "web_search_queries": list(provider.get("web_search_queries") or []),
            "attempts": list(LAST_ATTEMPTS),
            "models_attempted": list(LAST_MODELS),
            "retry_policy": {
                "transient_http": sorted(TRANSIENT_HTTP),
                "attempts_per_model": ATTEMPTS_PER_MODEL,
                "max_requests": MAX_REQUESTS,
            },
            "last_error": (LAST_ATTEMPTS[-1].get("error") if LAST_ATTEMPTS else None),
        })
        result["provider"] = provider
        result["provider_call_this_run"] = True
        result["cache_hit"] = False
        result["transient_retryable"] = True
        result["next"] = "RETRY_SAME_SIGNATURE_AFTER_TRANSIENT_PROVIDER_RECOVERY"
        result["resilience_schema_version"] = SCHEMA
        _write_result(out, result)
    elif result.get("provider_call_this_run"):
        result["transient_retryable"] = False
        result["resilience_schema_version"] = SCHEMA
        _write_result(out, result)
    return result


def self_test() -> int:
    assert retryable_http(429) and retryable_http(503) and not retryable_http(400)
    assert _dedup(["a", "a", "", "b"]) == ["a", "b"]
    assert transient_current({"state": "HOLD_WEB_RESEARCH_PROVIDER_ERROR", "selected_candidate": None})
    assert not transient_current({"state": "WAIT_TRUE_FRESH_SELECTED_CHILD_T", "selected_candidate": {"mechanism_id": "x"}})
    assert MAX_REQUESTS == 4 and ATTEMPTS_PER_MODEL == 2
    base.paid_gate.validate_target_binding(base.LANE_ID, "G5", base.TARGET_GATE, provider="gemini")
    print("PASS_G5_TRENDRIDER_CAUSAL_WEB_RESEARCH_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/g5_trendrider_causal_web_research_latest.json"))
    ap.add_argument("--forensic", type=Path, default=base.FORENSIC)
    ap.add_argument("--screen", type=Path, default=base.SCREEN)
    ap.add_argument("--current", type=Path, default=base.DEFAULT_CURRENT)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--no-network", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(
        args.out,
        forensic_path=args.forensic,
        screen_path=args.screen,
        current_path=args.current,
        allow_network=not args.no_network,
    )
    print(json.dumps({
        "state": result.get("state"),
        "parent_W2_T": result.get("parent_W2_T"),
        "provider_call": result.get("provider_call_this_run"),
        "request_count": (result.get("provider") or {}).get("request_count"),
        "models_attempted": (result.get("provider") or {}).get("models_attempted"),
        "source_count": (result.get("provider") or {}).get("source_count"),
        "selected": (result.get("selected_candidate") or {}).get("mechanism_id"),
        "fresh_T": (result.get("fresh") or {}).get("child_closed_T"),
        "next": result.get("next"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
