#!/usr/bin/env python3
"""Fail-closed, read-only Groq red-team client for Strategy11 research."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from groq import Groq

ALLOWED_DECISIONS = {"PASS_TO_REPLAY", "REJECT", "HOLD"}
AUTHORITY_ONLY_KEYS = {
    "research_only", "promotion_authority", "protected_mutations",
    "execution_allowed", "execution_authority", "order_authority",
    "runtime_bound", "authority_contract",
}
SENSITIVE_KEY_TOKENS = {
    "account", "credential", "credentials", "order", "orders", "password",
    "position", "positions", "secret", "token", "wallet",
}
SENSITIVE_KEY_PHRASES = {
    "account_id", "account_number", "api_key", "apikey", "access_token",
    "refresh_token", "client_secret", "exchange_key", "order_id",
    "client_order_id", "position_id", "private_key", "wallet_address",
}
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)(?:^|\s)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)-----begin private key-----"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])gsk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])cfut_[A-Za-z0-9_-]{8,}"),
)
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_JSON_ATTEMPTS = 2


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_key(raw_key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(raw_key).strip().lower()).strip("_")


def sensitive_key(raw_key: Any) -> bool:
    key = normalized_key(raw_key)
    if key in SENSITIVE_KEY_PHRASES:
        return True
    tokens = set(re.findall(r"[a-z0-9]+", key))
    if tokens & SENSITIVE_KEY_TOKENS:
        return True
    if {"api", "key"}.issubset(tokens) or {"private", "key"}.issubset(tokens):
        return True
    if {"exchange", "key"}.issubset(tokens):
        return True
    return False


def validate_authority_field(key: str, value: Any, path: str) -> None:
    if key == "order_authority" and value != "BLOCKED":
        raise ValueError(f"FORBIDDEN_AUTHORITY_VALUE:{path}.{key}")
    if key == "execution_authority" and value not in {"NONE", None}:
        raise ValueError(f"FORBIDDEN_AUTHORITY_VALUE:{path}.{key}")
    if key in {"execution_allowed", "runtime_bound", "promotion_authority"} and value is not False:
        raise ValueError(f"FORBIDDEN_AUTHORITY_VALUE:{path}.{key}")
    if key == "research_only" and value is not True:
        raise ValueError(f"FORBIDDEN_AUTHORITY_VALUE:{path}.{key}")
    if key == "protected_mutations" and value != 0:
        raise ValueError(f"FORBIDDEN_AUTHORITY_VALUE:{path}.{key}")


def assert_anonymized(value: Any, path: str = "$") -> None:
    """Reject private/order-bearing fields without substring false positives."""
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = normalized_key(raw_key)
            if key in AUTHORITY_ONLY_KEYS:
                validate_authority_field(key, child, path)
            elif sensitive_key(raw_key):
                raise ValueError(f"FORBIDDEN_FIELD:{path}.{raw_key}")
            assert_anonymized(child, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_anonymized(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
            raise ValueError(f"FORBIDDEN_VALUE:{path}")


def strip_authority_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_authority_fields(child)
            for key, child in value.items()
            if normalized_key(key) not in AUTHORITY_ONLY_KEYS
        }
    if isinstance(value, list):
        return [strip_authority_fields(child) for child in value]
    return value


def load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("INPUT_MUST_BE_JSON_OBJECT")
        return payload
    return {
        "strategy_id": "fixture_strategy",
        "changed_axes": ["TREND_REGIME_GATE"],
        "lineage_complete": True,
        "hypothesis": {
            "axis": "TREND_REGIME_GATE", "generation": 1,
            "change": "Apply one pre-entry trend-regime eligibility gate.",
        },
        "evidence": {
            "trades": 24, "retention_pct": 87.5, "positive_windows": 2,
            "ordered_marginal_delta_net": {"TEAM": 0.4},
            "description": "risk-adjusted task-level desk-neutral research",
        },
        "lineage": {
            "source_sha": "fixture-source-sha", "data_sha": "fixture-data-sha",
            "window_sha": "fixture-window-sha", "candidate_sha": "fixture-candidate-sha",
        },
        "research_only": True, "promotion_authority": False,
        "protected_mutations": 0, "execution_allowed": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED",
        "runtime_bound": False,
    }


def response_contract() -> dict[str, Any]:
    return {
        "decision": "PASS_TO_REPLAY|REJECT|HOLD",
        "blocker_codes": ["string"], "single_axis": True,
        "evidence_supported": True, "overfit_risk": "LOW|MEDIUM|HIGH",
        "reason": "one concise sentence",
    }


def build_prompt(payload: dict[str, Any], *, retry: bool = False) -> str:
    prefix = (
        "Your previous answer violated the JSON contract. Return exactly one valid JSON object, no markdown or prose.\n"
        if retry else ""
    )
    return (
        prefix
        + "You are an independent red-team reviewer for a research-only trading hypothesis. "
        "You have no promotion or execution authority. Reject or hold multi-axis changes, duplicate axes, unsupported evidence, overfit proposals, trade-deletion improvements, or lineage/control mismatches. "
        "Return one JSON object matching this contract exactly:\n"
        f"{canonical_json(response_contract())}\n"
        "Anonymized research payload:\n"
        f"{canonical_json(payload)}"
    )


def strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def iter_balanced_json_objects(raw: str):
    text = strip_code_fence(raw)
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:index + 1]
                start = None


def parse_review_json(raw: str) -> dict[str, Any]:
    text = strip_code_fence(raw)
    candidates = [text, *iter_balanced_json_objects(text)]
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("RESPONSE_JSON_DECODE_FAILED")


def validate_review(review: Any) -> dict[str, Any]:
    required = {"decision", "blocker_codes", "single_axis", "evidence_supported", "overfit_risk", "reason"}
    if not isinstance(review, dict):
        raise ValueError("RESPONSE_NOT_JSON_OBJECT")
    if set(review) != required:
        raise ValueError("RESPONSE_JSON_SHAPE_MISMATCH")
    if review["decision"] not in ALLOWED_DECISIONS:
        raise ValueError("RESPONSE_DECISION_INVALID")
    if not isinstance(review["blocker_codes"], list) or not all(isinstance(item, str) for item in review["blocker_codes"]):
        raise ValueError("RESPONSE_BLOCKERS_INVALID")
    if not isinstance(review["single_axis"], bool):
        raise ValueError("RESPONSE_SINGLE_AXIS_INVALID")
    if not isinstance(review["evidence_supported"], bool):
        raise ValueError("RESPONSE_EVIDENCE_INVALID")
    if review["overfit_risk"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise ValueError("RESPONSE_OVERFIT_INVALID")
    if not isinstance(review["reason"], str) or not review["reason"].strip():
        raise ValueError("RESPONSE_REASON_INVALID")
    return review


def select_model(client: Groq, requested: str) -> tuple[str, str]:
    try:
        response = client.models.list()
        model_ids = sorted(str(item.id) for item in getattr(response, "data", []) if getattr(item, "id", None))
    except Exception:
        return requested, "requested_without_model_listing"
    if requested in model_ids:
        return requested, "requested_exact"
    suffix = requested.rsplit("/", 1)[-1].lower()
    matches = [model_id for model_id in model_ids if model_id.lower().endswith(suffix)]
    if matches:
        return matches[0], "requested_suffix_match"
    preferred = [model_id for model_id in model_ids if "gpt-oss" in model_id.lower() and "120b" in model_id.lower()]
    if preferred:
        return preferred[0], "preferred_gpt_oss_120b"
    raise RuntimeError("HOLD_MODEL_UNAVAILABLE")


def package_version() -> str:
    try:
        return version("groq")
    except PackageNotFoundError:
        return "unknown"


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_review(client: Groq, model: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    raw_responses: list[str] = []
    prompt_hashes: list[str] = []
    last_error: Exception | None = None
    for attempt in range(MAX_JSON_ATTEMPTS):
        prompt = build_prompt(payload, retry=attempt > 0)
        prompt_hashes.append(sha256_text(prompt))
        completion = client.chat.completions.create(
            model=model, temperature=0, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = completion.choices[0].message.content or ""
        raw_responses.append(raw)
        try:
            return validate_review(parse_review_json(raw)), raw_responses, prompt_hashes
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"RESPONSE_JSON_RECOVERY_EXHAUSTED:{last_error}")


def self_test() -> int:
    allowed = load_payload(None)
    assert_anonymized(allowed)
    stripped = strip_authority_fields(allowed)
    assert "order_authority" not in stripped
    assert stripped["evidence"]["ordered_marginal_delta_net"]["TEAM"] == 0.4
    for safe in ("risk-adjusted", "task-level", "desk-neutral", "ordered execution evidence"):
        assert_anonymized({"description": safe})
    for bad in (
        {"orders": [{"id": 1}]}, {"client_order_id": "x"},
        {"account_number": "x"}, {"wallet_address": "x"},
        {"access_token": "x"}, {"position_id": "x"},
        {"api_key": "x"}, {"order_authority": "ENABLED"},
        {"execution_allowed": True}, {"payload": "Bearer abcdefgh"},
        {"payload": "sk-abcdefgh"},
    ):
        try:
            assert_anonymized(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"SENSITIVE_PAYLOAD_ACCEPTED:{bad}")
    print("PASS_GROQ_ANONYMIZATION_GUARD_V2")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to anonymized JSON payload")
    parser.add_argument("--output", default="artifacts/strategy11_groq_redteam_result.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    output_path = Path(args.output)
    started = time.monotonic()
    base_artifact: dict[str, Any] = {
        "schema_version": "strategy11.groq_redteam.v2.1",
        "provider": "groq", "groq_sdk_version": package_version(),
        "GROQ_USED": False, "secret_present": bool(os.environ.get("GROQ_API_KEY")),
        "promotion_authority": False, "protected_mutations": 0,
        "execution_allowed": False, "order_authority": "BLOCKED",
        "research_only": True,
    }
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("HOLD_GROQ_API_KEY_MISSING")
        raw_payload = load_payload(args.input)
        assert_anonymized(raw_payload)
        semantic_payload = strip_authority_fields(raw_payload)
        assert_anonymized(semantic_payload)
        input_text = canonical_json(raw_payload)
        semantic_text = canonical_json(semantic_payload)
        client = Groq(api_key=api_key)
        requested_model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
        model, model_resolution = select_model(client, requested_model)
        review, raw_responses, prompt_hashes = request_review(client, model, semantic_payload)
        artifact = {
            **base_artifact,
            "status": "PASS_GROQ_REDTEAM_CONNECTION", "GROQ_USED": True,
            "actual_model": model, "model_resolution": model_resolution,
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "input_sha": sha256_text(input_text), "semantic_input_sha": sha256_text(semantic_text),
            "authority_fields_stripped": True, "prompt_sha": prompt_hashes[-1],
            "prompt_attempt_shas": prompt_hashes, "response_sha": sha256_text(raw_responses[-1]),
            "response_attempt_shas": [sha256_text(raw) for raw in raw_responses],
            "json_attempt_count": len(raw_responses), "json_recovery_used": len(raw_responses) > 1,
            "latency_ms": round((time.monotonic() - started) * 1000), "review": review,
        }
        write_artifact(output_path, artifact)
        print(f"PASS_GROQ_REDTEAM_CONNECTION model={model} decision={review['decision']} attempts={len(raw_responses)} artifact={output_path}")
        return 0
    except Exception as exc:
        message = str(exc)
        blocker = message if message.startswith(("HOLD_", "FORBIDDEN_", "INPUT_", "RESPONSE_")) else type(exc).__name__
        artifact = {
            **base_artifact, "status": "HOLD_GROQ_REDTEAM_CONNECTION",
            "blocker_code": blocker, "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "max_json_attempts": MAX_JSON_ATTEMPTS,
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        write_artifact(output_path, artifact)
        print(f"HOLD_GROQ_REDTEAM_CONNECTION blocker={blocker} artifact={output_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
