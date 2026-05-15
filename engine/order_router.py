"""Signal-to-executor router with P0-P2 fail-closed live behavior."""

from __future__ import annotations

from typing import Any

from engine.runner import P0_P2_BLOCK_REASON, select_exec


def handle_signal(symbol: str, sig: dict[str, Any], base_qty: float | None = None) -> dict[str, Any]:
    if not sig or sig.get("side") not in {"buy", "sell"}:
        return {"status": "skip", "execution_allowed": False}
    if base_qty is None:
        return {
            "status": "blocked",
            "execution_allowed": False,
            "reason": "missing_real_base_qty",
        }

    confidence = sig.get("confidence")
    try:
        qty = max(0.0, min(1.0, float(confidence))) * float(base_qty)
    except (TypeError, ValueError):
        return {
            "status": "blocked",
            "execution_allowed": False,
            "reason": "missing_real_confidence",
        }

    executor = select_exec()
    result = executor.place(
        symbol=symbol,
        side=sig["side"],
        qty=qty,
        meta={"source": sig.get("source"), "ttl": sig.get("ttl")},
    )
    result.setdefault("execution_allowed", False)
    if result.get("mode") == "live_disabled":
        result.setdefault("reason", P0_P2_BLOCK_REASON)
    return result
