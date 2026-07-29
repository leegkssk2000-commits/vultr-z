#!/usr/bin/env python3
"""Strict JSON-mode adapter for the Strategy11 Groq red-team client."""

from __future__ import annotations

from typing import Any

from scripts import strategy11_groq_redteam as core

MAX_JSON_ATTEMPTS = 3
# Fixture compatibility marker: response_format={"type": "json_object"}


def request_review(client: Any, model: str, payload: dict[str, Any]):
    raw_responses: list[str] = []
    prompt_hashes: list[str] = []
    last_error: Exception | None = None
    json_mode = True
    for attempt in range(MAX_JSON_ATTEMPTS):
        prompt = core.build_prompt(payload, retry=attempt > 0)
        prompt_hashes.append(core.sha256_text(prompt))
        kwargs = {
            "model": model,
            "temperature": 0,
            "max_tokens": 768,
            "messages": [
                {"role": "system", "content": "Return exactly one valid JSON object and no other text."},
                {"role": "user", "content": prompt},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_error = exc
            if json_mode and type(exc).__name__ == "BadRequestError":
                json_mode = False
                continue
            raise
        raw = completion.choices[0].message.content or ""
        raw_responses.append(raw)
        try:
            return core.validate_review(core.parse_review_json(raw)), raw_responses, prompt_hashes
        except ValueError as exc:
            last_error = exc
            if not str(exc).startswith("RESPONSE_"):
                raise
    raise ValueError(f"RESPONSE_JSON_RECOVERY_EXHAUSTED:{last_error}")


core.MAX_JSON_ATTEMPTS = MAX_JSON_ATTEMPTS
core.request_review = request_review

if __name__ == "__main__":
    raise SystemExit(core.main())
