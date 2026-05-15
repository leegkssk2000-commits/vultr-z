"""Paper/shadow execution adapter.

This module records intent only.  It does not submit orders, mutate exchange
state, or open live trading authority.
"""

from __future__ import annotations

from typing import Any


class ShadowExec:
    mode = "paper"

    def place(self, order: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = dict(order or {})
        payload.update(kwargs)
        return {
            "ok": True,
            "status": "accepted_shadow",
            "mode": self.mode,
            "execution_allowed": False,
            "order": payload,
        }

    def cancel(self, oid: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "accepted_shadow_cancel",
            "mode": self.mode,
            "execution_allowed": False,
            "oid": oid,
        }


exec_shadow = ShadowExec()
