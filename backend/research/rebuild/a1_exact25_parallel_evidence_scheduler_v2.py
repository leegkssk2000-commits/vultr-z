from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.research.rebuild import a1_exact25_parallel_evidence_scheduler_v1 as v1
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

v1.ge.policy_functions = policy_functions

_route_prepare_v1 = v1.route_prepare
_route_after_receipt_v1 = v1.route_after_receipt


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _release_active_until_due(
    sid: str,
    ledger: dict[str, Any],
    clock: dict[str, Any],
    *,
    next_probe_utc: str,
) -> None:
    row = clock["strategies"][sid]
    row["state"] = "WAITING_EVIDENCE"
    row["next_probe_utc"] = next_probe_utc
    drow = ledger["strategies"][sid]
    if str(drow.get("status")) == "ACTIVE":
        drow["status"] = "UNTESTED"
    if ledger.get("active_strategy_id") == sid:
        ledger["active_strategy_id"] = None


def route_prepare(
    ledger: dict[str, Any],
    clock: dict[str, Any],
    *,
    now: datetime,
) -> tuple[str | None, bool]:
    """Release a previously probed heavy slot until its next closed-bar cadence."""
    current = ledger.get("active_strategy_id")
    if current:
        drow = ledger["strategies"][current]
        crow = clock["strategies"][current]
        if (
            crow.get("source_ready") is True
            and str(drow.get("status") or "") not in v1.TERMINAL
            and crow.get("last_probe_utc")
        ):
            tf_ms = int(crow.get("timeframe_ms") or 3_600_000)
            due = _parse_utc(str(crow["last_probe_utc"])) + timedelta(milliseconds=max(tf_ms, 60_000))
            if now < due:
                _release_active_until_due(current, ledger, clock, next_probe_utc=v1.iso(due))
                ranked = v1._rank(list(ledger["strategy_order"]), clock, now=now, exclude={current})
                if ranked:
                    v1._activate(ranked[0], ledger, clock)
                    return ranked[0], True
                return None, True
    return _route_prepare_v1(ledger, clock, now=now)


def route_after_receipt(
    ledger: dict[str, Any],
    clock: dict[str, Any],
    receipt: dict[str, Any],
    *,
    now: datetime,
) -> tuple[str | None, bool]:
    """After every nonterminal probe, release heavy until the next valid closed bar."""
    sid = str(receipt["strategy_id"])
    next_sid, changed = _route_after_receipt_v1(ledger, clock, receipt, now=now)
    drow = ledger["strategies"][sid]
    if str(drow.get("status") or "") in v1.TERMINAL or changed or next_sid != sid:
        return next_sid, changed

    crow = clock["strategies"][sid]
    tf_ms = int(crow.get("timeframe_ms") or 3_600_000)
    due = now + timedelta(milliseconds=max(tf_ms, 60_000))
    _release_active_until_due(sid, ledger, clock, next_probe_utc=v1.iso(due))

    ranked = v1._rank(list(ledger["strategy_order"]), clock, now=now, exclude={sid})
    if ranked:
        v1._activate(ranked[0], ledger, clock)
        return ranked[0], True
    return None, True


v1.route_prepare = route_prepare
v1.route_after_receipt = route_after_receipt


if __name__ == "__main__":
    v1.main()
