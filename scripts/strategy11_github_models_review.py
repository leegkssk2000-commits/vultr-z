#!/usr/bin/env python3
"""Read-only GitHub Models reviewer for Strategy11 major research gates.

This client accepts anonymized evidence, rejects private/order-bearing fields,
performs one JSON-only independent review through GitHub Models, and emits a
lineage artifact. It has no promotion, execution, runtime, Shadow, Paper,
Live, registry, router, or order authority.
"""

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
FORBIDDEN_KEY_FRAGMENTS = {
    "account",
    "api_key",
    "credential",
    "exchange_key",
    "order",
    "password",
    "position",
    "private_key",
    "secret",
    "token",
    "wallet",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_anonymized(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS):
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

    # Deliberately incomplete non-sensitive fixture. A correct major-gate
    # reviewer must fail closed because sample size and W2/W3 evidence are absent.
    return {
        "stage": "CORE_CLASSIFICATION_REVIEW",
        "strategy_id": "fixture_strategy",
        "candidate": {
            "axis": "TREND_REGIME_GATE",
            "generation": 1,
            "research_only": True,
        },
        "metrics": {
            "trades": 8,
            "win_rate_pct": 62.5,
            "net_r": 1.8,
            "profit_factor": 1.42,
            "payoff": 1.15,
            "max_drawdown_r": -1.1,
            "normal_worst_loss_r": -0.88,
            "stress_worst_loss_r": -0.94,
            "retention_pct": 81.0,
            "positive_windows": 1,
        },
        "oos_windows": {"W1": "PASS", "W2": "MISSING", "W3": "MISSING"},
        "lineage": {
            "source_sha": "fixture-source-sha",
            "data_sha": "fixture-data-sha",
            "window_sha": "fixture-window-sha",
            "candidate_sha": "fixture-candidate-sha",
        },
    }


def build_prompt(payload: dict[str, Any]) -> str:
    contract = {
        "decision": "PASS_TO_NEXT_GATE|REJECT|HOLD",
        "blocker_codes": ["string"],
        "evidence_complete": False,
        "oos_supported": False,
        "overfit_risk": "LOW|MEDIUM|HIGH",
        "reason": "one concise sentence",
    }
    return (
        "You are the independent third reviewer for Strategy11 major research "
        "gates only. You have no promotion or execution authority. Return one "
        "JSON object only and exactly match the contract. Apply these hard rules: "
        "trades below 30 requires HOLD with LOW_SAMPLE_SIZE; missing W2 or W3 "
        "requires HOLD with MISSING_OOS_WINDOWS; missing lineage requires HOLD; "
        "single-score or win-rate-only evidence cannot pass; any protected or "
        "execution authority must be rejected. Do not infer missing evidence.\n"
        f"Contract: {canonical_json(contract)}\n"
        f"Anonymized evidence: {canonical_json(payload)}"
    )


def strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def validate_review(review: Any) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("RESPONSE_NOT_JSON_OBJECT")
    required = {
        "decision",
        "blocker_codes",
        "evidence_complete",
        "oos_supported",
        "overfit_risk",
        "reason",
    }
    if set(review) != required:
        raise ValueError("RESPONSE_JSON_SHAPE_MISMATCH")
    if review["decision"] not in ALLOWED_DECISIONS:
        raise ValueError("RESPONSE_DECISION_INVALID")
    if not isinstance(review["blocker_codes"], list) or not all(
        isinstance(item, str) for item in review["blocker_codes"]
    ):
        raise ValueError("RESPONSE_BLOCKERS_INVALID")
    if not isinstance(review["evidence_complete"], bool):
        raise ValueError("RESPONSE_EVIDENCE_INVALID")
    if not isinstance(review["oos_supported"], bool):
        raise ValueError("RESPONSE_OOS_INVALID")
    if review["overfit_risk"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise ValueError("RESPONSE_OVERFIT_INVALID")
    if not isinstance(review["reason"], str) or not review["reason"].strip():
        raise ValueError("RESPONSE_REASON_INVALID")
    return review


def call_model(token: str, model: str, prompt: str) -> tuple[str, dict[str, Any]]:
    request_body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=canonical_json(request_body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw_http = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HOLD_GITHUB_MODELS_HTTP_{exc.code}:{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("HOLD_GITHUB_MODELS_NETWORK") from exc

    envelope = json.loads(raw_http)
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("RESPONSE_CHOICES_MISSING")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("RESPONSE_CONTENT_MISSING")
    return content, envelope


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to anonymized major-gate JSON payload")
    parser.add_argument(
        "--output",
        default="artifacts/strategy11_github_models_review.json",
        help="Result artifact path",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    started = time.monotonic()
    token = os.environ.get("GITHUB_TOKEN", "")
    base_artifact: dict[str, Any] = {
        "schema_version": "strategy11.github_models_review.v1",
        "provider": "github_models",
        "GITHUB_MODELS_USED": False,
        "token_present": bool(token),
        "token_sha_recorded": False,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "research_only": True,
    }

    try:
        if not token:
            raise RuntimeError("HOLD_GITHUB_TOKEN_MISSING")

        payload = load_payload(args.input)
        assert_anonymized(payload)
        payload_text = canonical_json(payload)
        prompt = build_prompt(payload)
        model = os.environ.get("GITHUB_MODELS_MODEL", DEFAULT_MODEL)

        raw_response, envelope = call_model(token, model, prompt)
        review = validate_review(json.loads(strip_code_fence(raw_response)))

        artifact = {
            **base_artifact,
            "status": "PASS_GITHUB_MODELS_CONNECTION",
            "GITHUB_MODELS_USED": True,
            "actual_model": envelope.get("model", model),
            "requested_model": model,
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "input_sha": sha256_text(payload_text),
            "prompt_sha": sha256_text(prompt),
            "response_sha": sha256_text(raw_response),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "usage": envelope.get("usage", {}),
            "review": review,
        }
        write_artifact(output_path, artifact)
        print(
            f"PASS_GITHUB_MODELS_CONNECTION model={artifact['actual_model']} "
            f"decision={review['decision']} artifact={output_path}"
        )
        return 0

    except Exception as exc:
        text = str(exc)
        blocker = text if text.startswith(("HOLD_", "FORBIDDEN_", "INPUT_", "RESPONSE_")) else type(exc).__name__
        artifact = {
            **base_artifact,
            "status": "HOLD_GITHUB_MODELS_CONNECTION",
            "blocker_code": blocker,
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        write_artifact(output_path, artifact)
        print(f"HOLD_GITHUB_MODELS_CONNECTION blocker={blocker} artifact={output_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
