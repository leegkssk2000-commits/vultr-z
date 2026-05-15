"""Fail-closed live execution adapter.

P0-P2 backend readiness must never create live trading capability.  This
adapter is intentionally non-executing: callers may route to it when a live
mode is requested, but every order is blocked with a structured response.
"""

from __future__ import annotations

from typing import Any


LIVE_EXECUTION_ENABLED = False
BLOCK_REASON = "live_execution_disabled_until_p3_gate"


class DisabledLiveExec:
    mode = "live_disabled"

    def place(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "blocked",
            "mode": self.mode,
            "reason": BLOCK_REASON,
            "execution_allowed": False,
        }

    def cancel(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "blocked",
            "mode": self.mode,
            "reason": BLOCK_REASON,
            "execution_allowed": False,
        }


exec_live = DisabledLiveExec()
