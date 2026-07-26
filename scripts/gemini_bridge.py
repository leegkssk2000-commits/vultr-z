#!/usr/bin/env python3
"""Isolated Gemini bridge for GitHub Actions.

Reads .gemini-bridge/request.json and writes result artifacts under
.gemini-bridge/out/. It never modifies project/runtime files.
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


def _write_status(*, ok: bool, request_id: str, message: str, error: str = "") -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": ok,
        "request_id": request_id,
        "message": message,
        "error": error,
    }
    (OUT_DIR / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "result.md").write_text(message + "\n", encoding="utf-8")


def main() -> int:
    request_id = "unknown"
    try:
        request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        request_id = str(request.get("request_id") or "unknown")
        mode = str(request.get("mode") or "").strip()
        model = str(request.get("model") or "gemini-3.5-flash").strip()
        prompt = str(request.get("prompt") or "").strip()
        source_text = str(request.get("source_text") or "").strip()
        youtube_urls = request.get("youtube_urls") or []

        if mode not in {"youtube_summary", "text_task"}:
            raise ValueError("mode must be youtube_summary or text_task")
        if not prompt:
            raise ValueError("prompt is required")
        if not isinstance(youtube_urls, list):
            raise ValueError("youtube_urls must be a list")
        if mode == "youtube_summary" and not youtube_urls:
            raise ValueError("youtube_summary requires at least one YouTube URL")
        if len(youtube_urls) > 10:
            raise ValueError("at most 10 YouTube URLs are allowed per request")

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY secret is missing or empty")

        inputs: list[dict[str, str]] = [{"type": "text", "text": prompt}]
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

        with urllib.request.urlopen(http_request, timeout=300) as response:
            raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "raw-response.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        text = _find_text(parsed)
        if not text:
            raise RuntimeError("Gemini response contained no readable output text")
        _write_status(ok=True, request_id=request_id, message=text)
        return 0

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _write_status(
            ok=False,
            request_id=request_id,
            message="Gemini request failed.",
            error=f"HTTP {exc.code}: {detail}",
        )
        return 1
    except Exception as exc:  # fail into artifact, not repository mutation
        _write_status(
            ok=False,
            request_id=request_id,
            message="Gemini bridge failed.",
            error=f"{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
