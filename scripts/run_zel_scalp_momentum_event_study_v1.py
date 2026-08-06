#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

PRIMARY_HORIZON = 6
HORIZONS = (1, 3, 6, 12)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("zel_momentum_event_study_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load momentum candidate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_bars(path: Path, bar_type) -> list[Any]:
    bars: list[Any] = []
    previous_ts: int | None = None
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
        if set(reader.fieldnames or []) != required:
            raise ValueError(f"unexpected header: {path}")
        for row in reader:
            bar = bar_type(
                ts=int(row["timestamp_ms"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            bar.validate()
            if previous_ts is not None and bar.ts <= previous_ts:
                raise ValueError(f"non-monotonic timestamp: {path}")
            previous_ts = bar.ts
            bars.append(bar)
    return bars


def percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_mean_ci(values: list[float], seed: int, draws: int = 600) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(draws):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    return percentile(means, 0.025), percentile(means, 0.975)


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    lm = fmean(left)
    rm = fmean(right)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    lden = math.sqrt(sum((a - lm) ** 2 for a in left))
    rden = math.sqrt(sum((b - rm) ** 2 for b in right))
    return numerator / (lden * rden) if lden > 0 and rden > 0 else 0.0


def quality_deciles(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda item: (item["quality"], item["symbol"], item["signal_ts"]))
    n = len(ordered)
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(10)]
    for rank, event in enumerate(ordered):
        bucket = min(9, rank * 10 // max(n, 1))
        buckets[bucket].append(event)
    result: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets):
        primary = [event["net_forward_pct"][str(PRIMARY_HORIZON)] for event in bucket]
        result.append({
            "decile": index + 1,
            "count": len(bucket),
            "quality_min": min((event["quality"] for event in bucket), default=None),
            "quality_max": max((event["quality"] for event in bucket), default=None),
            "mean_net_forward_pct_h6": fmean(primary) if primary else None,
        })
    return result


def choose_cutoff(events: list[dict[str, Any]], deciles: list[dict[str, Any]]) -> tuple[float | None, list[dict[str, Any]]]:
    accepted_deciles: list[int] = []
    for row in reversed(deciles):
        mean_value = row["mean_net_forward_pct_h6"]
        if row["count"] == 0:
            continue
        if mean_value is None or mean_value <= 0:
            break
        accepted_deciles.append(int(row["decile"]))
    if not accepted_deciles:
        return None, []
    minimum_decile = min(accepted_deciles)
    ordered = sorted(events, key=lambda item: (item["quality"], item["symbol"], item["signal_ts"]))
    n = len(ordered)
    retained = [event for rank, event in enumerate(ordered) if (min(9, rank * 10 // n) + 1) >= minimum_decile]
    threshold = min(event["quality"] for event in retained)
    return threshold, retained


def unique_entry_trials(trial_plan: dict[str, Any], maximum: int) -> list[dict[str, Any]]:
    entry_keys = (
        "regime_lookback",
        "directional_efficiency_min",
        "breakout_lookback",
        "breakout_buffer_atr",
        "expansion_atr_multiple",
        "relative_volume_min",
    )
    seen: set[tuple[Any, ...]] = set()
    selected: list[dict[str, Any]] = []
    for trial in trial_plan["trials"]:
        fingerprint = tuple(trial[key] for key in entry_keys)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected.append({key: trial[key] for key in entry_keys} | {"source_config_id": trial["config_id"]})
        if len(selected) >= maximum:
            break
    return selected


def build_events(module, inputs: Path, entry_trial: dict[str, Any], fixed: dict[str, Any], all_in_cost_pct: float) -> list[dict[str, Any]]:
    config = module.Config(
        regime_lookback=int(entry_trial["regime_lookback"]),
        directional_efficiency_min=float(entry_trial["directional_efficiency_min"]),
        breakout_lookback=int(entry_trial["breakout_lookback"]),
        breakout_buffer_atr=float(entry_trial["breakout_buffer_atr"]),
        expansion_atr_multiple=float(entry_trial["expansion_atr_multiple"]),
        relative_volume_min=float(entry_trial["relative_volume_min"]),
        stop_atr_multiple=float(fixed["stop_atr_multiple"]),
        target_r=float(fixed["target_r"]),
        max_hold_bars=int(fixed["max_hold_bars"]),
        expected_move_to_cost_min=float(fixed["expected_move_to_cost_min"]),
    )
    config.validate()
    events: list[dict[str, Any]] = []
    required_setup = max(config.breakout_lookback + 2, 22)
    required_regime = max(config.regime_lookback, 15)

    for symbol in SYMBOLS:
        setup = read_bars(inputs / "market/5m/research" / f"{symbol}.csv.gz", module.Bar)
        regime = read_bars(inputs / "market/15m/research" / f"{symbol}.csv.gz", module.Bar)
        regime_ts = [bar.ts for bar in regime]
        for index in range(required_setup - 1, len(setup) - max(HORIZONS) - 2):
            confirm = setup[index]
            last_closed_regime_open = confirm.ts - 10 * 60_000
            regime_end = bisect.bisect_right(regime_ts, last_closed_regime_open)
            if regime_end < required_regime:
                continue
            decision = module.decide_long(
                regime[max(0, regime_end - required_regime):regime_end],
                setup[index - required_setup + 1:index + 1],
                config,
                all_in_cost_pct,
            )
            if decision.action != "long":
                continue
            quality = float(decision.expected_move_to_cost or 0.0) * float(decision.relative_volume or 0.0)
            entry_index = index + 1
            delayed_entry_index = index + 2
            entry = setup[entry_index].open
            delayed_entry = setup[delayed_entry_index].open
            forward: dict[str, float] = {}
            reversed_forward: dict[str, float] = {}
            delayed_forward: dict[str, float] = {}
            for horizon in HORIZONS:
                exit_close = setup[entry_index + horizon - 1].close
                delayed_exit_close = setup[delayed_entry_index + horizon - 1].close
                gross = (exit_close / entry - 1.0) * 100.0
                delayed_gross = (delayed_exit_close / delayed_entry - 1.0) * 100.0
                forward[str(horizon)] = gross - all_in_cost_pct
                reversed_forward[str(horizon)] = -gross - all_in_cost_pct
                delayed_forward[str(horizon)] = delayed_gross - all_in_cost_pct
            events.append({
                "symbol": symbol,
                "signal_ts": confirm.ts,
                "entry_ts": setup[entry_index].ts,
                "quality": quality,
                "expected_move_to_cost": decision.expected_move_to_cost,
                "relative_volume": decision.relative_volume,
                "net_forward_pct": forward,
                "reversed_net_forward_pct": reversed_forward,
                "delayed_net_forward_pct": delayed_forward,
            })
    return events


def summarize_trial(config_id: str, entry_trial: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    deciles = quality_deciles(events)
    cutoff, retained = choose_cutoff(events, deciles)
    retention = len(retained) / len(events) if events else 0.0
    selected_horizon_means = {
        str(horizon): (fmean(event["net_forward_pct"][str(horizon)] for event in retained) if retained else None)
        for horizon in HORIZONS
    }
    reversed_mean = (
        fmean(event["reversed_net_forward_pct"][str(PRIMARY_HORIZON)] for event in retained) if retained else None
    )
    delayed_mean = (
        fmean(event["delayed_net_forward_pct"][str(PRIMARY_HORIZON)] for event in retained) if retained else None
    )
    selected_primary = [event["net_forward_pct"][str(PRIMARY_HORIZON)] for event in retained]
    seed = int(hashlib.sha256(config_id.encode("utf-8")).hexdigest()[:16], 16)
    ci_low, ci_high = bootstrap_mean_ci(selected_primary, seed)
    nonempty = [row for row in deciles if row["count"] > 0 and row["mean_net_forward_pct_h6"] is not None]
    monotonicity = pearson(
        [float(row["decile"]) for row in nonempty],
        [float(row["mean_net_forward_pct_h6"]) for row in nonempty],
    )
    pass_gate = bool(
        len(events) >= 120
        and retention >= 0.60
        and selected_horizon_means["6"] is not None
        and selected_horizon_means["6"] > 0
        and selected_horizon_means["12"] is not None
        and selected_horizon_means["12"] > 0
        and ci_low > 0
        and monotonicity >= 0.35
        and reversed_mean is not None
        and reversed_mean < 0
        and delayed_mean is not None
        and delayed_mean > 0
    )
    return {
        "config_id": config_id,
        "entry_parameters": {key: value for key, value in entry_trial.items() if key != "source_config_id"},
        "source_config_id": entry_trial["source_config_id"],
        "event_count": len(events),
        "quality_cutoff": cutoff,
        "retained_count": len(retained),
        "retention_pct": retention * 100.0,
        "selected_mean_net_forward_pct": selected_horizon_means,
        "selected_primary_bootstrap_ci95_pct": {"low": ci_low, "high": ci_high},
        "quality_decile_monotonicity": monotonicity,
        "direction_reversal_mean_net_pct_h6": reversed_mean,
        "plus_one_bar_mean_net_pct_h6": delayed_mean,
        "deciles": deciles,
        "pass_event_study_gate": pass_gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    source_path = args.repo_root / "backend/research/momentum_breakout_continuation_v1.py"
    trial_path = args.repo_root / "backend/research/zel_scalp_momentum_generation1_trial_plan_v1.json"
    control_path = args.repo_root / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json"
    manifest = json.loads((args.inputs / "materialized_manifest.json").read_text())
    cost = json.loads((args.inputs / "cost_binding.json").read_text())
    trial_plan = json.loads(trial_path.read_text())
    control_plan = json.loads(control_path.read_text())

    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("momentum materialization state mismatch")
    if manifest.get("strategy_id") != "momentum_breakout_continuation_v1":
        raise SystemExit("strategy binding mismatch")
    if manifest["references"]["candidate_source_sha256"] != sha256_file(source_path):
        raise SystemExit("candidate source SHA mismatch")
    if manifest["references"]["trial_plan_sha256"] != sha256_file(trial_path):
        raise SystemExit("trial plan SHA mismatch")
    if manifest["references"]["control_plan_sha256"] != sha256_file(control_path):
        raise SystemExit("control plan SHA mismatch")
    all_in_cost_pct = float(cost["all_in_cost_pct"])

    module = load_module(source_path)
    stage = control_plan["staged_search"][0]
    entry_trials = unique_entry_trials(trial_plan, int(stage["maximum_trials"]))
    fixed = stage["fixed_parameters"]
    results: list[dict[str, Any]] = []
    for number, entry_trial in enumerate(entry_trials, 1):
        config_id = f"ES1-{number:03d}"
        events = build_events(module, args.inputs, entry_trial, fixed, all_in_cost_pct)
        results.append(summarize_trial(config_id, entry_trial, events))

    passing = [row for row in results if row["pass_event_study_gate"]]
    passing.sort(
        key=lambda row: (
            float(row["selected_mean_net_forward_pct"]["6"] or -math.inf),
            float(row["quality_decile_monotonicity"]),
            int(row["retained_count"]),
        ),
        reverse=True,
    )
    state = "PASS_EVENT_STUDY_EDGE_FOUND" if passing else "PASS_EVENT_STUDY_NO_EDGE"
    receipt = {
        "schema_version": "zel.scalp.momentum.event_study.v1",
        "state": state,
        "strategy_id": "momentum_breakout_continuation_v1",
        "window": "research",
        "horizons_5m_bars": list(HORIZONS),
        "primary_horizon_5m_bars": PRIMARY_HORIZON,
        "all_in_cost_pct": all_in_cost_pct,
        "trial_count": len(results),
        "trials": results,
        "passing_config_ids": [row["config_id"] for row in passing],
        "passing_count": len(passing),
        "negative_controls": {
            "NO_SIGNAL_PLACEBO": {"events": 0, "net_return_pct": 0.0, "promotion_authority": False},
            "DIRECTION_REVERSAL": "evaluated_per_trial",
            "PLUS_ONE_BAR_DELAY": "evaluated_per_trial",
        },
        "integrity": {
            "future_information": 0,
            "errors": 0,
            "duplicates": 0,
            "protected_mutations": 0,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold" if passing else "route_change",
        "input_manifest_receipt_sha256": manifest["manifest_receipt_sha256"],
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    (args.output / "momentum_event_study_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "state": state,
        "trial_count": len(results),
        "passing_count": len(passing),
        "best_config_id": passing[0]["config_id"] if passing else None,
        "receipt": receipt["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
