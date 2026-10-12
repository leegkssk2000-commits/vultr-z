"""Backend runner for P0-P2 virtual-asset readiness.

The runner deliberately keeps live execution blocked. It is safe to import in
health checks and tests because it does not touch runtime data at import time.

Architecture invariant:
strategy -> raw candidate -> TeamBot(L/M/O/S) -> Z-OS risk -> executor.
A raw strategy signal or TeamBot-only signal can never be passed directly to an
executor.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from config.settings import (
    DATA_STALE_SEC,
    LIVE_MIN_DAYS,
    LIVE_MIN_TRADES,
    MISSED_FILL_RATE_MAX,
    SLIPPAGE_P95_MAX,
    TRACKING_ERR_MAX,
)
from engine.exec_live import exec_live
from engine.exec_shadow import exec_shadow
from engine.gate import precheck
from engine.utils.state import load_state


P0_P2_BLOCK_REASON = "p0_p2_gate_blocks_live_execution"
TEAM_BYPASS_BLOCK_REASON = "team_bot_hierarchy_required"
RISK_BYPASS_BLOCK_REASON = "z_os_risk_gate_required"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def gate_status(data_stale_sec: int | None = None, rows: int | None = None) -> dict[str, Any]:
    """Return a fail-closed gate snapshot for public health/smoke checks."""
    warmup_gate = None if rows is None else precheck([None] * rows, data_stale_sec, min_rows=1)
    stale = data_stale_sec is not None and data_stale_sec > DATA_STALE_SEC
    return {
        "ok": not stale and warmup_gate is None,
        "p0_runtime_hygiene": True,
        "p1_public_surface_ready": not stale,
        "p2_mindata_hard_binding": "blocked_until_real_source",
        "higher_roadmap_blocked": True,
        "execution_allowed": False,
        "live_execution_enabled": False,
        "reason": "ok" if not stale and warmup_gate is None else (warmup_gate or {}).get("why", "stale"),
    }


def ok_auto_promote(metrics: dict[str, Any] | None = None, started_at: datetime | None = None) -> bool:
    """P0-P2 always blocks promotion even if metrics look healthy."""
    metrics = metrics or {}
    required = (
        "trades_cnt",
        "tracking_err_p95",
        "slippage_p95",
        "missed_fill_rate",
    )
    if any(metrics.get(name) is None for name in required):
        return False

    started_at = started_at or load_state()[1]
    days = (_utcnow() - started_at).days if started_at else 0
    try:
        checks_pass = (
            int(metrics["trades_cnt"]) >= LIVE_MIN_TRADES
            and days >= LIVE_MIN_DAYS
            and float(metrics["tracking_err_p95"]) <= TRACKING_ERR_MAX
            and float(metrics["slippage_p95"]) <= SLIPPAGE_P95_MAX
            and float(metrics["missed_fill_rate"]) <= MISSED_FILL_RATE_MAX
        )
    except (TypeError, ValueError):
        return False
    return bool(checks_pass and False)


def select_exec() -> Any:
    """Select an executor without granting live authority."""
    force = os.getenv("FORCE_MODE", "").strip().lower()
    if force == "live":
        return exec_live
    return exec_shadow


def run_once(names: Iterable[str], **kwargs: Any) -> dict[str, Any]:
    """Collect raw strategy candidates without execution authority.

    Each actionable candidate receives a deterministic id so an upstream
    TeamBot decision can be bound to that exact strategy output.
    """
    from engine.router import route
    from engine.team_layer import build_candidate_id

    results: dict[str, Any] = {}
    for name in names:
        try:
            raw_signal = route(name, **kwargs)
            results[name] = {
                "raw_signal": raw_signal,
                "candidate_id": build_candidate_id(name, raw_signal),
                "execution_eligible": False,
                "execution_authority": "none",
                "next_layer": "team_bot",
            }
        except Exception as exc:
            results[name] = {
                "error": str(exc),
                "candidate_id": None,
                "execution_eligible": False,
                "execution_authority": "none",
                "next_layer": "team_bot",
            }
    return results


def _decision_for_strategy(
    name: str,
    per_strategy: Mapping[str, Any] | None,
    shared: Mapping[str, Any] | None,
    *,
    allow_shared: bool,
) -> Mapping[str, Any] | None:
    if isinstance(per_strategy, Mapping):
        candidate = per_strategy.get(name)
        if isinstance(candidate, Mapping):
            return candidate
    if allow_shared and isinstance(shared, Mapping):
        return shared
    return None


def _blocked_execution(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "execution_allowed": False,
        "reason": reason,
    }


def run_and_trade(names: Iterable[str], symbol: str, qty: float | None = None, **kwargs: Any) -> dict[str, Any]:
    names_list = list(names)
    gate = precheck(kwargs.get("df"), kwargs.get("data_stale_sec"))
    if gate:
        return {name: gate for name in names_list}

    from engine.risk_unit import authorize_execution
    from engine.router import route
    from engine.team_layer import authorize_team_signal

    routing_kwargs = dict(kwargs)
    team_decisions = routing_kwargs.pop("team_decisions", None)
    shared_team_decision = routing_kwargs.pop("team_decision", None)
    risk_decisions = routing_kwargs.pop("risk_decisions", None)
    shared_risk_decision = routing_kwargs.pop("risk_decision", None)
    allow_shared = len(names_list) == 1

    results: dict[str, Any] = {}
    executor = select_exec()
    for name in names_list:
        try:
            raw_signal = route(name, **routing_kwargs)
            team_decision = _decision_for_strategy(
                name,
                team_decisions,
                shared_team_decision,
                allow_shared=allow_shared,
            )
            team_signal = authorize_team_signal(raw_signal, team_decision, strategy_name=name)

            if not team_signal.get("execution_eligible"):
                results[name] = {
                    "raw_signal": raw_signal,
                    "team_signal": team_signal,
                    "signal": team_signal,
                    "execution": _blocked_execution(team_signal.get("reason", TEAM_BYPASS_BLOCK_REASON)),
                }
                continue

            risk_decision = _decision_for_strategy(
                name,
                risk_decisions,
                shared_risk_decision,
                allow_shared=allow_shared,
            )
            execution_signal = authorize_execution(team_signal, risk_decision)
            if not execution_signal.get("execution_eligible"):
                results[name] = {
                    "raw_signal": raw_signal,
                    "team_signal": team_signal,
                    "signal": execution_signal,
                    "execution": _blocked_execution(execution_signal.get("reason", RISK_BYPASS_BLOCK_REASON)),
                }
                continue

            order = {
                "symbol": symbol,
                "strategy": name,
                "candidate_id": execution_signal.get("candidate_id"),
                "signal": execution_signal,
            }
            if qty is not None:
                order["qty"] = qty
            results[name] = {
                "raw_signal": raw_signal,
                "team_signal": team_signal,
                "signal": execution_signal,
                "execution": executor.place(order),
            }
        except Exception as exc:
            results[name] = {
                "error": str(exc),
                "execution_allowed": False,
                "reason": P0_P2_BLOCK_REASON,
            }
    return results
