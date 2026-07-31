#!/usr/bin/env python3
"""Read-only GitHub Models reviewer with explicit provider-retirement HOLD."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o"
ALLOWED_DECISIONS = {"PASS_TO_NEXT_GATE", "REJECT", "HOLD"}
FORBIDDEN_KEYS = {"account", "account_id", "api_key", "credential", "exchange_key", "order", "orders", "order_id", "password", "position", "positions", "position_id", "private_key", "secret", "token", "wallet"}


class ProviderRetired(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_anonymized(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if key in FORBIDDEN_KEYS or any(term in key for term in ("secret", "password", "credential", "private_key")):
                raise ValueError(f"FORBIDDEN_FIELD:{path}.{raw_key}")
            assert_anonymized(child, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_anonymized(child, f"{path}[{index}]")


def load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("INPUT_MUST_BE_JSON_OBJECT")
        return payload
    return {
        "stage": "CORE_CLASSIFICATION_REVIEW",
        "strategy_id": "fixture_strategy",
        "candidate": {"axis": "TREND_REGIME_GATE", "generation": 1, "research_only": True},
        "metrics": {"trades": 8, "win_rate_pct": 62.5, "net_r": 1.8, "profit_factor": 1.42, "max_drawdown_r": -1.1},
        "oos_windows": {"W1": "PASS", "W2": "MISSING", "W3": "MISSING"},
        "lineage": {"source_sha": "fixture-source-sha", "data_sha": "fixture-data-sha", "window_sha": "fixture-window-sha", "candidate_sha": "fixture-candidate-sha"},
    }


def build_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    schema = {"decision": "PASS_TO_NEXT_GATE|REJECT|HOLD", "blocker_codes": ["string"], "evidence_complete": False, "oos_supported": False, "overfit_risk": "LOW|MEDIUM|HIGH", "reason": "one concise sentence"}
    criteria = {"LOW_SAMPLE_SIZE": "Use HOLD when trades is below 30.", "MISSING_OOS_WINDOWS": "Use HOLD when W2 or W3 is missing.", "MISSING_LINEAGE": "Use HOLD when lineage fields are incomplete.", "INSUFFICIENT_MULTIMETRIC_EVIDENCE": "Do not pass from one score alone."}
    return [
        {"role": "system", "content": "Evaluate research evidence conservatively and output JSON only."},
        {"role": "user", "content": f"Classify this anonymized research record. Schema: {canonical_json(schema)} Criteria: {canonical_json(criteria)} Record: {canonical_json(payload)}"},
    ]


def strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def validate_review(review: Any) -> dict[str, Any]:
    required = {"decision", "blocker_codes", "evidence_complete", "oos_supported", "overfit_risk", "reason"}
    if not isinstance(review, dict):
        raise ValueError("RESPONSE_NOT_JSON_OBJECT")
    if set(review) != required:
        raise ValueError("RESPONSE_JSON_SHAPE_MISMATCH")
    if review["decision"] not in ALLOWED_DECISIONS:
        raise ValueError("RESPONSE_DECISION_INVALID")
    if not isinstance(review["blocker_codes"], list) or not all(isinstance(item, str) for item in review["blocker_codes"]):
        raise ValueError("RESPONSE_BLOCKERS_INVALID")
    if not isinstance(review["evidence_complete"], bool) or not isinstance(review["oos_supported"], bool):
        raise ValueError("RESPONSE_BOOLEAN_INVALID")
    if review["overfit_risk"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise ValueError("RESPONSE_OVERFIT_INVALID")
    if not isinstance(review["reason"], str) or not review["reason"].strip():
        raise ValueError("RESPONSE_REASON_INVALID")
    return review


def call_model(token: str, model: str, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
    body = {"model": model, "temperature": 0, "max_tokens": 512, "response_format": {"type": "json_object"}, "messages": messages}
    request = urllib.request.Request(ENDPOINT, data=canonical_json(body).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw_http = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 410:
            raise ProviderRetired(f"HOLD_GITHUB_MODELS_HTTP_410:{body_text}") from exc
        raise RuntimeError(f"HOLD_GITHUB_MODELS_HTTP_{exc.code}:{body_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("HOLD_GITHUB_MODELS_NETWORK") from exc
    envelope = json.loads(raw_http)
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("RESPONSE_CHOICES_MISSING")
    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("RESPONSE_CONTENT_MISSING")
    return content, envelope


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def retired_review() -> dict[str, Any]:
    return {"decision": "HOLD", "blocker_codes": ["GITHUB_MODELS_PROVIDER_RETIRED_HTTP_410"], "evidence_complete": False, "oos_supported": False, "overfit_risk": "HIGH", "reason": "GitHub Models endpoint returned HTTP 410; deterministic gates remain authoritative."}


def self_test() -> int:
    review = validate_review(retired_review())
    assert review["decision"] == "HOLD"
    assert_anonymized(load_payload(None))
    print("PASS_GITHUB_MODELS_RETIREMENT_HOLD_FIXTURE")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output", default="artifacts/strategy11_github_models_review.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    output_path = Path(args.output)
    started = time.monotonic()
    token = os.environ.get("GITHUB_TOKEN", "")
    base = {"schema_version": "strategy11.github_models_review.v1.1", "provider": "github_models", "GITHUB_MODELS_USED": False, "token_present": bool(token), "token_sha_recorded": False, "promotion_authority": False, "protected_mutations": 0, "execution_allowed": False, "order_authority": "BLOCKED", "research_only": True}
    try:
        if not token:
            raise RuntimeError("HOLD_GITHUB_TOKEN_MISSING")
        payload = load_payload(args.input)
        assert_anonymized(payload)
        payload_text = canonical_json(payload)
        messages = build_messages(payload)
        prompt_text = canonical_json(messages)
        requested_model = os.environ.get("GITHUB_MODELS_MODEL", DEFAULT_MODEL)
        try:
            raw_response, envelope = call_model(token, requested_model, messages)
            review = validate_review(json.loads(strip_code_fence(raw_response)))
            artifact = {**base, "status": "PASS_GITHUB_MODELS_CONNECTION", "GITHUB_MODELS_USED": True, "actual_model": envelope.get("model", requested_model), "requested_model": requested_model, "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"), "input_sha": sha256_text(payload_text), "prompt_sha": sha256_text(prompt_text), "response_sha": sha256_text(raw_response), "latency_ms": round((time.monotonic() - started) * 1000), "usage": envelope.get("usage", {}), "review": review}
            write_artifact(output_path, artifact)
            print(f"PASS_GITHUB_MODELS_CONNECTION model={artifact['actual_model']} decision={review['decision']} artifact={output_path}")
            return 0
        except ProviderRetired as exc:
            artifact = {**base, "status": "HOLD_GITHUB_MODELS_PROVIDER_RETIRED", "provider_available": False, "blocker_code": "HOLD_GITHUB_MODELS_HTTP_410", "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"), "input_sha": sha256_text(payload_text), "prompt_sha": sha256_text(prompt_text), "latency_ms": round((time.monotonic() - started) * 1000), "review": retired_review(), "final_authority": "DETERMINISTIC_REPLAY_STATISTICS_HARD_GATES"}
            write_artifact(output_path, artifact)
            print(f"HOLD_GITHUB_MODELS_PROVIDER_RETIRED blocker={exc} artifact={output_path}")
            return 0
    except Exception as exc:
        text = str(exc)
        blocker = text if text.startswith(("HOLD_", "FORBIDDEN_", "INPUT_", "RESPONSE_")) else type(exc).__name__
        artifact = {**base, "status": "HOLD_GITHUB_MODELS_CONNECTION", "blocker_code": blocker, "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"), "latency_ms": round((time.monotonic() - started) * 1000)}
        write_artifact(output_path, artifact)
        print(f"HOLD_GITHUB_MODELS_CONNECTION blocker={blocker} artifact={output_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
