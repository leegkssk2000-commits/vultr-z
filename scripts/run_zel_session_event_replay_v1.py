#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

BAR_MS = 900_000
HOUR_MS = 3_600_000
ROLLING_BARS = 96
SAFETY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "protected_mutations": 0,
}


@dataclass(frozen=True)
class Bar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"NON_FINITE_BAR:{self.ts}")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError(f"INVALID_OHLC_ENVELOPE:{self.ts}")
        if self.low > self.high or self.volume < 0:
            raise ValueError(f"INVALID_BAR:{self.ts}")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    previous_ts: int | None = None
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
        if set(reader.fieldnames or []) != required:
            raise ValueError(f"UNEXPECTED_HEADER:{path}")
        for row in reader:
            bar = Bar(
                ts=int(row["timestamp_ms"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            bar.validate()
            if previous_ts is not None and bar.ts - previous_ts != BAR_MS:
                raise ValueError(f"TIMESTAMP_DISCONTINUITY:{path}:{previous_ts}->{bar.ts}")
            previous_ts = bar.ts
            bars.append(bar)
    if len(bars) <= ROLLING_BARS + 20:
        raise ValueError(f"INSUFFICIENT_BARS:{path}:{len(bars)}")
    return bars


def percentile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def direction(bar: Bar) -> int:
    return 1 if bar.close > bar.open else -1 if bar.close < bar.open else 0


def true_range(bar: Bar, previous_close: float) -> float:
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))


def parse_session_minutes(plan: dict[str, Any]) -> list[int]:
    for row in plan.get("pre_registered_axes", []):
        if isinstance(row, dict) and row.get("axis") == "UTC_SESSION_TRANSITION":
            result: list[int] = []
            for raw in row.get("windows_utc", []):
                hour, minute = map(int, str(raw).split(":"))
                result.append(hour * 60 + minute)
            if not result:
                raise ValueError("SESSION_WINDOWS_EMPTY")
            return result
    raise ValueError("SESSION_AXIS_PLAN_MISSING")


def circular_minute_distance(left: int, right: int) -> int:
    delta = abs(left - right) % 1440
    return min(delta, 1440 - delta)


def in_session_window(signal_close_ts: int, session_minutes: list[int], window_minutes: int) -> bool:
    dt = datetime.fromtimestamp(signal_close_ts / 1000.0, tz=timezone.utc)
    minute = dt.hour * 60 + dt.minute
    return any(circular_minute_distance(minute, anchor) <= window_minutes for anchor in session_minutes)


def completed_hour_direction(bars_by_ts: dict[int, Bar], signal_close_ts: int) -> int:
    hour_end = (signal_close_ts // HOUR_MS) * HOUR_MS
    hour_start = hour_end - HOUR_MS
    hour = [bars_by_ts.get(hour_start + offset * BAR_MS) for offset in range(4)]
    if any(bar is None for bar in hour):
        return 0
    first = hour[0]
    last = hour[-1]
    assert first is not None and last is not None
    return 1 if last.close > first.open else -1 if last.close < first.open else 0


def event_mask(axis: str, bars: list[Bar], plan: dict[str, Any]) -> tuple[list[bool], list[int], list[dict[str, Any]]]:
    session_minutes = parse_session_minutes(plan)
    session_window = next(
        int(row["event_window_minutes"])
        for row in plan["pre_registered_axes"]
        if row.get("axis") == "UTC_SESSION_TRANSITION"
    )
    bars_by_ts = {bar.ts: bar for bar in bars}
    tr_values = [
        true_range(bar, bars[index - 1].close if index else bar.close)
        for index, bar in enumerate(bars)
    ]
    mask = [False] * len(bars)
    sides = [0] * len(bars)
    diagnostics: list[dict[str, Any]] = [{} for _ in bars]
    for index in range(ROLLING_BARS, len(bars)):
        bar = bars[index]
        side = direction(bar)
        if side == 0:
            continue
        prior_tr = tr_values[index - ROLLING_BARS:index]
        prior_volume = [item.volume for item in bars[index - ROLLING_BARS:index]]
        tr_p90 = percentile(prior_tr, 0.90)
        volume_p90 = percentile(prior_volume, 0.90)
        volatility_shock = tr_values[index] >= tr_p90
        volume_shock = bar.volume >= volume_p90
        signal_close_ts = bar.ts + BAR_MS
        hour_side = completed_hour_direction(bars_by_ts, signal_close_ts)
        session_event = in_session_window(signal_close_ts, session_minutes, session_window)
        selected = {
            "UTC_SESSION_TRANSITION": session_event,
            "VOLATILITY_SHOCK": volatility_shock,
            "VOLUME_SHOCK": volume_shock,
            "COMBINED_SHOCK": volatility_shock and volume_shock and hour_side == side and hour_side != 0,
        }.get(axis)
        if selected is None:
            raise ValueError(f"UNSUPPORTED_SELECTED_AXIS:{axis}")
        mask[index] = bool(selected)
        sides[index] = side
        diagnostics[index] = {
            "true_range": tr_values[index],
            "true_range_p90_prior_96": tr_p90,
            "volume": bar.volume,
            "volume_p90_prior_96": volume_p90,
            "hour_direction": hour_side,
            "session_event": session_event,
            "volatility_shock": volatility_shock,
            "volume_shock": volume_shock,
        }
    return mask, sides, diagnostics


def forward_net_pct(
    bars: list[Bar],
    signal_index: int,
    side: int,
    horizon: int,
    all_in_cost_pct: float,
    delay_bars: int = 0,
) -> float | None:
    entry_index = signal_index + 1 + delay_bars
    exit_index = entry_index + horizon - 1
    if side not in (-1, 1) or entry_index >= len(bars) or exit_index >= len(bars):
        return None
    entry = bars[entry_index].open
    exit_close = bars[exit_index].close
    if entry <= 0:
        raise ValueError(f"NON_POSITIVE_ENTRY:{bars[entry_index].ts}")
    gross_pct = side * (exit_close / entry - 1.0) * 100.0
    return gross_pct - all_in_cost_pct


def find_placebo_index(
    bars: list[Bar],
    mask: list[bool],
    signal_index: int,
    max_horizon: int,
) -> int | None:
    for offset in (32, -32, 16, -16, 48, -48, 64, -64):
        index = signal_index + offset
        if index < ROLLING_BARS or index + 1 + max_horizon > len(bars):
            continue
        if mask[index] or direction(bars[index]) == 0:
            continue
        return index
    return None


def utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def block_bootstrap_mean_ci(
    observations: list[tuple[str, float]], seed: int, draws: int
) -> tuple[float, float]:
    if not observations:
        return math.nan, math.nan
    by_day: dict[str, list[float]] = defaultdict(list)
    for day, value in observations:
        by_day[day].append(value)
    days = sorted(by_day)
    if len(days) == 1:
        values = by_day[days[0]]
        mean = fmean(values)
        return mean, mean
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(draws):
        sampled: list[float] = []
        for _ in days:
            sampled.extend(by_day[days[rng.randrange(len(days))]])
        means.append(fmean(sampled))
    return percentile(means, 0.025), percentile(means, 0.975)


def metric(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean_net_pct": fmean(values) if values else None,
        "median_net_pct": percentile(values, 0.5) if values else None,
        "positive_pct": (sum(value > 0 for value in values) / len(values) * 100.0) if values else None,
    }


def write_jsonl_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as text:
                for row in rows:
                    text.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ai-receipt", type=Path, required=True)
    parser.add_argument("--window", choices=("research", "W1", "W2", "W3"), default="research")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    plan = read_object(args.plan)
    ai = read_object(args.ai_receipt)
    manifest = read_object(args.inputs / "materialized_manifest.json")
    cost = read_object(args.inputs / "cost_binding.json")

    if plan.get("state") != "PASS_SESSION_EVENT_CONTINUATION_PLAN_SEALED_RESEARCH_ONLY":
        raise SystemExit("SESSION_EVENT_PLAN_NOT_SEALED")
    if ai.get("state") != "PASS_SESSION_EVENT_AI_CHAIN_BOUND":
        raise SystemExit("AI_CHAIN_NOT_BOUND")
    if manifest.get("state") != "PASS_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("MATERIALIZED_INPUT_STATE_MISMATCH")
    if cost.get("stress_lineage_complete") is not True:
        raise SystemExit("COST_LINEAGE_INCOMPLETE")

    selected_axis = str(ai.get("selected_axis", ""))
    allowed_axes = {
        str(row.get("axis"))
        for row in plan.get("pre_registered_axes", [])
        if isinstance(row, dict) and row.get("axis")
    }
    if selected_axis not in allowed_axes:
        raise SystemExit(f"AI_SELECTED_AXIS_NOT_PREREGISTERED:{selected_axis}")

    horizons = tuple(int(value) for value in plan["forward_horizons_15m_bars"])
    primary_horizon = int(plan["primary_horizon_15m_bars"])
    if primary_horizon not in horizons:
        raise SystemExit("PRIMARY_HORIZON_NOT_PREREGISTERED")
    all_in_cost_pct = float(cost["all_in_cost_pct"])
    if not math.isfinite(all_in_cost_pct) or all_in_cost_pct <= 0:
        raise SystemExit("INVALID_ALL_IN_COST")

    symbols = tuple(str(value) for value in plan["data_timeframes"]["symbols"])
    candidate_by_horizon: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    reversal_by_horizon: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    delay_by_horizon: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    shift_by_horizon: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    placebo_by_horizon: dict[int, list[float]] = {horizon: [] for horizon in horizons}
    candidate_primary_blocks: list[tuple[str, float]] = []
    ledger: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int]] = set()

    for symbol in symbols:
        bars_path = args.inputs / "market" / "15m" / args.window / f"{symbol}.csv.gz"
        bars = read_bars(bars_path)
        mask, sides, diagnostics = event_mask(selected_axis, bars, plan)
        max_horizon = max(horizons)
        for index in range(ROLLING_BARS, len(bars)):
            if not mask[index] or sides[index] == 0:
                continue
            if index + 1 + max_horizon > len(bars):
                continue
            key = (symbol, bars[index].ts)
            if key in seen_keys:
                raise SystemExit(f"DUPLICATE_EVENT:{symbol}:{bars[index].ts}")
            seen_keys.add(key)
            side = sides[index]
            shifted_index = index + 8
            shifted_side = direction(bars[shifted_index]) if shifted_index < len(bars) else 0
            placebo_index = find_placebo_index(bars, mask, index, max_horizon)
            placebo_side = direction(bars[placebo_index]) if placebo_index is not None else 0
            row: dict[str, Any] = {
                "symbol": symbol,
                "axis": selected_axis,
                "signal_ts": bars[index].ts,
                "signal_close_ts": bars[index].ts + BAR_MS,
                "entry_ts": bars[index + 1].ts,
                "side": "long" if side == 1 else "short",
                "diagnostics": diagnostics[index],
                "candidate_net_pct": {},
                "direction_reversal_net_pct": {},
                "plus_one_bar_delay_net_pct": {},
                "session_time_shift_2h_net_pct": {},
                "no_event_placebo_net_pct": {},
                "placebo_signal_ts": bars[placebo_index].ts if placebo_index is not None else None,
                "shifted_signal_ts": bars[shifted_index].ts if shifted_index < len(bars) else None,
            }
            for horizon in horizons:
                candidate = forward_net_pct(bars, index, side, horizon, all_in_cost_pct)
                reversal = forward_net_pct(bars, index, -side, horizon, all_in_cost_pct)
                delayed = forward_net_pct(bars, index, side, horizon, all_in_cost_pct, delay_bars=1)
                shifted = (
                    forward_net_pct(bars, shifted_index, shifted_side, horizon, all_in_cost_pct)
                    if shifted_index < len(bars) and shifted_side != 0
                    else None
                )
                placebo = (
                    forward_net_pct(bars, placebo_index, placebo_side, horizon, all_in_cost_pct)
                    if placebo_index is not None and placebo_side != 0
                    else None
                )
                for collection, value in (
                    (candidate_by_horizon[horizon], candidate),
                    (reversal_by_horizon[horizon], reversal),
                    (delay_by_horizon[horizon], delayed),
                    (shift_by_horizon[horizon], shifted),
                    (placebo_by_horizon[horizon], placebo),
                ):
                    if value is not None:
                        collection.append(value)
                row["candidate_net_pct"][str(horizon)] = candidate
                row["direction_reversal_net_pct"][str(horizon)] = reversal
                row["plus_one_bar_delay_net_pct"][str(horizon)] = delayed
                row["session_time_shift_2h_net_pct"][str(horizon)] = shifted
                row["no_event_placebo_net_pct"][str(horizon)] = placebo
                if horizon == primary_horizon and candidate is not None:
                    candidate_primary_blocks.append((utc_day(bars[index].ts), candidate))
            ledger.append(row)

    draws = int(plan["gates"]["bootstrap_draws"])
    seed = int(plan["gates"]["bootstrap_seed"])
    ci_low, ci_high = block_bootstrap_mean_ci(candidate_primary_blocks, seed, draws)
    primary_candidate = candidate_by_horizon[primary_horizon]
    primary_controls = {
        "NO_EVENT_PLACEBO": placebo_by_horizon[primary_horizon],
        "DIRECTION_REVERSAL": reversal_by_horizon[primary_horizon],
        "PLUS_ONE_BAR_DELAY": delay_by_horizon[primary_horizon],
        "SESSION_TIME_SHIFT_2H": shift_by_horizon[primary_horizon],
    }
    candidate_mean = fmean(primary_candidate) if primary_candidate else math.nan
    minimum_coverage = float(plan["gates"]["minimum_control_coverage_pct"])
    control_coverage = {
        name: (len(values) / len(primary_candidate) * 100.0 if primary_candidate else 0.0)
        for name, values in primary_controls.items()
    }
    control_means = {
        name: (fmean(values) if values else math.nan)
        for name, values in primary_controls.items()
    }
    gate_results = {
        "events_gte": len(primary_candidate) >= int(plan["gates"]["events_gte"]),
        "mean_net_return_gt_pct": candidate_mean > float(plan["gates"]["mean_net_return_gt_pct"]),
        "bootstrap_ci95_low_gt_pct": ci_low > float(plan["gates"]["bootstrap_ci95_low_gt_pct"]),
        "controls_coverage_gte_pct": all(value >= minimum_coverage for value in control_coverage.values()),
        "controls_separated": all(
            math.isfinite(value) and candidate_mean > value for value in control_means.values()
        ),
    }
    passed = all(gate_results.values())
    state = (
        "PASS_SESSION_EVENT_RESEARCH_EDGE"
        if passed and args.window == "research"
        else "PASS_SESSION_EVENT_W1_EDGE"
        if passed and args.window == "W1"
        else "HOLD_SESSION_EVENT_REPLAY_NO_EDGE"
    )

    metrics = {
        str(horizon): {
            "candidate": metric(candidate_by_horizon[horizon]),
            "NO_EVENT_PLACEBO": metric(placebo_by_horizon[horizon]),
            "DIRECTION_REVERSAL": metric(reversal_by_horizon[horizon]),
            "PLUS_ONE_BAR_DELAY": metric(delay_by_horizon[horizon]),
            "SESSION_TIME_SHIFT_2H": metric(shift_by_horizon[horizon]),
        }
        for horizon in horizons
    }
    ledger_path = args.output / "session_event_ledger.jsonl.gz"
    write_jsonl_gzip(ledger_path, ledger)
    receipt = {
        "schema_version": "zel.session_event.deterministic_replay.v1",
        "state": state,
        "family": "session_event_continuation_v1",
        "selected_axis": selected_axis,
        "window": args.window,
        "signal_timeframe": "15m",
        "execution": "next 15m open",
        "horizons_15m_bars": list(horizons),
        "primary_horizon_15m_bars": primary_horizon,
        "all_in_cost_pct": all_in_cost_pct,
        "event_count": len(primary_candidate),
        "metrics": metrics,
        "primary_bootstrap_ci95_pct": {
            "low": ci_low,
            "high": ci_high,
            "draws": draws,
            "seed": seed,
            "unit": "UTC_DAY",
        },
        "primary_control_coverage_pct": control_coverage,
        "gate_results": gate_results,
        "integrity": {
            "duplicate_events": 0,
            "future_information": 0,
            "closed_bar_only": True,
            "rolling_threshold_uses_prior_96_bars_only": True,
            "event_ledger_sha256": sha256_file(ledger_path),
            "event_ledger_rows": len(ledger),
        },
        "lineage": {
            "plan_sha256": sha256_file(args.plan),
            "plan_receipt_sha256": plan["receipt_sha256"],
            "ai_receipt_sha256": sha256_file(args.ai_receipt),
            "ai_selected_axis": ai["selected_axis"],
            "materialized_manifest_sha256": sha256_file(args.inputs / "materialized_manifest.json"),
            "materialized_manifest_receipt_sha256": manifest["manifest_receipt_sha256"],
            "cost_binding_sha256": sha256_file(args.inputs / "cost_binding.json"),
            "cost_binding_receipt_sha256": cost["receipt_sha256"],
        },
        "next_gate": "W1_HOLDOUT_REPLAY" if passed and args.window == "research" else "NONE_UNTIL_EDGE_PASS",
        **SAFETY,
        "action": "route_change" if passed else "hold",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path = args.output / "session_event_replay_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "selected_axis": selected_axis,
        "window": args.window,
        "event_count": len(primary_candidate),
        "primary_mean_net_pct": candidate_mean if math.isfinite(candidate_mean) else None,
        "ci95_low_pct": ci_low if math.isfinite(ci_low) else None,
        "gate_results": gate_results,
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
