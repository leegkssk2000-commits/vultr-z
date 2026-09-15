"""Causal seven-sleeve research allocation; no account, order, or Core authority.

Allocation uses only signal identities, clocked source status, outstanding
capital, and shadow outcomes available strictly before a decision. A completed
trade row is future fill evidence, never a current health feature. Both closed
and unresolved candidate positions must be supplied to preserve capacity.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

SLEEVE_COUNT = 7
SLEEVE_WEIGHT = 1.0 / SLEEVE_COUNT
COLD_START_MULTIPLIER = 0.5
SCHEMA = "zel.scalp7.causal_portfolio.v2"


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("NONFINITE:" + name)
    return result


def _stamp(value: Any) -> int:
    stamp = int(value)
    if float(value) != stamp:
        raise ValueError("NONINTEGER_TIMESTAMP")
    return stamp


def _key(signal: Mapping[str, Any]) -> str:
    identity = {
        key: signal.get(key)
        for key in ("identity", "symbol", "signal_ts_ms", "side", "legs")
    }
    return hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _prepare(
    raw: Mapping[str, Any], identity_to_lane: Mapping[str, str]
) -> dict[str, Any] | None:
    position = raw.get("position", {})
    signal = raw.get("signal") or position.get("signal") or raw
    identity = str(raw.get("identity", signal.get("identity", "")))
    if (
        "identity" in raw
        and "identity" in signal
        and str(raw["identity"]) != str(signal["identity"])
    ):
        raise ValueError("RAW_SIGNAL_IDENTITY_MISMATCH")
    if identity not in identity_to_lane:
        return None
    if _stamp(signal.get("timeframe_min", raw.get("timeframe_min", 0))) not in (15, 30):
        raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    ts = _stamp(signal["signal_ts_ms"])
    feature_available = signal.get("meta", {}).get("feature_available_ts_ms")
    if feature_available is not None and _stamp(feature_available) > ts:
        raise ValueError("SIGNAL_BEFORE_CONTEXT_AVAILABILITY")
    entry = _stamp(raw.get("entry_ts_ms", position.get("entry_ts_ms")))
    if entry < ts:
        raise ValueError("FILL_BEFORE_SIGNAL")
    record: dict[str, Any] = {
        "key": _key({**signal, "identity": identity}),
        "identity": identity,
        "lane": identity_to_lane[identity],
        "symbol": str(signal["symbol"]),
        "signal_ts_ms": ts,
        "entry_ts_ms": entry,
        "signal": dict(signal),
        "raw": dict(raw),
        "closed": False,
    }
    if "net_bps" in raw:
        if "exit_ts_ms" not in raw or "outcome_available_ts_ms" not in raw:
            raise ValueError("OUTCOME_AVAILABILITY_UNBOUND")
        exit_ts = _stamp(raw["exit_ts_ms"])
        available = _stamp(raw["outcome_available_ts_ms"])
        if available < exit_ts or exit_ts < entry:
            raise ValueError("OUTCOME_CLOCK_INVALID")
        gross = _finite(raw["gross_bps"], "gross_bps")
        cost = _finite(raw["cost_bps"], "cost_bps")
        net = _finite(raw["net_bps"], "net_bps")
        if cost <= 0 or not math.isclose(
            net, gross - cost, rel_tol=1e-10, abs_tol=1e-7
        ):
            raise ValueError("COST_OR_NET_INCONSISTENT")
        record.update(
            {
                "closed": True,
                "exit_ts_ms": exit_ts,
                "outcome_available_ts_ms": available,
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": net,
            }
        )
    return record


def _health(values: Mapping[str, float], source_blocked: bool) -> dict[str, Any]:
    count, net, gains, losses = (
        int(values["count"]),
        values["net"],
        values["gains"],
        values["losses"],
    )
    if source_blocked:
        state, multiplier = "BLOCK_SOURCE", 0.0
    elif count == 0:
        state, multiplier = "THROTTLE_NO_COMPLETED_OUTCOME", COLD_START_MULTIPLIER
    elif net > 0 and (losses == 0 or gains / losses > 1.0):
        state, multiplier = "ALLOW_POSITIVE_COMPLETED_SHADOW", 1.0
    else:
        state, multiplier = "BLOCK_NONPOSITIVE_COMPLETED_SHADOW", 0.0
    return {
        "state": state,
        "multiplier": multiplier,
        "completed_shadow_T": count,
        "completed_shadow_net_bps": net,
        "completed_shadow_PF": gains / losses if losses > 0 else None,
        "pf_case": (
            "FINITE"
            if losses > 0
            else ("POSITIVE_GAIN_ZERO_LOSS" if gains > 0 else "NO_POSITIVE_GAIN")
        ),
        "promotion_authority": False,
        "limitations": [
            "Market state is inherited from frozen native valid-signal rules; no additional optimized portfolio regime gate.",
            "An observed source block persists to this research window end; no source recovery is inferred.",
        ],
    }


def _realized_metrics(
    rows: Sequence[Mapping[str, Any]], start: int, end: int
) -> dict[str, Any]:
    buckets: dict[int, float] = defaultdict(float)
    wins: list[float] = []
    losses: list[float] = []
    for row in rows:
        value = float(row["net_bps"])
        buckets[int(row["outcome_available_ts_ms"])] += value
        if value > 0:
            wins.append(value)
        elif value < 0:
            losses.append(-value)
    equity = peak = dd = 0.0
    sequence: list[dict[str, Any]] = []
    for ts, pnl in sorted(buckets.items()):
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        sequence.append(
            {
                "available_ts_ms": ts,
                "net_bps": pnl,
                "equity_bps": equity,
                "drawdown_bps": peak - equity,
            }
        )
    # Equal-timestamp outcomes are a simultaneous realized batch; no arbitrary
    # row ordering is allowed to manufacture a DD path or losing streak.
    streak = maximum = 0
    for _, pnl in sorted(buckets.items()):
        streak = streak + 1 if pnl < 0 else 0
        maximum = max(maximum, streak)
    count = len(rows)
    return {
        "T": count,
        "T_per_day": count / ((end - start) / 86_400_000),
        "WR": len(wins) / count if count else None,
        "gross_bps": sum(float(row["gross_bps"]) for row in rows),
        "cost_bps": sum(float(row["cost_bps"]) for row in rows),
        "net_bps": equity,
        "net_per_T_bps": equity / count if count else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
        "max_loss_batch_streak": maximum,
        "simultaneous_outcome_semantics": "GROUP_BY_OUTCOME_AVAILABILITY_NO_ARBITRARY_INTRABATCH_PATH",
        "equity_events": sequence,
    }


def route(
    trades: Sequence[Mapping[str, Any]],
    primary_ids: Mapping[str, str],
    start: int,
    end: int,
    *,
    mode: str = "adaptive",
    source_gap_events: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Allocate primary frozen identities in an independently flat research window.

    Modes are predeclared equal7 (no transfer) and adaptive. The latter allows
    positive prior-shadow-health lanes, blocks nonpositive completed health,
    halves unobserved sleeves and transfers remaining free capital only to
    already valid, same-decision-time signals with positive prior health.
    Source gaps require observed_ts_ms; unresolved outcome labels are never used
    before that clock. Outstanding unresolved allocations reserve capital.
    """
    start, end = _stamp(start), _stamp(end)
    if start >= end or mode not in {"equal7", "adaptive"}:
        raise ValueError("WINDOW_OR_MODE_INVALID")
    if (
        len(primary_ids) != SLEEVE_COUNT
        or len(set(primary_ids.values())) != SLEEVE_COUNT
    ):
        raise ValueError("EXACTLY_SEVEN_DISTINCT_PRIMARY_IDENTITIES_REQUIRED")
    identities = {str(identity): str(lane) for lane, identity in primary_ids.items()}
    records = []
    seen: set[str] = set()
    outside_window = 0
    for raw in trades:
        record = _prepare(raw, identities)
        if record is None:
            continue
        if not (start <= record["signal_ts_ms"] < end and record["entry_ts_ms"] < end):
            outside_window += 1
            continue
        if record["key"] in seen:
            raise ValueError("DUPLICATE_CANDIDATE_POSITION")
        seen.add(record["key"])
        records.append(record)
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["signal_ts_ms"]].append(record)
    outcomes = sorted(
        (record for record in records if record["closed"]),
        key=lambda record: (record["outcome_available_ts_ms"], record["key"]),
    )
    gaps = []
    for event in source_gap_events:
        identity = str(event.get("identity", ""))
        lane = identities.get(identity, str(event.get("lane", "")))
        if lane in primary_ids:
            gaps.append((_stamp(event["observed_ts_ms"]), lane))
    for record in records:
        if "source_block_ts_ms" in record["raw"]:
            gaps.append((_stamp(record["raw"]["source_block_ts_ms"]), record["lane"]))
    gaps.sort()
    health = {
        lane: {"count": 0.0, "net": 0.0, "gains": 0.0, "losses": 0.0}
        for lane in primary_ids
    }
    blocked_sources: set[str] = set()
    outcome_cursor = gap_cursor = 0
    active: dict[str, dict[str, Any]] = {}
    releases: list[tuple[int, str]] = []
    allocated_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    allocations = 0
    peak_gross = 0.0
    no_allocation = 0

    def release_through(ts: int) -> None:
        while releases and releases[0][0] <= ts:
            available, key = heapq.heappop(releases)
            allocation = active.pop(key)
            record, weight = allocation["record"], allocation["weight"]
            allocated_rows.append(
                {
                    **record["raw"],
                    "allocated_weight": weight,
                    "unallocated_gross_bps": record["gross_bps"],
                    "unallocated_cost_bps": record["cost_bps"],
                    "unallocated_net_bps": record["net_bps"],
                    "gross_bps": weight * record["gross_bps"],
                    "cost_bps": weight * record["cost_bps"],
                    "net_bps": weight * record["net_bps"],
                    "portfolio_policy": mode,
                    "portfolio_realized_ts_ms": available,
                }
            )
            events.append(
                {
                    "event": "REALIZED_RELEASE",
                    "available_ts_ms": available,
                    "identity": record["identity"],
                    "lane": record["lane"],
                    "position_key": key,
                    "released_weight": weight,
                    "weighted_net_bps": weight * record["net_bps"],
                }
            )

    for ts, cohort in sorted(groups.items()):
        release_through(ts)
        while (
            outcome_cursor < len(outcomes)
            and outcomes[outcome_cursor]["outcome_available_ts_ms"] < ts
        ):
            outcome = outcomes[outcome_cursor]
            state = health[outcome["lane"]]
            value = float(outcome["net_bps"])
            state["count"] += 1
            state["net"] += value
            state["gains"] += max(value, 0.0)
            state["losses"] += max(-value, 0.0)
            outcome_cursor += 1
        while gap_cursor < len(gaps) and gaps[gap_cursor][0] <= ts:
            blocked_sources.add(gaps[gap_cursor][1])
            gap_cursor += 1
        states = {
            lane: _health(health[lane], lane in blocked_sources) for lane in primary_ids
        }
        occupied: dict[str, float] = defaultdict(float)
        for allocation in active.values():
            occupied[allocation["record"]["lane"]] += allocation["weight"]
        active_total = sum(occupied.values())
        by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in sorted(cohort, key=lambda row: row["key"]):
            by_lane[record["lane"]].append(record)
        budgets: dict[str, float] = {}
        for lane in by_lane:
            multiplier = (
                (0.0 if lane in blocked_sources else 1.0)
                if mode == "equal7"
                else float(states[lane]["multiplier"])
            )
            budgets[lane] = max(0.0, SLEEVE_WEIGHT * multiplier - occupied[lane])
        available = max(0.0, 1.0 - active_total)
        base = sum(budgets.values())
        if base > available and base > 0:
            budgets = {
                lane: value * available / base for lane, value in budgets.items()
            }
        recipients = sorted(
            lane
            for lane in by_lane
            if states[lane]["state"] == "ALLOW_POSITIVE_COMPLETED_SHADOW"
        )
        transfer = (
            max(0.0, available - sum(budgets.values()))
            if mode == "adaptive" and recipients
            else 0.0
        )
        if transfer:
            for lane in recipients:
                budgets[lane] += transfer / len(recipients)
        new_total = sum(budgets.values())
        if active_total + new_total > 1.0 + 1e-12:
            raise AssertionError("RESEARCH_GROSS_CAPACITY_EXCEEDED")
        for lane, lane_records in sorted(by_lane.items()):
            weight = budgets[lane] / len(lane_records)
            for record in lane_records:
                if weight <= 1e-15:
                    no_allocation += 1
                    events.append(
                        {
                            "event": "NO_ALLOCATION",
                            "decision_ts_ms": ts,
                            "identity": record["identity"],
                            "lane": lane,
                            "position_key": record["key"],
                            "health": states[lane],
                            "reason": "SOURCE_HEALTH_OR_OCCUPIED_CAPACITY",
                        }
                    )
                    continue
                allocations += 1
                active[record["key"]] = {"record": record, "weight": weight}
                if record["closed"]:
                    heapq.heappush(
                        releases, (record["outcome_available_ts_ms"], record["key"])
                    )
                events.append(
                    {
                        "event": "ALLOCATE",
                        "decision_ts_ms": ts,
                        "entry_ts_ms": record["entry_ts_ms"],
                        "identity": record["identity"],
                        "lane": lane,
                        "symbol": record["symbol"],
                        "position_key": record["key"],
                        "weight": weight,
                        "health": states[lane],
                        "same_time_valid_signal_count": len(cohort),
                        "risk_transfer_recipient": lane in recipients and transfer > 0,
                        "market_state": record["signal"]
                        .get("meta", {})
                        .get("regime", "UNCLASSIFIED"),
                    }
                )
        peak_gross = max(peak_gross, active_total + new_total)
        events.append(
            {
                "event": "COHORT_CAPACITY",
                "decision_ts_ms": ts,
                "previous_active_weight": active_total,
                "new_weight": new_total,
                "gross_weight": active_total + new_total,
                "cash_weight": max(0.0, 1.0 - active_total - new_total),
                "same_time_valid_lanes": sorted(by_lane),
                "transfer_recipient_lanes": recipients if transfer > 0 else [],
                "transfer_weight": transfer,
            }
        )
    release_through(end - 1)
    open_allocations = [
        {
            "identity": allocation["record"]["identity"],
            "lane": allocation["record"]["lane"],
            "position_key": key,
            "entry_ts_ms": allocation["record"]["entry_ts_ms"],
            "weight": allocation["weight"],
            "state": "HOLD_UNRESOLVED_OR_WINDOW_CARRYOUT",
            "realized_pnl": None,
        }
        for key, allocation in sorted(active.items())
    ]
    metrics = _realized_metrics(allocated_rows, start, end)
    return {
        "schema": SCHEMA,
        "mode": mode,
        "start_ts_ms": start,
        "end_ts_ms": end,
        "flat_window_start": True,
        "primary_ids": dict(primary_ids),
        "health_basis": "SHADOW_OUTCOMES_AVAILABLE_STRICTLY_BEFORE_DECISION_WITHIN_THIS_WINDOW",
        "nominal_research_sleeve": SLEEVE_WEIGHT,
        "gross_research_cap": 1.0,
        "leverage": "NOT_APPLIED",
        "candidate_position_count": len(records),
        "outside_window_or_carryin_count": outside_window,
        "allocation_count": allocations,
        "closed_trade_count": len(allocated_rows),
        "no_allocation_count": no_allocation,
        "open_allocation_count": len(open_allocations),
        "peak_gross_weight": peak_gross,
        "end_reserved_weight": sum(row["weight"] for row in open_allocations),
        "allocated_rows": allocated_rows,
        "events": events,
        "open_allocations": open_allocations,
        "metrics": metrics,
        "state": (
            "HOLD_OPEN_ALLOCATION"
            if open_allocations
            else "RESEARCH_ALLOCATION_COMPLETE_NO_PROMOTION"
        ),
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
        "promotion_authority": False,
        "limitations": [
            "Market state is inherited from frozen native valid-signal rules; no additional optimized portfolio regime gate.",
            "An observed source block persists to this research window end; no source recovery is inferred.",
        ],
    }
