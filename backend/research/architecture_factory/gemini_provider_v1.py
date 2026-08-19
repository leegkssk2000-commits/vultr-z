from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

DEFAULT_GEMINI_MODEL = "gemini-3.1-pro-preview"
GEMINI_FALLBACK_MODEL = "gemini-3.1-pro-preview"
DEFAULT_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
PASS_DECISIONS = {"PASS", "PASS_TO_REPLAY", "PASS_TO_PREREGISTER"}


def _canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("GEMINI_JSON_MISSING")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("GEMINI_OBJECT_REQUIRED")
    return value


def _extract_text(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content")
        if not isinstance(content, Mapping):
            continue
        for part in content.get("parts") or []:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("GEMINI_EMPTY_RESPONSE")
    return text


def _is_obsolete_model_404(detail: str) -> bool:
    text = detail.lower()
    return "no longer available" in text or "model" in text and "not found" in text


def _call(prompt: str, *, system_instruction: str, max_output_tokens: int, temperature: float) -> tuple[str, str, dict[str, str]]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY_MISSING")
    requested_model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    api_base = os.environ.get("GEMINI_API_BASE", "").strip().rstrip("/") or DEFAULT_GEMINI_API_BASE
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_output_tokens),
            "responseMimeType": "application/json",
        },
    }

    def request_model(model: str) -> Mapping[str, Any]:
        url = f"{api_base}/models/{urllib.parse.quote(model, safe='-._')}:generateContent?key={urllib.parse.quote(key, safe='')}"
        req = urllib.request.Request(
            url,
            data=_canonical(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))

    actual_model = requested_model
    fallback_used = False
    try:
        payload = request_model(requested_model)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        if exc.code == 404 and requested_model != GEMINI_FALLBACK_MODEL and _is_obsolete_model_404(detail):
            actual_model = GEMINI_FALLBACK_MODEL
            fallback_used = True
            try:
                payload = request_model(actual_model)
            except urllib.error.HTTPError as fallback_exc:
                fallback_detail = fallback_exc.read().decode(errors="replace")[:800]
                raise RuntimeError(f"GEMINI_HTTP_{fallback_exc.code}:{fallback_detail}") from fallback_exc
        else:
            raise RuntimeError(f"GEMINI_HTTP_{exc.code}:{detail}") from exc
    text = _extract_text(payload)
    lineage = {
        "prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "requested_model": requested_model,
        "fallback_used": str(fallback_used).lower(),
    }
    return actual_model, text, lineage


def call_gemini_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    model, text, lineage = _call(
        prompt,
        system_instruction=(
            "Return only the requested strategy-architecture JSON. "
            "Do not browse, do not infer sealed holdout outcomes, and do not tune parameters from outcomes."
        ),
        max_output_tokens=5000,
        temperature=0.15,
    )
    return model, _extract_json(text), lineage


def call_gemini_critic(candidate_payload: Mapping[str, Any]) -> dict[str, Any]:
    prompt = (
        "Adversarially review this research-only crypto strategy candidate. "
        "Judge causal mechanism, source sufficiency, falsifiability, cost geometry, leakage risk, and whether it is a one-axis repair or genuinely distinct architecture. "
        "Do not claim profitability. Return JSON only with keys decision and reason. "
        "decision must be one of PASS, PASS_TO_REPLAY, HOLD, REJECT.\nCANDIDATE="
        + _canonical(candidate_payload)
    )
    model, text, lineage = _call(
        prompt,
        system_instruction="You are an adversarial strategy research critic. JSON only.",
        max_output_tokens=1200,
        temperature=0.0,
    )
    value = _extract_json(text)
    decision = str(value.get("decision") or "").strip()
    if decision not in {"PASS", "PASS_TO_REPLAY", "HOLD", "REJECT"}:
        raise RuntimeError(f"GEMINI_CRITIC_DECISION_INVALID:{decision}")
    return {
        "successful": True,
        "model": model,
        "decision": decision,
        "reason": str(value.get("reason") or "")[:1600],
        "input_sha": hashlib.sha256(_canonical(candidate_payload).encode("utf-8")).hexdigest(),
        **lineage,
    }


def economic_rebuild_enabled(done_count: int) -> bool:
    explicit = os.environ.get("GEMINI_ECONOMIC_REBUILD_ENABLED", "").strip().lower()
    if explicit in {"0", "false", "no", "off"}:
        return False
    if done_count < 25:
        return False
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def self_test() -> int:
    parsed = _extract_json('```json\n{"decision":"PASS","reason":"ok"}\n```')
    assert parsed["decision"] == "PASS"
    assert economic_rebuild_enabled(24) is False
    assert _is_obsolete_model_404('{"error":{"message":"This model models/gemini-2.5-pro is no longer available to new users."}}') is True
    assert _is_obsolete_model_404('{"error":{"message":"quota exceeded"}}') is False
    print("PASS_GEMINI_PROVIDER_V1_SELF_TEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
