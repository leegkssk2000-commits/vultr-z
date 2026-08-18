from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping, Sequence

SCHEMA = "zel.production_ai_openai_critic.v1"
_ALLOWED_DECISIONS = {"PASS", "HOLD", "REJECT"}
_BLOCKER_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

_CRITIC_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "string", "const": SCHEMA},
        "decision": {"type": "string", "enum": ["PASS", "HOLD", "REJECT"]},
        "causal_critique": {"type": "string", "minLength": 1, "maxLength": 1600},
        "falsification_test": {"type": "string", "minLength": 1, "maxLength": 1600},
        "blocker_codes": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "minLength": 3, "maxLength": 64},
        },
    },
    "required": [
        "schema_version",
        "decision",
        "causal_critique",
        "falsification_test",
        "blocker_codes",
    ],
}


def validate_critic_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {
            "enabled": False,
            "required": False,
            "model_env": "OPENAI_MODEL",
            "default_model": "gpt-5-mini",
            "timeout_sec": 60,
            "max_output_tokens": 1200,
        }
    cfg = dict(raw)
    if cfg.get("enabled") not in {True, False} or cfg.get("required") not in {True, False}:
        raise RuntimeError("OPENAI_CRITIC_ENABLEMENT_INVALID")
    if cfg.get("required") is True and cfg.get("enabled") is not True:
        raise RuntimeError("OPENAI_CRITIC_REQUIRED_BUT_DISABLED")
    model_env = str(cfg.get("model_env") or "OPENAI_MODEL").strip()
    default_model = str(cfg.get("default_model") or "gpt-5-mini").strip()
    if not model_env or not default_model:
        raise RuntimeError("OPENAI_CRITIC_MODEL_CONFIG_INVALID")
    timeout_sec = int(cfg.get("timeout_sec") or 60)
    max_output_tokens = int(cfg.get("max_output_tokens") or 1200)
    if timeout_sec < 10 or timeout_sec > 120:
        raise RuntimeError("OPENAI_CRITIC_TIMEOUT_INVALID")
    if max_output_tokens < 256 or max_output_tokens > 4096:
        raise RuntimeError("OPENAI_CRITIC_TOKEN_BUDGET_INVALID")
    allowed = cfg.get("allowed_decisions", ["PASS", "HOLD", "REJECT"])
    if list(allowed) != ["PASS", "HOLD", "REJECT"]:
        raise RuntimeError("OPENAI_CRITIC_DECISION_POLICY_INVALID")
    cfg.update(
        {
            "model_env": model_env,
            "default_model": default_model,
            "timeout_sec": timeout_sec,
            "max_output_tokens": max_output_tokens,
        }
    )
    return cfg


def _safe_proposer_view(proposer_response: Mapping[str, Any]) -> dict[str, Any]:
    status = str(proposer_response.get("status") or "")
    raw = proposer_response.get("proposals")
    proposals: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw[:2]:
            if not isinstance(item, Mapping):
                continue
            proposals.append(
                {
                    "proposal_type": str(item.get("proposal_type") or ""),
                    "family_id": str(item.get("family_id") or ""),
                    "economic_mechanism": str(item.get("economic_mechanism") or "")[:1200],
                    "required_sources": [str(v) for v in (item.get("required_sources") or [])][:6],
                    "causal_reason": str(item.get("causal_reason") or "")[:1200],
                    "falsification_test": str(item.get("falsification_test") or "")[:1200],
                    "expected_horizon": str(item.get("expected_horizon") or "")[:1200],
                }
            )
    return {"status": status, "proposals": proposals}


def critic_prompt(proposer_response: Mapping[str, Any]) -> str:
    safe = _safe_proposer_view(proposer_response)
    return (
        "You are an independent falsification critic for proposal-only quantitative research. "
        "You do not select winners and you have no authority over thresholds, parameters, TP/SL, leverage, sizing, code, promotion, execution, orders, or LIVE trading. "
        "Review only the causal coherence and falsifiability of the supplied economic hypotheses. "
        "PASS only when no material causal or falsification defect is found. HOLD when evidence or specification is insufficient. "
        "REJECT when the mechanism is internally contradictory, circular, non-falsifiable, or materially duplicates its own stated logic. "
        "Do not invent market facts, performance, thresholds, or source availability. Give one bounded falsification test.\n\n"
        f"PROPOSER_RESPONSE={json.dumps(safe, ensure_ascii=False, sort_keys=True)}"
    )


def _extract_output_text(payload: Mapping[str, Any]) -> str:
    status = str(payload.get("status") or "completed")
    if status not in {"completed", "incomplete"}:
        raise RuntimeError(f"OPENAI_CRITIC_RESPONSE_STATUS:{status[:80]}")
    texts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, Mapping):
            continue
        for part in item.get("content", []):
            if isinstance(part, Mapping) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if text:
        return text
    incomplete = payload.get("incomplete_details")
    if status == "incomplete" and isinstance(incomplete, Mapping):
        reason = str(incomplete.get("reason") or "UNKNOWN")[:80]
        raise RuntimeError(f"OPENAI_CRITIC_INCOMPLETE:{reason}")
    raise RuntimeError("OPENAI_CRITIC_EMPTY_RESPONSE")


def validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "decision", "causal_critique", "falsification_test", "blocker_codes"}
    if set(receipt) != required:
        raise RuntimeError("OPENAI_CRITIC_SCHEMA_MISMATCH")
    if receipt.get("schema_version") != SCHEMA:
        raise RuntimeError("OPENAI_CRITIC_SCHEMA_VERSION_INVALID")
    decision = str(receipt.get("decision") or "")
    if decision not in _ALLOWED_DECISIONS:
        raise RuntimeError("OPENAI_CRITIC_DECISION_INVALID")
    for key in ("causal_critique", "falsification_test"):
        text = str(receipt.get(key) or "").strip()
        if not text or len(text) > 1600:
            raise RuntimeError(f"OPENAI_CRITIC_TEXT_INVALID:{key}")
    blockers = receipt.get("blocker_codes")
    if not isinstance(blockers, list) or len(blockers) > 8:
        raise RuntimeError("OPENAI_CRITIC_BLOCKERS_INVALID")
    normalized = [str(v).strip().upper() for v in blockers]
    if len(normalized) != len(set(normalized)) or any(not _BLOCKER_CODE.fullmatch(v) for v in normalized):
        raise RuntimeError("OPENAI_CRITIC_BLOCKER_CODE_INVALID")
    if decision == "PASS" and normalized:
        raise RuntimeError("OPENAI_CRITIC_PASS_WITH_BLOCKERS")
    return {
        "schema_version": SCHEMA,
        "decision": decision,
        "causal_critique": str(receipt["causal_critique"]).strip(),
        "falsification_test": str(receipt["falsification_test"]).strip(),
        "blocker_codes": normalized,
    }


def fail_closed_receipt(code: str, detail: str = "") -> dict[str, Any]:
    normalized = re.sub(r"[^A-Z0-9_]+", "_", str(code).upper()).strip("_")[:64]
    if not _BLOCKER_CODE.fullmatch(normalized):
        normalized = "OPENAI_CRITIC_FAILURE"
    suffix = str(detail).strip().replace("\n", " ")[:300]
    return {
        "schema_version": SCHEMA,
        "decision": "HOLD",
        "causal_critique": f"OpenAI critic unavailable or invalid: {normalized}" + (f" ({suffix})" if suffix else ""),
        "falsification_test": "Retry the same bounded critic review only after authentication, transport, and schema validity are restored.",
        "blocker_codes": [normalized],
    }


def _responses_body(model: str, proposer_response: Mapping[str, Any], max_output_tokens: int) -> bytes:
    payload: dict[str, Any] = {
        "model": str(model),
        "store": False,
        "instructions": "Return only the required structured critic receipt. Do not use tools or external web data.",
        "input": critic_prompt(proposer_response),
        "max_output_tokens": int(max_output_tokens),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "zel_production_ai_openai_critic_v1",
                "strict": True,
                "schema": _CRITIC_JSON_SCHEMA,
            }
        },
    }
    # GPT-5 reasoning tokens count against max_output_tokens. The critic needs only a
    # bounded structured falsification review, so minimal reasoning preserves visible JSON.
    if str(model).lower().startswith("gpt-5"):
        payload["reasoning"] = {"effort": "minimal"}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _post_responses(api_key: str, body: bytes, timeout_sec: int) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": request_id,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(timeout_sec)) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OPENAI_CRITIC_HTTP_{exc.code}:{detail}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("OPENAI_CRITIC_RESPONSE_NOT_OBJECT")
    return dict(payload)


def call_openai_critic(
    api_key: str,
    model: str,
    proposer_response: Mapping[str, Any],
    *,
    timeout_sec: int = 60,
    max_output_tokens: int = 1200,
) -> tuple[str, dict[str, Any]]:
    if not str(api_key).strip():
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    if not str(model).strip():
        raise RuntimeError("OPENAI_MODEL_MISSING")

    budgets = [int(max_output_tokens)]
    retry_budget = min(4096, max(2400, int(max_output_tokens) * 2))
    if retry_budget > budgets[0]:
        budgets.append(retry_budget)

    last_exc: Exception | None = None
    for idx, budget in enumerate(budgets):
        payload = _post_responses(
            str(api_key),
            _responses_body(str(model), proposer_response, budget),
            int(timeout_sec),
        )
        try:
            receipt_raw = json.loads(_extract_output_text(payload))
        except RuntimeError as exc:
            last_exc = exc
            incomplete = payload.get("incomplete_details")
            reason = str(incomplete.get("reason") or "") if isinstance(incomplete, Mapping) else ""
            if idx == 0 and reason == "max_output_tokens" and len(budgets) > 1:
                continue
            raise
        if not isinstance(receipt_raw, Mapping):
            raise RuntimeError("OPENAI_CRITIC_RESPONSE_NOT_OBJECT")
        return str(model), validate_receipt(receipt_raw)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OPENAI_CRITIC_EMPTY_RESPONSE")


def review_or_hold(
    api_key: str,
    model: str,
    proposer_response: Mapping[str, Any],
    *,
    timeout_sec: int = 60,
    max_output_tokens: int = 1200,
) -> tuple[str, dict[str, Any]]:
    try:
        return call_openai_critic(
            api_key,
            model,
            proposer_response,
            timeout_sec=timeout_sec,
            max_output_tokens=max_output_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        return str(model), fail_closed_receipt(type(exc).__name__, str(exc))
