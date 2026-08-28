"""Z-OS risk authority boundary.

A TeamBot-approved candidate may reach an executor only after Z-OS risk approval
for the same strategy candidate *and* the exact executable symbol/quantity.
Executor entry points re-derive TeamBot evidence instead of trusting asserted
authority strings.

No risk thresholds are invented here. Threshold logic remains SSOT-owned; this
module enforces provenance, order identity, and fail-closed sequencing only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


RISK_AUTHORITY = "z_os_risk_gate"
RISK_BLOCK_REASON = "z_os_risk_gate_required"
TEAM_AUTHORITY = "team_bot_consensus"


def risk_check():
    # TODO: position size / SL / exposure / DD checks remain SSOT-owned.
    print("risk check")


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "approved": False,
        "execution_eligible": False,
        "execution_authority": "none",
        "reason": reason,
        "next_layer": "z_os_risk",
    }


def _normalized_qty(value: Any) -> Decimal | None:
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not qty.is_finite() or qty <= 0:
        return None
    return qty


def _revalidate_team_signal(team_signal: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """Recompute TeamBot authorization from the embedded raw candidate/evidence."""
    if not isinstance(team_signal, Mapping):
        return None, "invalid_team_signal"

    strategy = team_signal.get("strategy")
    raw_signal = team_signal.get("strategy_signal")
    team_bots = team_signal.get("team_bots")
    candidate_id = team_signal.get("candidate_id")
    if not strategy or not isinstance(raw_signal, Mapping):
        return None, "team_signal_evidence_missing"

    from engine.team_layer import authorize_team_signal, build_candidate_id

    recomputed_id = build_candidate_id(strategy, raw_signal)
    if not recomputed_id or recomputed_id != candidate_id:
        return None, "team_candidate_recompute_mismatch"

    decision = {
        "team": team_signal.get("team"),
        "strategy": strategy,
        "candidate_id": candidate_id,
        "side": team_signal.get("side"),
        "approved": team_signal.get("approved") is True,
        "team_bots": team_bots,
        "confidence": team_signal.get("confidence"),
    }
    rebuilt = authorize_team_signal(raw_signal, decision, strategy_name=strategy)
    if rebuilt.get("execution_eligible") is not True:
        return None, rebuilt.get("reason", "team_signal_revalidation_failed")
    return rebuilt, "ok"


def authorize_execution(
    team_signal: Mapping[str, Any] | None,
    risk_decision: Mapping[str, Any] | None,
    *,
    symbol: str | None,
    qty: Any,
) -> dict[str, Any]:
    """Authorize the exact executable order after TeamBot + Z-OS approval."""
    rebuilt_team, team_reason = _revalidate_team_signal(team_signal)
    if rebuilt_team is None:
        return _blocked(team_reason)

    strategy = rebuilt_team["strategy"]
    candidate_id = rebuilt_team["candidate_id"]

    if not isinstance(symbol, str) or not symbol.strip():
        return _blocked("execution_symbol_required")
    normalized_symbol = symbol.strip()
    normalized_qty = _normalized_qty(qty)
    if normalized_qty is None:
        return _blocked("execution_qty_required")

    if not isinstance(risk_decision, Mapping):
        return _blocked(RISK_BLOCK_REASON)
    if risk_decision.get("strategy") != strategy:
        return _blocked("risk_strategy_identity_mismatch")
    if risk_decision.get("candidate_id") != candidate_id:
        return _blocked("risk_candidate_identity_mismatch")
    if risk_decision.get("symbol") != normalized_symbol:
        return _blocked("risk_symbol_identity_mismatch")
    risk_qty = _normalized_qty(risk_decision.get("qty"))
    if risk_qty is None or risk_qty != normalized_qty:
        return _blocked("risk_qty_identity_mismatch")
    if risk_decision.get("approved") is not True:
        return _blocked("z_os_risk_not_approved")
    if risk_decision.get("execution_eligible") is not True:
        return _blocked("z_os_risk_not_execution_eligible")
    if risk_decision.get("authority") != RISK_AUTHORITY:
        return _blocked("invalid_z_os_risk_authority")

    return {
        "ok": True,
        "approved": True,
        "execution_eligible": True,
        "execution_authority": RISK_AUTHORITY,
        "source": RISK_AUTHORITY,
        "strategy": strategy,
        "candidate_id": candidate_id,
        "symbol": normalized_symbol,
        "qty": str(normalized_qty),
        "team_signal": rebuilt_team,
        "risk_decision": dict(risk_decision),
        "side": rebuilt_team.get("side"),
        "confidence": rebuilt_team.get("confidence"),
        "team": rebuilt_team.get("team"),
        "next_layer": "executor",
    }


def validate_execution_signal(signal: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Recompute every embedded authority proof at an executor entry point."""
    if not isinstance(signal, Mapping):
        return False, "invalid_execution_signal"
    if signal.get("execution_eligible") is not True:
        return False, "z_os_risk_not_execution_eligible"
    if signal.get("execution_authority") != RISK_AUTHORITY:
        return False, "invalid_z_os_risk_authority"
    if signal.get("next_layer") != "executor":
        return False, "invalid_execution_signal_route"

    team_signal = signal.get("team_signal")
    rebuilt_team, team_reason = _revalidate_team_signal(team_signal)
    if rebuilt_team is None:
        return False, team_reason

    rebuilt_execution = authorize_execution(
        rebuilt_team,
        signal.get("risk_decision"),
        symbol=signal.get("symbol"),
        qty=signal.get("qty"),
    )
    if rebuilt_execution.get("execution_eligible") is not True:
        return False, rebuilt_execution.get("reason", "execution_revalidation_failed")

    fields = ("strategy", "candidate_id", "symbol", "side", "team")
    for field in fields:
        if signal.get(field) != rebuilt_execution.get(field):
            return False, f"execution_{field}_mismatch"

    if _normalized_qty(signal.get("qty")) != _normalized_qty(rebuilt_execution.get("qty")):
        return False, "execution_qty_mismatch"
    return True, "ok"
