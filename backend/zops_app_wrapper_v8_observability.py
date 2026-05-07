"""Minimal ASGI wrapper for read-only portfolio observability."""

from __future__ import annotations

import json
from typing import Any

from backend.portfolio_binding import load_or_refresh_artifact


async def _send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope.get("type") != "http":
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})
        return

    path = scope.get("path") or ""
    method = scope.get("method") or "GET"
    if method != "GET":
        await _send_json(send, 405, {"ok": False, "reason": "method_not_allowed"})
        return
    if path == "/healthz":
        await _send_json(send, 200, {"ok": True})
        return
    if path == "/api/portfolio/state":
        await _send_json(send, 200, load_or_refresh_artifact("state"))
        return
    if path == "/api/portfolio/virtual":
        await _send_json(send, 200, load_or_refresh_artifact("virtual"))
        return
    if path == "/api/portfolio/positions":
        await _send_json(send, 200, load_or_refresh_artifact("positions"))
        return
    if path == "/api/portfolio/pnl-bars":
        await _send_json(send, 200, load_or_refresh_artifact("pnl-bars"))
        return
    if path == "/api/portfolio/equity-curve":
        await _send_json(send, 200, load_or_refresh_artifact("equity-curve"))
        return
    await _send_json(send, 404, {"ok": False, "reason": "not_found"})
