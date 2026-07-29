#!/usr/bin/env python3
"""Strict JSON-mode adapter for the Strategy11 Groq red-team client."""

from __future__ import annotations

from typing import Any

from scripts import strategy11_groq_redteam as core

MAX_JSON_ATTEMPTS = 3


def request_review(client: Any, model: str, payload: dict[str, Any]):
    raw_responses: list[str] = []
    prompt_hashes: list[str] = []
    last_error: Exception | None = None
    for attempt in range(MAX_JSON_ATTEMPTS):
        prompt = core.build_prompt(payload, retry=attempt > 0)
        prompt_hashes.append(core.sha256_text(prompt))
        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=768,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return exactly one valid JSON object and no other text."},
                {"role": "user", "content": prompt},
            ],
        )
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
