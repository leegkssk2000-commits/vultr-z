"""Frozen-calendar ledger diagnostics; never runs a strategy or grants promotion.

All intervals are UTC epoch milliseconds, start inclusive and end exclusive.
PnL is the additive sum of supplied, cost-checked trade bps, not NAV return.
Unknown exposure, incomplete input and bad identities fail closed. Historical
data is untouched only with an explicit pre-evaluation inspection receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DAY_MS = 86_400_000
SCHEMA = "zel.economic7.walkforward_calendar.v1"
EXPOSURES = {
    "OBSERVED_DEVELOPMENT",
    "UNTOUCHED_AT_REGISTRATION",
    "FRESH_FORWARD",
    "UNKNOWN",
}


def digest(value: Any) -> str:
    """Canonical JSON SHA-256; NaN/Infinity and non-JSON objects are rejected."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: finite number required")
    if not math.isfinite(value):
        raise ValueError(f"{field}: finite number required")
    return float(value)


def _stamp(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field}: nonnegative integer UTC epoch ms required")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: nonempty identity required")
    return value


def _sha(value: Any, field: str, lengths: tuple[int, ...] = (64,)) -> str:
    value = _text(value, field)
    if len(value) not in lengths or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{field}: full lowercase hexadecimal hash required")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field}: JSON object required")
    return value


def rolling_windows(
    *,
    start_ms: int,
    end_ms: int,
    train_days: int,
    oos_days: int,
    step_days: int | None = None,
    embargo_ms: int = 0,
    purge_ms: int = 0,
) -> list[dict[str, int | str]]:
    """Build a fixed calendar. Incomplete trailing windows are not manufactured."""
    _stamp(start_ms, "start_ms")
    _stamp(end_ms, "end_ms")
    step = oos_days if step_days is None else step_days
    for name, value in (
        ("train_days", train_days),
        ("oos_days", oos_days),
        ("step_days", step),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name}: positive integer required")
    if step < oos_days or end_ms <= start_ms:
        raise ValueError("invalid span or overlapping OOS windows")
    _stamp(embargo_ms, "embargo_ms")
    _stamp(purge_ms, "purge_ms")
    if purge_ms >= train_days * DAY_MS:
        raise ValueError("purge consumes train window")
    windows: list[dict[str, int | str]] = []
    cursor = start_ms
    while True:
        train_end = cursor + train_days * DAY_MS
        oos_start = train_end + embargo_ms
        oos_end = oos_start + oos_days * DAY_MS
        if oos_end > end_ms:
            break
        windows.append(
            {
                "window_id": f"W{len(windows) + 1:03d}",
                "train_start_ms": cursor,
                "train_end_ms": train_end,
                "oos_start_ms": oos_start,
                "oos_end_ms": oos_end,
                "embargo_ms": embargo_ms,
                "purge_ms": purge_ms,
            }
        )
        cursor += step * DAY_MS
    if not windows:
        raise ValueError("no complete rolling window")
    return windows


def _validate_calendar(calendar: Mapping[str, Any]) -> None:
    calendar = _mapping(calendar, "calendar")
    body = {k: v for k, v in calendar.items() if k != "calendar_sha256"}
    if calendar.get("schema") != SCHEMA or digest(body) != calendar.get(
        "calendar_sha256"
    ):
        raise ValueError("calendar hash/schema mismatch")
    for field in ("candidate_id", "source"):
        _text(calendar.get(field), field)
    _sha(calendar.get("rule_hash"), "rule_hash")
    _sha(calendar.get("code_sha"), "code_sha", (40, 64))
    for field in ("registered_at_ms", "written_at_ms"):
        _stamp(calendar.get(field), field)
    cost = _mapping(calendar.get("cost_authority"), "cost_authority")
    _text(cost.get("source"), "cost_authority.source")
    _sha(cost.get("sha256"), "cost_authority.sha256")
    if cost.get("equation") != "gross_minus_fee_minus_slippage_minus_funding":
        raise ValueError(
            "cost equation must explicitly include funding, including explicit zero"
        )
    manifest = _mapping(calendar.get("exposure_manifest"), "exposure_manifest")
    _text(manifest.get("source"), "exposure_manifest.source")
    _sha(manifest.get("sha256"), "exposure_manifest.sha256")
    _stamp(manifest.get("inspected_at_ms"), "exposure_manifest.inspected_at_ms")
    if manifest["inspected_at_ms"] > calendar["registered_at_ms"]:
        raise ValueError("inspection manifest postdates registration")
    intervals = manifest.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ValueError("explicit exposure intervals required")
    for interval in intervals:
        interval = _mapping(interval, "exposure interval")
        a = _stamp(interval.get("start_ms"), "exposure.start_ms")
        b = _stamp(interval.get("end_ms"), "exposure.end_ms")
        if b <= a or interval.get("exposure") not in EXPOSURES:
            raise ValueError("invalid exposure interval")
        _text(interval.get("receipt"), "exposure.receipt")
    windows = calendar.get("windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("explicit windows required")
    ids: set[str] = set()
    previous_end = -1
    previous_train = -1
    for window in windows:
        window = _mapping(window, "calendar window")
        identity = _text(window.get("window_id"), "window_id")
        if identity in ids:
            raise ValueError("duplicate window identity")
        ids.add(identity)
        a, b, c, d, embargo, purge = (
            _stamp(window.get(k), k)
            for k in (
                "train_start_ms",
                "train_end_ms",
                "oos_start_ms",
                "oos_end_ms",
                "embargo_ms",
                "purge_ms",
            )
        )
        if not a < b <= c < d or c < b + embargo or purge >= b - a:
            raise ValueError("invalid causal train/embargo/purge/OOS boundary")
        if c < previous_end or a <= previous_train:
            raise ValueError("OOS overlap or nonrolling train order")
        previous_end, previous_train = d, a


def preregister_calendar(
    path: str | Path,
    *,
    candidate_id: str,
    rule_hash: str,
    code_sha: str,
    source: str,
    exposure_manifest: Mapping[str, Any],
    cost_authority: Mapping[str, Any],
    windows: Sequence[Mapping[str, Any]],
    registered_at_ms: int | None = None,
) -> dict[str, Any]:
    """Exclusively create a hash-bound registration before reading result ledgers.

    A caller-provided older registration cannot backdate the actual write time.
    Existing files are never replaced; use their receipt to resume evaluations.
    """
    now = time.time_ns() // 1_000_000
    calendar: dict[str, Any] = {
        "schema": SCHEMA,
        "candidate_id": candidate_id,
        "rule_hash": rule_hash,
        "code_sha": code_sha,
        "source": source,
        "registered_at_ms": now if registered_at_ms is None else registered_at_ms,
        "written_at_ms": now,
        "timezone": "UTC",
        "windows": list(windows),
        "exposure_manifest": dict(exposure_manifest),
        "cost_authority": dict(cost_authority),
    }
    calendar["calendar_sha256"] = digest(calendar)
    _validate_calendar(calendar)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(calendar, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        import os

        os.fsync(handle.fileno())
    return calendar


def _covered(start: int, end: int, intervals: Iterable[Mapping[str, Any]]) -> bool:
    cursor = start
    for item in sorted(intervals, key=lambda v: v["start_ms"]):
        if item["end_ms"] <= cursor:
            continue
        if item["start_ms"] > cursor:
            return False
        cursor = max(cursor, item["end_ms"])
        if cursor >= end:
            return True
    return False


def _exposure(calendar: Mapping[str, Any], start: int, end: int) -> str:
    manifest = calendar["exposure_manifest"]
    touched = [
        x for x in manifest["intervals"] if x["start_ms"] < end and x["end_ms"] > start
    ]
    if any(x["exposure"] == "OBSERVED_DEVELOPMENT" for x in touched):
        return "HISTORICAL_DEVELOPMENT"
    if manifest.get("inspection_inventory_complete") is not True:
        return "UNKNOWN_HOLD"
    if not _covered(start, end, touched) or any(
        x["exposure"] == "UNKNOWN" for x in touched
    ):
        return "UNKNOWN_HOLD"
    effective_registration = max(
        calendar["registered_at_ms"], calendar["written_at_ms"]
    )
    if all(x["exposure"] == "FRESH_FORWARD" for x in touched):
        return "FRESH_FORWARD" if start >= effective_registration else "UNKNOWN_HOLD"
    if all(x["exposure"] == "UNTOUCHED_AT_REGISTRATION" for x in touched):
        return "DECLARED_UNTOUCHED_OOS"
    return "UNKNOWN_HOLD"


def _trade(record: Mapping[str, Any], calendar: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(record)
    if out.get("instrument_kind") != "SINGLE_LEG_LINEAR_USDT":
        raise ValueError(
            "explicit single-leg contract required; multileg needs a two-leg adapter"
        )
    for field in ("trade_id", "strategy", "symbol", "source"):
        _text(out.get(field), field)
    for field in ("candidate_id", "rule_hash", "code_sha"):
        if out.get(field) != calendar[field]:
            raise ValueError(f"{field}: ledger/calendar identity mismatch")
    if out.get("side") not in ("LONG", "SHORT"):
        raise ValueError("side: LONG/SHORT required")
    out["entry_ts_ms"] = _stamp(out.get("entry_ts_ms"), "entry_ts_ms")
    if _number(out.get("entry_price"), "entry_price") <= 0:
        raise ValueError("entry_price must be positive")
    if out.get("status") in ("OPEN", "CENSORED"):
        if out.get("exit_ts_ms") is not None or out.get("exit_price") is not None:
            raise ValueError("OPEN/CENSORED may not masquerade as closed trade")
        return out
    if out.get("status") != "CLOSED":
        raise ValueError("explicit CLOSED/OPEN/CENSORED status required")
    out["exit_ts_ms"] = _stamp(out.get("exit_ts_ms"), "exit_ts_ms")
    out["outcome_available_at_ms"] = _stamp(
        out.get("outcome_available_at_ms"), "outcome_available_at_ms"
    )
    if out["outcome_available_at_ms"] < out["exit_ts_ms"]:
        raise ValueError("outcome availability predates exit")
    if out["exit_ts_ms"] < out["entry_ts_ms"]:
        raise ValueError("exit predates entry")
    if _number(out.get("exit_price"), "exit_price") <= 0:
        raise ValueError("exit_price must be positive")
    for field in (
        "gross_bps",
        "fee_bps",
        "slippage_bps",
        "funding_bps",
        "net_bps",
        "pnl_weight",
    ):
        out[field] = _number(out.get(field), field)
    if min(out["fee_bps"], out["slippage_bps"]) < 0 or out["pnl_weight"] <= 0:
        raise ValueError("negative costs or nonpositive executed risk weight")
    if out.get("cost_authority_sha256") != calendar["cost_authority"]["sha256"]:
        raise ValueError("cost authority mismatch")
    gross = (out["exit_price"] / out["entry_price"] - 1) * 10_000
    gross *= (1 if out["side"] == "LONG" else -1) * out["pnl_weight"]
    if not math.isclose(out["gross_bps"], gross, rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("gross/price/side/weight mismatch")
    expected = (
        out["gross_bps"] - out["fee_bps"] - out["slippage_bps"] - out["funding_bps"]
    )
    if not math.isclose(out["net_bps"], expected, rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("gross-fee-slippage-funding != net")
    return out


def _month_keys(intervals: Sequence[tuple[int, int]]) -> list[str]:
    keys: set[str] = set()
    for start, end in intervals:
        current = datetime.fromtimestamp(start / 1000, timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        while int(current.timestamp() * 1000) < end:
            keys.add(current.strftime("%Y-%m"))
            current = current.replace(
                year=current.year + (current.month == 12), month=current.month % 12 + 1
            )
    return sorted(keys)


def _share(values: Iterable[float]) -> float | None:
    positive = [max(x, 0.0) for x in values]
    return max(positive) / sum(positive) if positive and sum(positive) > 0 else None


def _correlation(
    records: Sequence[Mapping[str, Any]], intervals: Sequence[tuple[int, int]]
) -> dict[str, float | None]:
    days = sorted(
        {
            day
            for start, end in intervals
            for day in range(start // DAY_MS, (end - 1) // DAY_MS + 1)
        }
    )
    strategies = sorted({str(x["strategy"]) for x in records})
    daily: dict[str, dict[int, float]] = {s: defaultdict(float) for s in strategies}
    for row in records:
        daily[row["strategy"]][row["exit_ts_ms"] // DAY_MS] += row["net_bps"]
    result: dict[str, float | None] = {}
    for i, left in enumerate(strategies):
        for right in strategies[i + 1 :]:
            x, y = [daily[left][d] for d in days], [daily[right][d] for d in days]
            if len(days) < 2:
                result[f"{left}|{right}"] = None
                continue
            mx, my = sum(x) / len(x), sum(y) / len(y)
            vx, vy = sum((v - mx) ** 2 for v in x), sum((v - my) ** 2 for v in y)
            result[f"{left}|{right}"] = (
                sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(vx * vy)
                if vx and vy
                else None
            )
    return result


def _metrics(
    records: Sequence[Mapping[str, Any]], intervals: Sequence[tuple[int, int]]
) -> dict[str, Any]:
    days = sum(end - start for start, end in intervals) / DAY_MS
    ordered = sorted(records, key=lambda r: (r["exit_ts_ms"], r["trade_id"]))
    nets = [float(r["net_bps"]) for r in ordered]
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x < 0]
    total, count = sum(nets), len(nets)
    months: dict[str, dict[str, Any]] = {
        key: {"T": 0, "net_bps": 0.0} for key in _month_keys(intervals)
    }
    symbols: dict[str, float] = defaultdict(float)
    exits: dict[int, list[float]] = defaultdict(list)
    for row in ordered:
        month = datetime.fromtimestamp(row["exit_ts_ms"] / 1000, timezone.utc).strftime(
            "%Y-%m"
        )
        months[month]["T"] += 1
        months[month]["net_bps"] += row["net_bps"]
        symbols[row["symbol"]] += row["net_bps"]
        exits[row["exit_ts_ms"]].append(row["net_bps"])
    equity = peak = dd = 0.0
    longest = ending_losses = 0
    tie_ambiguity = False
    for ts in sorted(exits):
        group = exits[ts]
        equity += sum(group)
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        loss_count = sum(x < 0 for x in group)
        breakers = len(group) - loss_count
        longest = max(longest, ending_losses + loss_count)
        ending_losses = loss_count if breakers else ending_losses + loss_count
        tie_ambiguity |= bool(loss_count and breakers)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    monthly_net = [float(x["net_bps"]) for x in months.values()]

    def avg(key: str) -> float | None:
        return sum(float(r[key]) for r in ordered) / count if count else None

    return {
        "unit": "additive_trade_bps_not_portfolio_NAV",
        "calendar_days": days,
        "T": count,
        "T_per_day": count / days,
        "WR": len(wins) / count if count else None,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "payoff": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None,
        "gross_bps_per_T": avg("gross_bps"),
        "fee_bps_per_T": avg("fee_bps"),
        "slippage_bps_per_T": avg("slippage_bps"),
        "funding_bps_per_T": avg("funding_bps"),
        "cost_bps_per_T": (
            sum(r["fee_bps"] + r["slippage_bps"] + r["funding_bps"] for r in ordered)
            / count
            if count
            else None
        ),
        "net_bps": total,
        "net_bps_per_T": total / count if count else None,
        "PF": sum(wins) / abs(sum(losses)) if losses else None,
        "DD_bps": dd if count else None,
        "max_loss_streak": longest if count else None,
        "loss_streak_is_upper_bound_due_to_simultaneous_exits": tie_ambiguity,
        "EdgeDensity_bps_per_day": total / days if count else None,
        "monthly": months,
        "positive_month_ratio": sum(x > 0 for x in monthly_net) / len(months),
        "symbol_net_bps": dict(sorted(symbols.items())),
        "symbol_positive_net_concentration": _share(symbols.values()),
        "month_positive_net_concentration": _share(monthly_net),
        "single_winner_share_of_winning_bps": _share(wins),
        "single_winner_share_of_net": max(wins) / total if wins and total > 0 else None,
        "net_without_best_trade_bps": total - max(wins) if wins else None,
        "net_without_best_symbol_bps": (
            total - max(symbols.values()) if symbols else None
        ),
        "net_without_best_month_bps": total - max(monthly_net) if monthly_net else None,
        "strategy_daily_net_correlation": _correlation(ordered, intervals),
    }


def _gates(
    metrics: Mapping[str, Any] | None, thresholds: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, Any]]:
    """Check only caller-supplied SSOT thresholds. These never imply Core PASS."""
    results: list[dict[str, Any]] = []
    for gate in thresholds or []:
        if not isinstance(gate, Mapping):
            results.append(
                {
                    "verdict": "HOLD",
                    "value": None,
                    "error": "threshold JSON object required",
                }
            )
            continue
        item = dict(gate)
        item["verdict"] = "HOLD"
        value = metrics.get(str(gate.get("metric"))) if metrics else None
        item["value"] = value
        try:
            _text(gate.get("source"), "threshold.source")
            _sha(gate.get("source_sha256"), "threshold.source_sha256")
            _text(gate.get("unit"), "threshold.unit")
            limit = _number(gate.get("limit"), "threshold.limit")
            actual = _number(value, "metric")
            comparisons = {
                ">": actual > limit,
                ">=": actual >= limit,
                "<": actual < limit,
                "<=": actual <= limit,
            }
            if gate.get("operator") not in comparisons:
                raise ValueError("unknown threshold operator")
            item["verdict"] = "PASS" if comparisons[gate["operator"]] else "FAIL"
        except (ValueError, TypeError):
            pass
        results.append(item)
    return results


def evaluate_ledger(
    calendar: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    evaluated_at_ms: int,
    ledger_manifest: Mapping[str, Any],
    thresholds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read frozen-rule events, purge causal overlaps and report calendar metrics.

    Required ledger manifest: records_sha256, source, complete, start_ms, end_ms,
    record_count, candidate_id, rule_hash, code_sha. Completion is an explicit
    producer assertion, not inferred from the first or last trade timestamp.
    Open/censored trades remain separate. No synthetic exits or zero costs.
    """
    report: dict[str, Any] = {
        "schema": "zel.economic7.walkforward_report.v1",
        "state": "HOLD",
        "promotion_authority": "BLOCKED",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
        "calendar_sha256": (
            calendar.get("calendar_sha256") if isinstance(calendar, Mapping) else None
        ),
        "evaluated_at_ms": evaluated_at_ms,
        "windows": [],
        "metrics": None,
        "errors": [],
        "promotion_blockers": [],
    }
    try:
        _validate_calendar(calendar)
        ledger_manifest = _mapping(ledger_manifest, "ledger_manifest")
        _stamp(evaluated_at_ms, "evaluated_at_ms")
        if evaluated_at_ms < max(
            calendar["registered_at_ms"], calendar["written_at_ms"]
        ):
            raise ValueError("evaluation predates durable registration")
        _text(ledger_manifest.get("source"), "ledger.source")
        if ledger_manifest.get("records_sha256") != digest(records):
            raise ValueError("ledger hash mismatch")
        if ledger_manifest.get("record_count") != len(records):
            raise ValueError("ledger record count mismatch")
        for field in ("candidate_id", "rule_hash", "code_sha"):
            if ledger_manifest.get(field) != calendar[field]:
                raise ValueError(f"ledger manifest {field} mismatch")
        start = _stamp(ledger_manifest.get("start_ms"), "ledger.start_ms")
        end = _stamp(ledger_manifest.get("end_ms"), "ledger.end_ms")
        if end <= start or end > evaluated_at_ms:
            raise ValueError("invalid ledger coverage timestamps")
        report["ledger_sha256"] = ledger_manifest["records_sha256"]
        report["exposure_manifest"] = calendar["exposure_manifest"]
    except (ValueError, TypeError, KeyError) as exc:
        report["errors"].append(str(exc))
        return report
    valid: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, record in enumerate(records):
        try:
            row = _trade(record, calendar)
            identity = (row["strategy"], row["symbol"], row["trade_id"])
            if identity in seen:
                raise ValueError("duplicate trade identity")
            seen.add(identity)
            if row["entry_ts_ms"] >= end or (
                row["status"] == "CLOSED" and row["exit_ts_ms"] >= end
            ):
                raise ValueError("ledger trade beyond declared coverage")
            if (
                row["status"] == "CLOSED"
                and row["outcome_available_at_ms"] > evaluated_at_ms
            ):
                raise ValueError("outcome unavailable at evaluation timestamp")
            valid.append(row)
        except (ValueError, TypeError, KeyError) as exc:
            report["errors"].append(f"record[{index}]: {exc}")
    report["invalid_record_count"] = len(records) - len(valid)
    pooled: list[dict[str, Any]] = []
    intervals: list[tuple[int, int]] = []
    for window in calendar["windows"]:
        a, b = window["oos_start_ms"], window["oos_end_ms"]
        exposure = _exposure(calendar, a, b)
        issues: list[str] = []
        if report["errors"]:
            issues.append("LEDGER_INTEGRITY_FAILURE")
        if (
            ledger_manifest.get("complete") is not True
            or start > window["train_start_ms"]
            or end < b
        ):
            issues.append("INCOMPLETE_DECLARED_CALENDAR_COVERAGE")
        if evaluated_at_ms < b:
            issues.append("OOS_WINDOW_NOT_FINISHED")
        if exposure == "UNKNOWN_HOLD":
            issues.append("EXPOSURE_UNKNOWN")
        train_end = window["train_end_ms"] - window["purge_ms"]
        train = [
            r
            for r in valid
            if window["train_start_ms"] <= r["entry_ts_ms"] < train_end
            and r["status"] == "CLOSED"
            and r["exit_ts_ms"] <= train_end
            and r["outcome_available_at_ms"] <= train_end
        ]
        train_purged = [
            r
            for r in valid
            if window["train_start_ms"] <= r["entry_ts_ms"] < window["train_end_ms"]
            and r not in train
        ]
        closed = [
            r
            for r in valid
            if a <= r["entry_ts_ms"] < b
            and r["status"] == "CLOSED"
            and r["exit_ts_ms"] < b
        ]
        censored = [
            r
            for r in valid
            if a <= r["entry_ts_ms"] < b
            and (r["status"] != "CLOSED" or r["exit_ts_ms"] >= b)
        ]
        boundary = [
            r
            for r in valid
            if r["entry_ts_ms"] < a
            and (r["status"] != "CLOSED" or r["exit_ts_ms"] >= a)
        ]
        metric = _metrics(closed, [(a, b)]) if not issues else None
        if boundary:
            issues.append("CARRY_IN_EXPOSURE_EXCLUDED_FROM_PURGED_DIAGNOSTICS")
        if metric is not None:
            metric["coverage_status"] = (
                "PURGED_BOUNDARY_SUBSET_NOT_PORTFOLIO"
                if boundary
                else "CLOSED_TRADE_DIAGNOSTICS"
            )
        report["windows"].append(
            {
                "window_id": window["window_id"],
                "calendar": dict(window),
                "exposure": exposure,
                "state": (
                    "HOLD"
                    if issues or censored or not closed
                    else "DIAGNOSTIC_COMPLETE"
                ),
                "issues": issues,
                "train_eligible_ids": [r["trade_id"] for r in train],
                "train_purged_ids": [r["trade_id"] for r in train_purged],
                "oos_closed_ids": [r["trade_id"] for r in closed],
                "oos_censored_ids": [r["trade_id"] for r in censored],
                "boundary_overlap_ids": [r["trade_id"] for r in boundary],
                "metrics": metric,
                "gates": _gates(metric, thresholds),
            }
        )
        pooled.extend(closed)
        intervals.append((a, b))
    if all(w["metrics"] is not None for w in report["windows"]):
        report["metrics"] = _metrics(pooled, intervals)
        report["metrics"]["coverage_status"] = (
            "PURGED_BOUNDARY_SUBSET_NOT_PORTFOLIO"
            if any(w["boundary_overlap_ids"] for w in report["windows"])
            else "CLOSED_TRADE_DIAGNOSTICS"
        )
        if all(w["state"] == "DIAGNOSTIC_COMPLETE" for w in report["windows"]):
            report["state"] = "DIAGNOSTIC_COMPLETE"
    report["cost_authority_status"] = (
        "CALLER_ASSERTED_HASH_BOUND_COSTS_EXECUTION_CALIBRATION_NOT_VERIFIED"
    )
    report["gates"] = _gates(report["metrics"], thresholds)
    window_nets = [
        float(w["metrics"]["net_bps"])
        for w in report["windows"]
        if w["metrics"] is not None
    ]
    report["rolling_summary"] = {
        "registered_windows": len(report["windows"]),
        "measured_windows": len(window_nets),
        "positive_windows": sum(x > 0 for x in window_nets),
        "positive_window_ratio": sum(x > 0 for x in window_nets)
        / len(report["windows"]),
        "window_positive_net_concentration": _share(window_nets),
        "net_without_best_window_bps": (
            sum(window_nets) - max(window_nets) if window_nets else None
        ),
    }
    report["fresh_closed_T"] = sum(
        len(w["oos_closed_ids"])
        for w in report["windows"]
        if w["exposure"] == "FRESH_FORWARD" and w["metrics"] is not None
    )
    report["promotion_blockers"] = [
        "SEPARATE_PORTFOLIO_MARGINAL_VALUE_AND_EXECUTION_EVIDENCE_REQUIRED"
    ]
    if not thresholds:
        report["promotion_blockers"].append("SSOT_NUMERIC_BUDGETS_NOT_SUPPLIED")
    if any(
        w["exposure"] in ("HISTORICAL_DEVELOPMENT", "UNKNOWN_HOLD")
        for w in report["windows"]
    ):
        report["promotion_blockers"].append(
            "DEVELOPMENT_OR_UNKNOWN_HISTORY_IS_NOT_FRESH_OOS"
        )
    if not report["fresh_closed_T"]:
        report["promotion_blockers"].append("NO_FRESH_FORWARD_CLOSED_EVIDENCE")
    metric = report["metrics"]
    if metric and metric["net_bps"] > 0:
        if report["rolling_summary"]["net_without_best_window_bps"] <= 0:
            report["promotion_blockers"].append("SINGLE_WINDOW_DEPENDENCE")
        for key in ("trade", "symbol", "month"):
            remaining = metric[f"net_without_best_{key}_bps"]
            if remaining is not None and remaining <= 0:
                report["promotion_blockers"].append(f"SINGLE_{key.upper()}_DEPENDENCE")
    report["report_sha256"] = digest(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument(
        "--ledger",
        type=Path,
        required=True,
        help="JSON object with records and manifest",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path)
    args = parser.parse_args()
    calendar = json.loads(args.calendar.read_text())
    payload = json.loads(args.ledger.read_text())
    thresholds = json.loads(args.thresholds.read_text()) if args.thresholds else None
    report = evaluate_ledger(
        calendar,
        payload["records"],
        evaluated_at_ms=time.time_ns() // 1_000_000,
        ledger_manifest=payload["manifest"],
        thresholds=thresholds,
    )
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
