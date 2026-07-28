#!/usr/bin/env python3
"""Read-only Cloudflare Workers AI guard for Strategy11 research artifacts.

The provider evaluates eligibility for deterministic offline replay only. It
never grants promotion, live execution or order authority. Mandatory authority
safety fields are validated locally and stripped from the semantic model input
so they cannot be misread as a reason to reject offline replay.
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
    "api_key", "apikey", "secret", "token", "password", "credential",
    "credentials", "account", "account_id", "order", "orders", "position",
    "positions", "exchange_key", "private_key",
}
AUTHORITY_ONLY_KEYS = {
    "research_only", "promotion_authority", "protected_mutations",
    "execution_allowed", "order_authority", "authority_contract",
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


def strip_authority_fields(value: Any) -> Any:
    """Remove locally-enforced authority fields from the semantic AI payload."""
    if isinstance(value, dict):
        return {
            key: strip_authority_fields(child)
            for key, child in value.items()
            if str(key).strip().lower() not in AUTHORITY_ONLY_KEYS
        }
    if isinstance(value, list):
        return [strip_authority_fields(child) for child in value]
    return value


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


def validate_review(review: dict[str, Any], *, source_lineage_complete: bool, changed_axis_count: int) -> dict[str, Any]:
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

    if source_lineage_complete and "MISSING_LINEAGE" in blockers:
        raise ValueError("HOLD_WORKERS_AI_CONTRADICTORY_MISSING_LINEAGE")
    if not source_lineage_complete and (decision != "HOLD" or "MISSING_LINEAGE" not in blockers):
        raise ValueError("HOLD_WORKERS_AI_FAIL_CLOSED_LINEAGE_REQUIRED")
    if changed_axis_count == 1 and decision == "PASS_TO_REPLAY" and review.get("single_axis") is not True:
        raise ValueError("HOLD_WORKERS_AI_PASS_WITH_SINGLE_AXIS_FALSE")
    if changed_axis_count != 1 and decision == "PASS_TO_REPLAY":
        raise ValueError("HOLD_WORKERS_AI_PASS_WITH_MULTI_AXIS_INPUT")
    if decision == "PASS_TO_REPLAY" and blockers:
        raise ValueError("HOLD_WORKERS_AI_PASS_WITH_BLOCKERS")
    if decision in {"REJECT", "HOLD"} and not blockers:
        raise ValueError("HOLD_WORKERS_AI_NONPASS_WITHOUT_BLOCKER")
    return review


def call_workers_ai(*, account_id: str, token: str, model: str, payload: dict[str, Any], timeout: int) -> tuple[dict[str, Any], int, str]:
    assert_anonymized(payload)
    semantic_payload = strip_authority_fields(payload)
    source_lineage_complete = bool(semantic_payload.get("lineage_complete"))
    changed_axes = semantic_payload.get("changed_axes", [])
    changed_axis_count = len(changed_axes) if isinstance(changed_axes, list) else 0

    system_prompt = (
        "You are an independent fail-closed guard for eligibility to run a deterministic OFFLINE research replay. "
        "This is not permission for promotion, live execution, positions, orders, or capital use. Return JSON only. "
        "Required schema: {\"decision\":\"PASS_TO_REPLAY|REJECT|HOLD\","
        "\"blocker_codes\":[\"CODE\"],\"single_axis\":true,"
        "\"lineage_complete\":true,\"overfit_risk\":\"LOW|MEDIUM|HIGH\","
        "\"reason\":\"one concise sentence\"}. "
        "Judge only: exactly one causal axis, complete lineage, no duplicate axis, evidence support, bounded generation, "
        "retention safety, and overfit risk. Mandatory authority restrictions are enforced outside this payload and must "
        "never be treated as blockers to offline replay. If supplied lineage_complete=true, do not emit MISSING_LINEAGE. "
        "If changed_axes contains exactly one axis and no other blocker exists, single_axis should be true. "
        "PASS_TO_REPLAY means only that deterministic replay may test the hypothesis; it never means the strategy passes."
    )
    input_text = canonical_json(semantic_payload)
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
            "User-Agent": "Strategy11-WorkersAI-Guard/1.1",
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
    review = validate_review(
        parse_json_response(raw_text),
        source_lineage_complete=source_lineage_complete,
        changed_axis_count=changed_axis_count,
    )
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
        "version": "STRATEGY11_WORKERS_AI_GUARD_V1_1",
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
        semantic_payload = strip_authority_fields(payload)
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
            "review_input_sha": sha256_text(canonical_json(semantic_payload)),
            "authority_fields_stripped": True,
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
    except Exception as exc:
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
