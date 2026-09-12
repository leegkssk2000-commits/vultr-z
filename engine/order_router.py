"""Final Z-OS-signal-to-executor router with P0-P2 fail-closed behavior."""

from __future__ import annotations

from typing import Any

from engine.risk_unit import validate_execution_signal
from engine.runner import P0_P2_BLOCK_REASON, select_exec


def handle_signal(symbol: str, sig: dict[str, Any], base_qty: float | None = None) -> dict[str, Any]:
    """Route only a fully TeamBot + Z-OS-risk-authorized execution signal.

    Raw strategy signals and TeamBot-only signals are rejected here even if a
    caller bypasses ``engine.runner.run_and_trade``.
    """
    valid, reason = validate_execution_signal(sig)
    if not valid:
        return {
            "status": "blocked",
            "execution_allowed": False,
            "reason": reason,
        }

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
        meta={
            "source": sig.get("source"),
            "strategy": sig.get("strategy"),
            "candidate_id": sig.get("candidate_id"),
        },
    )
    result.setdefault("execution_allowed", False)
    if result.get("mode") == "live_disabled":
        result.setdefault("reason", P0_P2_BLOCK_REASON)
    return result
