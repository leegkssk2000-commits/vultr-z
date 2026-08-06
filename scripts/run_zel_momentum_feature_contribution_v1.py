#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from statistics import fmean
from typing import Any

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
DAY_MS = 86_400_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_bars(path: Path, bar_type, timeframe_ms: int) -> list[Any]:
    bars: list[Any] = []
    previous_ts: int | None = None
    with gzip.open(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
        if set(reader.fieldnames or []) != required:
            raise ValueError(f"unexpected header: {path}")
        for row in reader:
            close_ts = int(row["timestamp_ms"]) + timeframe_ms
            bar = bar_type(
                ts=close_ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            bar.validate()
            if previous_ts is not None and close_ts <= previous_ts:
                raise ValueError(f"non-monotonic timestamp: {path}")
            previous_ts = close_ts
            bars.append(bar)
    return bars


def config_from_variant(module, plan: dict[str, Any], variant: dict[str, Any]):
    baseline = plan["baseline"]
    fixed = plan["fixed_risk_exit"]
    return module.StrategyConfig(
        regime_lookback=int(baseline["regime_lookback"]),
        breakout_lookback=int(baseline["breakout_lookback"]),
        directional_efficiency_min=float(variant["directional_efficiency_min"]),
        breakout_buffer_atr=float(baseline["breakout_buffer_atr"]),
        expansion_atr_min=float(variant["expansion_atr_min"]),
        relative_volume_min=float(variant["relative_volume_min"]),
        stop_atr_multiple=float(fixed["stop_atr_multiple"]),
        target_r=float(fixed["target_r"]),
        max_hold_bars=int(fixed["max_hold_bars"]),
        expected_move_to_cost_min=float(variant["expected_move_to_cost_min"]),
        quality_cutoff=float(fixed["quality_cutoff"]),
    )


def simulate_variant(module, inputs: Path, config, variant_id: str, all_in_cost_pct: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trades: list[dict[str, Any]] = []
    signals = 0
    rejected_unfillable = 0
    skipped_gap_or_alignment = 0
    first_ts: int | None = None
    last_ts: int | None = None

    required_setup = max(config.breakout_lookback + 1, 15)
    required_regime = config.regime_lookback

    for symbol in SYMBOLS:
        setup = read_bars(inputs / "market/5m/research" / f"{symbol}.csv.gz", module.Bar, module.FIVE_MIN_MS)
        regime = read_bars(inputs / "market/15m/research" / f"{symbol}.csv.gz", module.Bar, module.FIFTEEN_MIN_MS)
        regime_ts = [bar.ts for bar in regime]
        if setup:
            first_ts = setup[0].ts if first_ts is None else min(first_ts, setup[0].ts)
            last_ts = setup[-1].ts if last_ts is None else max(last_ts, setup[-1].ts)
        locked_until = -1

        for index in range(required_setup - 1, len(setup) - config.max_hold_bars - 1):
            if index <= locked_until:
                continue
            confirm = setup[index]
            regime_end = bisect.bisect_right(regime_ts, confirm.ts)
            if regime_end < required_regime:
                continue
            setup_slice = setup[index - required_setup + 1:index + 1]
            regime_slice = regime[regime_end - required_regime:regime_end]
            try:
                intent = module.decide_momentum_long(symbol, regime_slice, setup_slice, config, all_in_cost_pct)
            except ValueError as exc:
                if "timestamp discontinuity" in str(exc) or "alignment mismatch" in str(exc):
                    skipped_gap_or_alignment += 1
                    continue
                raise
            if intent.side != "long":
                continue
            signals += 1

            entry_index = index + 1
            entry_bar = setup[entry_index]
            entry_price = entry_bar.open
            stop_price = float(intent.invalidation_price)
            target_price = float(intent.target_price)
            planned_risk = float(intent.planned_risk)
            if planned_risk <= 0 or entry_price <= stop_price or entry_price >= target_price:
                rejected_unfillable += 1
                continue

            exit_price = setup[entry_index + config.max_hold_bars - 1].close
            exit_index = entry_index + config.max_hold_bars - 1
            exit_reason = "TIMEOUT"
            for cursor in range(entry_index, entry_index + config.max_hold_bars):
                bar = setup[cursor]
                stop_hit = bar.low <= stop_price
                target_hit = bar.high >= target_price
                if stop_hit:
                    exit_price = stop_price
                    exit_index = cursor
                    exit_reason = "STOP_FIRST" if target_hit else "STOP"
                    break
                if target_hit:
                    exit_price = target_price
                    exit_index = cursor
                    exit_reason = "TARGET"
                    break

            gross_r = (exit_price - entry_price) / planned_risk
            cost_r = (entry_price * (all_in_cost_pct / 100.0)) / planned_risk
            net_r = gross_r - cost_r
            trade_id = hashlib.sha256(
                f"{variant_id}|{symbol}|{intent.signal_ts}|{entry_bar.ts}|{exit_index}".encode("utf-8")
            ).hexdigest()
            trades.append({
                "trade_id": trade_id,
                "variant_id": variant_id,
                "symbol": symbol,
                "signal_ts": intent.signal_ts,
                "entry_ts": entry_bar.ts,
                "exit_ts": setup[exit_index].ts,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "planned_risk": planned_risk,
                "gross_R": gross_r,
                "cost_R": cost_r,
                "net_R": net_r,
                "exit_reason": exit_reason,
                "intent_sha256": intent.sha256(),
                "strategy_source_sha256": intent.strategy_source_sha256,
                "feature_schema_sha256": intent.feature_schema_sha256,
                "config_sha256": intent.config_sha256,
            })
            locked_until = exit_index

    ordered = sorted(trades, key=lambda row: (row["exit_ts"], row["symbol"], row["trade_id"]))
    net_values = [float(row["net_R"]) for row in ordered]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    elapsed_days = max(((last_ts or 0) - (first_ts or 0)) / DAY_MS, 1.0)
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    avg_win = fmean(wins) if wins else 0.0
    avg_loss = fmean(losses) if losses else 0.0
    payoff = avg_win / abs(avg_loss) if avg_loss < 0 else None
    metrics = {
        "variant_id": variant_id,
        "signals": signals,
        "trades": len(ordered),
        "win_rate_pct": (len(wins) / len(ordered) * 100.0) if ordered else 0.0,
        "net_R": sum(net_values),
        "net_R_per_day": sum(net_values) / elapsed_days,
        "profit_factor": profit_factor,
        "profit_factor_unbounded": bool(wins and not losses),
        "payoff": payoff,
        "payoff_unbounded": bool(avg_win > 0 and avg_loss >= 0),
        "expectancy_R": fmean(net_values) if net_values else 0.0,
        "avg_win_R": avg_win,
        "avg_loss_R": avg_loss,
        "max_drawdown_R": max_drawdown,
        "rejected_unfillable": rejected_unfillable,
        "skipped_gap_or_alignment": skipped_gap_or_alignment,
        "elapsed_days": elapsed_days,
        "duplicates": len(ordered) - len({row["trade_id"] for row in ordered}),
    }
    return metrics, ordered


def numeric_delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)


def ranking_value(value: float | None) -> float:
    return math.inf if value is None else float(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(args.repo_root.resolve()))
    from backend.research import zel_feature_strategy_ssot_v1 as module

    manifest_path = args.inputs / "materialized_manifest.json"
    cost_path = args.inputs / "cost_binding.json"
    plan_path = args.repo_root / "backend/research/zel_momentum_feature_contribution_plan_v1.json"
    control_path = args.repo_root / "backend/research/zel_scalp_momentum_replay_control_plan_v1.json"
    ssot_path = args.repo_root / "backend/research/zel_feature_strategy_ssot_v1.py"
    adapter_path = args.repo_root / "backend/research/zel_strategy_intent_adapters_v1.py"

    manifest = json.loads(manifest_path.read_text())
    cost = json.loads(cost_path.read_text())
    plan = json.loads(plan_path.read_text())
    control = json.loads(control_path.read_text())

    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("momentum materialization state mismatch")
    references = manifest.get("references", {})
    required_bindings = {
        "feature_strategy_ssot_sha256": sha256_file(ssot_path),
        "intent_adapters_sha256": sha256_file(adapter_path),
        "feature_contribution_plan_sha256": sha256_file(plan_path),
        "control_plan_sha256": sha256_file(control_path),
    }
    for key, expected in required_bindings.items():
        if references.get(key) != expected:
            raise SystemExit(f"materialized binding mismatch: {key}")
    if plan.get("state") != "PASS_PLAN_SEALED_RESEARCH_ATTRIBUTION_ONLY":
        raise SystemExit("feature contribution plan not sealed")
    if control.get("next_gate") != "FEATURE_ECONOMIC_CONTRIBUTION":
        raise SystemExit("feature contribution gate not authorized")

    all_in_cost_pct = float(cost["all_in_cost_pct"])
    results: list[dict[str, Any]] = []
    ledgers: dict[str, list[dict[str, Any]]] = {}
    for variant in plan["variants"]:
        config = config_from_variant(module, plan, variant)
        metrics, trades = simulate_variant(module, args.inputs, config, variant["variant_id"], all_in_cost_pct)
        metrics["added_feature"] = variant["added_feature"]
        metrics["config"] = asdict(config)
        results.append(metrics)
        ledgers[variant["variant_id"]] = trades

    baseline = results[0]
    baseline_trades = max(int(baseline["trades"]), 1)
    for row in results:
        row["retention_pct"] = float(row["trades"]) / baseline_trades * 100.0
        row["delta_vs_baseline"] = {
            "trades": int(row["trades"]) - int(baseline["trades"]),
            "win_rate_pct": float(row["win_rate_pct"]) - float(baseline["win_rate_pct"]),
            "net_R": float(row["net_R"]) - float(baseline["net_R"]),
            "net_R_per_day": float(row["net_R_per_day"]) - float(baseline["net_R_per_day"]),
            "profit_factor": numeric_delta(row["profit_factor"], baseline["profit_factor"]),
            "payoff": numeric_delta(row["payoff"], baseline["payoff"]),
            "expectancy_R": float(row["expectancy_R"]) - float(baseline["expectancy_R"]),
            "avg_loss_R": float(row["avg_loss_R"]) - float(baseline["avg_loss_R"]),
            "max_drawdown_R": float(row["max_drawdown_R"]) - float(baseline["max_drawdown_R"]),
        }

    ranking = [row["variant_id"] for row in sorted(
        results,
        key=lambda row: (
            float(row["net_R_per_day"]),
            ranking_value(row["profit_factor"]),
            float(row["expectancy_R"]),
        ),
        reverse=True,
    )]
    integrity = {
        "errors": 0,
        "duplicates": sum(int(row["duplicates"]) for row in results),
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    if integrity["duplicates"] != 0:
        raise SystemExit("duplicate feature contribution trades")

    receipt = {
        "schema_version": "zel.momentum.feature_contribution_receipt.v1",
        "state": "PASS_FEATURE_CONTRIBUTION_COMPLETE_SELECTION_NOT_AUTHORIZED",
        "strategy_id": plan["strategy_id"],
        "window": plan["evaluation_window"],
        "all_in_cost_pct": all_in_cost_pct,
        "references": required_bindings | {
            "materialized_manifest_sha256": sha256_file(manifest_path),
            "cost_binding_sha256": sha256_file(cost_path),
        },
        "results": results,
        "research_ranking": ranking,
        "integrity": integrity,
        "selection_authority": False,
        "promotion_authority": False,
        "next_gate": "W1_FEATURE_SELECTION_AFTER_ATTRIBUTION",
        "action": "hold",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    (args.output / "feature_contribution_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    with gzip.open(args.output / "feature_contribution_trades.csv.gz", "wt", newline="") as handle:
        fieldnames = [
            "trade_id", "variant_id", "symbol", "signal_ts", "entry_ts", "exit_ts",
            "entry_price", "stop_price", "target_price", "planned_risk", "gross_R",
            "cost_R", "net_R", "exit_reason", "intent_sha256", "strategy_source_sha256",
            "feature_schema_sha256", "config_sha256",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for variant_id in [row["variant_id"] for row in results]:
            writer.writerows(ledgers[variant_id])

    print(json.dumps({
        "state": receipt["state"],
        "variants": len(results),
        "ranking": ranking,
        "baseline_trades": baseline["trades"],
        "receipt": receipt["receipt_sha256"],
        "next_gate": receipt["next_gate"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
