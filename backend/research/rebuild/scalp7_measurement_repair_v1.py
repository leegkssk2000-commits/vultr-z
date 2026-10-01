"""Data-only continuity and measurement boundaries; no strategy or economic runner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

MINUTE = 60_000
DAY = 86_400_000
AUTHORITY = {
    "new_full_runs": 0,
    "live": "BLOCKED",
    "orders": "BLOCKED",
    "promotion": False,
}


def clock_coverage(
    symbol: str, timestamps: Iterable[int], start: int, end: int
) -> dict[str, Any]:
    if start >= end or start % MINUTE or end % MINUTE:
        raise ValueError("ALIGNED_HALF_OPEN_RANGE_REQUIRED")
    spans, gaps = [], []
    expected, span_start, count = start, None, 0
    for stamp in timestamps:
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp % MINUTE:
            raise ValueError("ALIGNED_INTEGER_MINUTE_REQUIRED")
        if stamp < expected or stamp >= end:
            raise ValueError("DUPLICATE_REVERSED_OR_OUTSIDE_TIMESTAMP")
        if stamp != expected:
            if span_start is not None:
                spans.append({"start_ts_ms": span_start, "end_ts_ms": expected})
            gaps.append(
                {
                    "start_ts_ms": expected,
                    "end_ts_ms": stamp,
                    "missing_minutes": (stamp - expected) // MINUTE,
                }
            )
            span_start = None
        if span_start is None:
            span_start = stamp
        expected, count = stamp + MINUTE, count + 1
    if span_start is not None:
        spans.append({"start_ts_ms": span_start, "end_ts_ms": expected})
    if expected < end:
        gaps.append(
            {
                "start_ts_ms": expected,
                "end_ts_ms": end,
                "missing_minutes": (end - expected) // MINUTE,
            }
        )
    return {
        "symbol": symbol,
        "start_ts_ms": start,
        "end_ts_ms": end,
        "observed_minutes": count,
        "gaps": gaps,
        "continuous_spans": spans,
    }


def continuous_contract(
    coverage: Sequence[Mapping[str, Any]],
    source_refs: Sequence[Mapping[str, str]],
    *,
    warmup_ms: int = 90 * DAY,
    decision_minutes: int = 30,
) -> dict[str, Any]:
    if not coverage or not source_refs or warmup_ms < 0 or warmup_ms % MINUTE:
        raise ValueError("EXPLICIT_SOURCE_COVERAGE_AND_ALIGNED_CONTEXT_REQUIRED")
    symbols = [c["symbol"] for c in coverage]
    if len(set(symbols)) != len(symbols) or decision_minutes <= 0:
        raise ValueError("DISTINCT_SYMBOLS_AND_POSITIVE_GRID_REQUIRED")
    for ref in source_refs:
        digest = ref.get("sha256", "")
        if (
            not ref.get("path")
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("HASH_BOUND_SOURCE_REQUIRED")
    common = [
        (s["start_ts_ms"], s["end_ts_ms"]) for s in coverage[0]["continuous_spans"]
    ]
    for item in coverage[1:]:
        common = [
            (max(a, s["start_ts_ms"]), min(b, s["end_ts_ms"]))
            for a, b in common
            for s in item["continuous_spans"]
            if max(a, s["start_ts_ms"]) < min(b, s["end_ts_ms"])
        ]
    grid = decision_minutes * MINUTE
    rows = []
    for index, (start, end) in enumerate(sorted(common)):
        scored_start = ((start + warmup_ms + grid - 1) // grid) * grid
        scored_end = (end // grid) * grid
        rows.append(
            {
                "segment_id": f"common_contiguous_{index+1}",
                "raw_start_ts_ms": start,
                "raw_end_ts_ms": end,
                "context_start_ts_ms": start,
                "evaluation_start_ts_ms": scored_start,
                "evaluation_end_ts_ms": scored_end,
                "eligible_by_data_only": scored_start < scored_end,
                "exclusion": (
                    None
                    if scored_start < scored_end
                    else "INSUFFICIENT_UNIFORM_CONTEXT"
                ),
                "evaluation_minutes": max(0, (scored_end - scored_start) // MINUTE),
                "initial_state": "SEPARATE_RESEARCH_ACCOUNT_FLAT_NOT_CLOSURE_OF_OLD_OWNERS",
            }
        )
    contract = {
        "schema": "scalp7.measurement.continuous_common_data.v1",
        "symbols": sorted(symbols),
        "source_refs": list(source_refs),
        "coverage": list(coverage),
        "segments": rows,
        "uniform_selection_rule": "ALL_COMMON_CONTIGUOUS_SPANS_WITH_SAME_CONTEXT_AND_GRID",
        "warmup_ms": warmup_ms,
        "decision_minutes": decision_minutes,
        "strategy_or_profit_used_for_selection": False,
        "gap_fill": "FORBIDDEN",
        "cross_segment_nav_aggregation": "FORBIDDEN",
        "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE",
        "execution_status": "NOT_RUN_REQUIRES_NEW_IDENTITIES_AND_NEW_FULL_APPROVAL",
        "authority": dict(AUTHORITY),
    }
    contract["contract_sha256"] = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return contract


def adapt_segment_details(
    rows: Iterable[Mapping[str, Any]],
    contract: Mapping[str, Any],
    segment_id: str,
    symbol: str,
) -> list[dict[str, Any]]:
    unsigned = {k: v for k, v in contract.items() if k != "contract_sha256"}
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != contract.get("contract_sha256"):
        raise ValueError("CONTINUOUS_CONTRACT_HASH_MISMATCH")
    if symbol not in contract["symbols"]:
        raise ValueError("SYMBOL_OUTSIDE_COMMON_CONTRACT")
    segment = next(
        (r for r in contract["segments"] if r["segment_id"] == segment_id), None
    )
    if segment is None or not segment["eligible_by_data_only"]:
        raise ValueError("ELIGIBLE_COMMON_SEGMENT_REQUIRED")
    start, end = segment["raw_start_ts_ms"], segment["raw_end_ts_ms"]
    selected = [dict(r) for r in rows if start <= r["open_ts_ms"] < end]
    clock = clock_coverage(symbol, (r["open_ts_ms"] for r in selected), start, end)
    if clock["gaps"]:
        raise ValueError("INPUT_DOES_NOT_MEET_CONTINUOUS_SEGMENT_CONTRACT")
    for row in selected:
        if row["symbol"] != symbol or row["close_ts_ms"] != row["open_ts_ms"] + MINUTE:
            raise ValueError("MINUTE_SYMBOL_OR_DURATION_MISMATCH")
        if row["available_ts_ms"] < row["close_ts_ms"]:
            raise ValueError("NONCAUSAL_AVAILABILITY")
        row["parent_segment_id"] = row.get("segment_id")
        row["segment_id"] = (
            "measurement:" + contract["contract_sha256"] + ":" + segment_id
        )
    return selected


def unknown_executions(
    executions: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    return [
        e
        for e in executions
        if e.get("state", e.get("status")) == "UNRESOLVED"
        or e.get("unresolved") is True
    ]


def followup_admission(
    executions: Sequence[Mapping[str, Any]], symbol: str
) -> dict[str, Any]:
    owners = []
    for e in executions:
        order = e.get("order", {})
        position = e.get("position") or e.get("unclosed_position") or {}
        owner_symbol = order.get("symbol") or e.get("symbol")
        if owner_symbol is None and position.get("episode"):
            owner_symbol = position["episode"].split(":")[-2]
        if owner_symbol == symbol and (e in unknown_executions([e]) or position):
            owners.append(
                order.get("position_episode_id", position.get("episode", symbol))
            )
    return {
        "symbol": symbol,
        "allowed": not owners,
        "retained_owners": owners,
        "reason": (
            "EXISTING_UNRESOLVED_OR_OPEN_OWNERSHIP" if owners else "NO_EXISTING_OWNER"
        ),
        "synthetic_close_created": False,
    }


def window_measurement_status(
    window: Mapping[str, Any],
    executions: Sequence[Mapping[str, Any]],
    snapshot_times: Sequence[int],
    episodes: Sequence[Mapping[str, Any]],
    *,
    expected_snapshot_times: Sequence[int] | None = None,
) -> dict[str, Any]:
    start, end = window["start_ts_ms"], window["end_ts_ms"]
    unknown = unknown_executions(executions)
    crossing = [
        e
        for e in episodes
        if start <= e["entry_ts_ms"] < end
        and (not e["closed"] or e["outcome_available_ts_ms"] >= end)
    ]
    carried = [
        e
        for e in episodes
        if e["entry_ts_ms"] < start
        and (not e["closed"] or e["outcome_available_ts_ms"] >= start)
    ]
    affected = [e for e in unknown if e.get("unresolved_from_ts_ms", 0) < end]
    cutoff = min((e.get("unresolved_observed_ts_ms", 0) for e in unknown), default=None)
    expected = list(expected_snapshot_times or [])
    if expected and (
        expected != sorted(set(expected)) or expected[0] != start or expected[-1] != end
    ):
        raise ValueError("EXPLICIT_ORDERED_WINDOW_SNAPSHOT_GRID_REQUIRED")
    missing = sorted(set(expected) - set(snapshot_times))
    covered = bool(expected) and not missing
    nav_complete = covered and (cutoff is None or cutoff > end)
    return {
        "cohort_complete": not (crossing or carried or affected),
        "cohort_crossing_count": len(crossing),
        "cohort_carry_in_count": len(carried),
        "cohort_unknown_affected_count": len(affected),
        "sampled_reference_nav_path_complete": nav_complete,
        "expected_snapshot_grid_supplied": bool(expected),
        "missing_expected_snapshot_count": len(missing) if expected else None,
        "missing_expected_snapshot_first_ts_ms": missing[0] if missing else None,
        "first_unknown_observed_ts_ms": cutoff,
        "path_status": (
            "KNOWN_REFERENCE_PRICE_PATH" if nav_complete else "PREFIX_OR_MISSING_PATH"
        ),
        "funding_status": "UNKNOWN_NOT_ZERO",
        "actual_account_net": None,
        "cohort_incompleteness_is_not_itself_a_physical_data_gap": True,
    }


def value_trusted_prefix(
    ledger: Sequence[Mapping[str, Any]],
    prices: Sequence[Mapping[str, Any]],
    executions: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    start_ts_ms: int,
    expected_snapshot_times: Sequence[int] | None = None,
) -> dict[str, Any]:
    from backend.research.rebuild.scalp7_exact25_execution_v1 import (
        account_snapshots_from_ledger,
    )

    unknown = unknown_executions(executions)
    cutoff = min((e.get("unresolved_observed_ts_ms", 0) for e in unknown), default=None)
    trusted = [p for p in prices if cutoff is None or p["ts_ms"] < cutoff]
    account = None
    if trusted:
        last = trusted[-1]["ts_ms"]
        account = account_snapshots_from_ledger(
            [r for r in ledger if r["ts_ms"] <= last],
            trusted,
            initial_cash_usdt=initial_cash,
            start_ts_ms=start_ts_ms,
            price_basis="LAST_PRICE",
        )
    expected = list(expected_snapshot_times or [])
    if expected and (expected != sorted(set(expected)) or expected[0] != start_ts_ms):
        raise ValueError("EXPLICIT_ORDERED_SNAPSHOT_GRID_REQUIRED")
    missing = sorted(set(expected) - {p["ts_ms"] for p in trusted})
    full = not unknown and bool(expected) and not missing
    return {
        "account": account,
        "first_unknown_observed_ts_ms": cutoff,
        "full_reference_nav_available": full,
        "missing_expected_snapshot_count": len(missing) if expected else None,
        "terminal_after_gap_nav": (
            None
            if not full
            else (account["valuation"]["curve"][-1]["equity_usdt"] if account else None)
        ),
        "ownership": "RETAINED_NO_SYNTHETIC_CLOSE",
        "funding_status": "UNKNOWN_NOT_ZERO",
        "new_full_runs": 0,
        "authority": dict(AUTHORITY),
    }


def sampled_nav_dd(
    curve: Sequence[Mapping[str, Any]],
    window: Mapping[str, Any],
    executions: Sequence[Mapping[str, Any]],
    episodes: Sequence[Mapping[str, Any]],
    *,
    expected_snapshot_times: Sequence[int],
) -> float | None:
    """Saved-curve arithmetic, independent of closed-entry-cohort completeness."""
    from decimal import Decimal

    status = window_measurement_status(
        window,
        executions,
        [r["ts_ms"] for r in curve],
        episodes,
        expected_snapshot_times=expected_snapshot_times,
    )
    if not status["sampled_reference_nav_path_complete"]:
        return None
    wanted = set(expected_snapshot_times)
    samples = [r for r in curve if r["ts_ms"] in wanted]
    if [r["ts_ms"] for r in samples] != list(expected_snapshot_times):
        raise ValueError("DUPLICATE_OR_REVERSED_NAV_SAMPLE")
    values = [Decimal(str(r["equity_usdt"])) for r in samples]
    if any(not value.is_finite() for value in values) or values[0] <= 0:
        raise ValueError("FINITE_EQUITY_AND_POSITIVE_INITIAL_NAV_REQUIRED")
    peak, worst = values[0], Decimal(0)
    for value in values:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak * 100)
    return float(worst)
