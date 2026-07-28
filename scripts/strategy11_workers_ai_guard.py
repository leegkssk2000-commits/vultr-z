#!/usr/bin/env python3
"""Read-only Cloudflare Workers AI guard for Strategy11 research artifacts.

The client is advisory only. It never grants promotion or execution authority.
Secrets are read from environment variables and are never written to logs/artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct"
ALLOWED_DECISIONS = {"PASS_TO_REPLAY", "REJECT", "HOLD"}
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "credentials",
    "account",
    "account_id",
    "order",
    "orders",
    "position",
    "positions",
    "exchange_key",
    "private_key",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_anonymized(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_KEYS or any(term in normalized for term in ("secret", "password", "credential", "private_key")):
                raise ValueError(f"HOLD_SENSITIVE_FIELD:{path}.{key}")
            assert_anonymized(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_anonymized(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        suspicious = ("bearer ", "-----begin private key-----", "sk-", "gsk_", "cfut_")
        if any(marker in lowered for marker in suspicious):
            raise ValueError(f"HOLD_SENSITIVE_VALUE:{path}")


def extract_text(api_payload: dict[str, Any]) -> str:
    result = api_payload.get("result")
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("response", "output_text", "text", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
    raise ValueError("HOLD_WORKERS_AI_RESPONSE_TEXT_MISSING")


def parse_json_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("HOLD_WORKERS_AI_JSON_MISSING")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("HOLD_WORKERS_AI_JSON_NOT_OBJECT")
    return parsed


def validate_review(review: dict[str, Any]) -> dict[str, Any]:
    decision = review.get("decision")
    blockers = review.get("blocker_codes")
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("HOLD_WORKERS_AI_DECISION_INVALID")
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        raise ValueError("HOLD_WORKERS_AI_BLOCKERS_INVALID")
    if not isinstance(review.get("single_axis"), bool):
        raise ValueError("HOLD_WORKERS_AI_SINGLE_AXIS_INVALID")
    if not isinstance(review.get("lineage_complete"), bool):
        raise ValueError("HOLD_WORKERS_AI_LINEAGE_INVALID")
    if review.get("overfit_risk") not in {"LOW", "MEDIUM", "HIGH"}:
        raise ValueError("HOLD_WORKERS_AI_OVERFIT_INVALID")
    if not isinstance(review.get("reason"), str) or not review["reason"].strip():
        raise ValueError("HOLD_WORKERS_AI_REASON_INVALID")
    return review


def call_workers_ai(*, account_id: str, token: str, model: str, payload: dict[str, Any], timeout: int) -> tuple[dict[str, Any], int, str]:
    assert_anonymized(payload)
    system_prompt = (
        "You are an independent fail-closed research artifact guard. Return JSON only. "
        "Required schema: {\"decision\":\"PASS_TO_REPLAY|REJECT|HOLD\","
        "\"blocker_codes\":[\"CODE\"],\"single_axis\":true,"
        "\"lineage_complete\":true,\"overfit_risk\":\"LOW|MEDIUM|HIGH\","
        "\"reason\":\"one concise sentence\"}. "
        "Mandatory rules: if lineage_complete in the supplied artifact is false, decision MUST be HOLD "
        "and blocker_codes MUST contain MISSING_LINEAGE. Reject or hold multi-axis, duplicate-axis, "
        "unsupported, trade-deletion-driven, low-sample, or authority-unsafe proposals. "
        "Never grant promotion or execution authority."
    )
    input_text = canonical_json(payload)
    request_body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        "temperature": 0,
        "max_tokens": 400,
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    request = urllib.request.Request(
        url,
        data=canonical_json(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Strategy11-WorkersAI-Guard/1.0",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_bytes = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"HOLD_WORKERS_AI_HTTP_{exc.code}:{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HOLD_WORKERS_AI_NETWORK:{exc.reason}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)
    api_payload = json.loads(response_bytes.decode("utf-8"))
    if api_payload.get("success") is not True:
        raise RuntimeError("HOLD_WORKERS_AI_API_FAILURE:" + canonical_json(api_payload.get("errors", []))[:1200])
    raw_text = extract_text(api_payload)
    review = validate_review(parse_json_response(raw_text))
    prompt_sha = sha256_text(system_prompt)
    return review, latency_ms, prompt_sha


def default_fixture() -> dict[str, Any]:
    return {
        "strategy_id": "fixture_strategy",
        "candidate_axis": "VOLATILITY_GATE",
        "changed_axes": ["VOLATILITY_GATE"],
        "lineage_complete": False,
        "control": {"trades": 4, "net_pct": 0.3, "pf": 1.05, "dd_pct": 0.9},
        "candidate": {"trades": 3, "net_pct": 0.5, "pf": 1.2, "dd_pct": 0.8},
        "retention": 0.75,
        "promotion_authority": False,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.environ.get("WORKERS_AI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_WORKERS_AI_TOKEN", "").strip()
    base_artifact: dict[str, Any] = {
        "version": "STRATEGY11_WORKERS_AI_GUARD_V1",
        "provider": "cloudflare_workers_ai",
        "model": args.model,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "secret_present": bool(token),
        "account_id_present": bool(account_id),
    }
    try:
        if not account_id:
            raise RuntimeError("HOLD_CLOUDFLARE_ACCOUNT_ID_MISSING")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", account_id):
            raise RuntimeError("HOLD_CLOUDFLARE_ACCOUNT_ID_INVALID")
        if not token:
            raise RuntimeError("HOLD_CLOUDFLARE_WORKERS_AI_TOKEN_MISSING")
        payload = json.loads(args.input.read_text(encoding="utf-8")) if args.input else default_fixture()
        if not isinstance(payload, dict):
            raise RuntimeError("HOLD_WORKERS_AI_INPUT_NOT_OBJECT")
        assert_anonymized(payload)
        review, latency_ms, prompt_sha = call_workers_ai(
            account_id=account_id,
            token=token,
            model=args.model,
            payload=payload,
            timeout=args.timeout,
        )
        artifact = {
            **base_artifact,
            "status": "PASS_WORKERS_AI_CONNECTION",
            "blocker_code": None,
            "input_sha": sha256_text(canonical_json(payload)),
            "prompt_sha": prompt_sha,
            "response_sha": sha256_text(canonical_json(review)),
            "account_id_sha": sha256_text(account_id),
            "latency_ms": latency_ms,
            "review": review,
        }
        write_artifact(args.output, artifact)
        print("PASS_WORKERS_AI_CONNECTION")
        print(f"workers_ai_model={args.model}")
        print(f"workers_ai_latency_ms={latency_ms}")
        return 0
    except Exception as exc:  # fail closed and still emit diagnostic artifact
        blocker = str(exc)
        artifact = {
            **base_artifact,
            "status": "HOLD_WORKERS_AI_CONNECTION",
            "blocker_code": blocker[:1500],
        }
        write_artifact(args.output, artifact)
        print(blocker, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
