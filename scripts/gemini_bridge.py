#!/usr/bin/env python3
"""Isolated, free-tier-only Gemini analysis bridge for GitHub Actions.

Reads .gemini-bridge/request.json and writes evidence under
.gemini-bridge/out/. It never modifies project/runtime files and never enables
Google Search grounding or other billable tools.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REQUEST_PATH = Path(".gemini-bridge/request.json")
OUT_DIR = Path(".gemini-bridge/out")
API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
ALLOWED_MODEL = "gemini-3.6-flash"
ALLOWED_MODES = {"youtube_summary", "youtube_compare", "text_task"}
MAX_YOUTUBE_URLS = 5
MAX_SOURCE_CHARS = 200_000


def _find_text(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("output_text", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for candidate in value.values():
            found = _find_text(candidate)
            if found:
                return found
    elif isinstance(value, list):
        for candidate in value:
            found = _find_text(candidate)
            if found:
                return found
    return None


def _write_status(
    *,
    ok: bool,
    request_id: str,
    message: str,
    error: str = "",
    mode: str = "unknown",
    model: str = ALLOWED_MODEL,
    youtube_count: int = 0,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "request_id": request_id,
        "mode": mode,
        "model": model,
        "youtube_count": youtube_count,
        "free_only": True,
        "search_grounding": False,
        "repository_mutation": False,
        "message": message,
        "error": error,
    }
    (OUT_DIR / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "result.md").write_text(message + "\n", encoding="utf-8")


def main() -> int:
    request_id = "unknown"
    mode = "unknown"
    youtube_count = 0
    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        request_id = str(request.get("request_id") or "unknown")
        mode = str(request.get("mode") or "").strip()
        model = str(request.get("model") or ALLOWED_MODEL).strip()
        prompt = str(request.get("prompt") or "").strip()
        source_text = str(request.get("source_text") or "").strip()
        youtube_urls = request.get("youtube_urls") or []
        free_only = request.get("free_only", True)

        if free_only is not True:
            raise ValueError("free_only must be true")
        if model != ALLOWED_MODEL:
            raise ValueError(f"model must be {ALLOWED_MODEL}")
        if request.get("tools") or request.get("use_google_search"):
            raise ValueError("tools and Google Search grounding are forbidden")
        if mode not in ALLOWED_MODES:
            raise ValueError(f"mode must be one of {sorted(ALLOWED_MODES)}")
        if not prompt:
            raise ValueError("prompt is required")
        if len(source_text) > MAX_SOURCE_CHARS:
            raise ValueError(f"source_text exceeds {MAX_SOURCE_CHARS} characters")
        if not isinstance(youtube_urls, list):
            raise ValueError("youtube_urls must be a list")
        youtube_count = len(youtube_urls)
        if mode in {"youtube_summary", "youtube_compare"} and not youtube_urls:
            raise ValueError(f"{mode} requires at least one YouTube URL")
        if youtube_count > MAX_YOUTUBE_URLS:
            raise ValueError(f"at most {MAX_YOUTUBE_URLS} YouTube URLs are allowed")

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY secret is missing or empty")

        safety_context = (
            "You are a read-only research assistant. Do not propose or perform repository, "
            "strategy, runtime, deployment, trading, or order mutations. Separate verified "
            "claims, creator opinions, assumptions, and contradictions. Popularity or view count "
            "is not evidence of correctness. For videos, include useful timestamps when possible. "
            "Return analysis only.\n\n"
        )
        inputs: list[dict[str, str]] = [
            {"type": "text", "text": safety_context + prompt}
        ]
        if source_text:
            inputs.append({"type": "text", "text": "SOURCE MATERIAL:\n" + source_text})
        for url in youtube_urls:
            url_text = str(url).strip()
            if not url_text.startswith(("https://www.youtube.com/", "https://youtu.be/")):
                raise ValueError(f"unsupported YouTube URL: {url_text}")
            inputs.append({"type": "video", "uri": url_text})

        body = json.dumps({"model": model, "input": inputs}).encode("utf-8")
        http_request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        with urllib.request.urlopen(http_request, timeout=600) as response:
            raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "raw-response.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        text = _find_text(parsed)
        if not text:
            raise RuntimeError("Gemini response contained no readable output text")
        _write_status(
            ok=True,
            request_id=request_id,
            mode=mode,
            model=model,
            youtube_count=youtube_count,
            message=text,
        )
        return 0

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _write_status(
            ok=False,
            request_id=request_id,
            mode=mode,
            youtube_count=youtube_count,
            message="Gemini request failed.",
            error=f"HTTP {exc.code}: {detail[:2000]}",
        )
        return 1
    except Exception as exc:
        _write_status(
            ok=False,
            request_id=request_id,
            mode=mode,
            youtube_count=youtube_count,
            message="Gemini bridge failed.",
            error=f"{type(exc).__name__}: {exc}"[:2000],
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
