#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import fmean
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_feature_runner(repo_root: Path):
    path = repo_root / "scripts/run_zel_momentum_feature_contribution_v1.py"
    spec = importlib.util.spec_from_file_location("zel_momentum_feature_contribution_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load feature contribution runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def finite_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def enrich_metrics(metrics: dict[str, Any], trades: list[dict[str, Any]]) -> None:
    gross = [float(row["gross_R"]) for row in trades]
    costs = [float(row["cost_R"]) for row in trades]
    gross_wins = [value for value in gross if value > 0]
    gross_losses = [value for value in gross if value < 0]
    metrics["gross_expectancy_R"] = fmean(gross) if gross else 0.0
    metrics["avg_cost_R"] = fmean(costs) if costs else 0.0
    metrics["gross_profit_factor"] = finite_ratio(sum(gross_wins), abs(sum(gross_losses))) if gross_losses else None
    metrics["gross_payoff"] = (
        finite_ratio(fmean(gross_wins), abs(fmean(gross_losses)))
        if gross_wins and gross_losses
        else None
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.repo_root = args.repo_root.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.repo_root))

    from backend.research import zel_feature_strategy_ssot_v1 as strategy

    engine = load_feature_runner(args.repo_root)
    manifest_path = args.inputs / "materialized_manifest.json"
    cost_path = args.inputs / "cost_binding.json"
    plan_path = args.repo_root / "backend/research/zel_momentum_cost_geometry_plan_v1.json"
    disposition_path = args.repo_root / "backend/research/zel_momentum_feature_contribution_disposition_v1.json"
    ssot_path = args.repo_root / "backend/research/zel_feature_strategy_ssot_v1.py"
    adapters_path = args.repo_root / "backend/research/zel_strategy_intent_adapters_v1.py"

    manifest = json.loads(manifest_path.read_text())
    cost = json.loads(cost_path.read_text())
    plan = json.loads(plan_path.read_text())
    disposition = json.loads(disposition_path.read_text())

    if manifest.get("state") != "PASS_MOMENTUM_MATERIALIZED_REPLAY_INPUTS":
        raise SystemExit("momentum materialization state mismatch")
    if plan.get("state") != "PASS_COST_GEOMETRY_PLAN_SEALED_RESEARCH_ONLY":
        raise SystemExit("cost geometry plan not sealed")
    if disposition.get("state") != "FAIL_NET_AFTER_COST_POSITIVE_GROSS_EDGE":
        raise SystemExit("feature contribution disposition mismatch")

    references = manifest.get("references", {})
    required_bindings = {
        "feature_strategy_ssot_sha256": sha256_file(ssot_path),
        "intent_adapters_sha256": sha256_file(adapters_path),
        "cost_geometry_plan_sha256": sha256_file(plan_path),
        "feature_contribution_disposition_sha256": sha256_file(disposition_path),
    }
    for key, expected in required_bindings.items():
        if references.get(key) != expected:
            raise SystemExit(f"materialized binding mismatch: {key}")

    fixed = plan["fixed_policy"]
    all_in_cost_pct = float(cost["all_in_cost_pct"])
    results: list[dict[str, Any]] = []
    ledgers: dict[str, list[dict[str, Any]]] = {}

    for profile in plan["profiles"]:
        for threshold in plan["expected_move_to_cost_thresholds"]:
            variant_id = f"{profile['profile_id']}__EMC_{threshold:g}"
            config = strategy.StrategyConfig(
                regime_lookback=int(fixed["regime_lookback"]),
                breakout_lookback=int(fixed["breakout_lookback"]),
                directional_efficiency_min=float(profile["directional_efficiency_min"]),
                breakout_buffer_atr=float(fixed["breakout_buffer_atr"]),
                expansion_atr_min=float(profile["expansion_atr_min"]),
                relative_volume_min=float(profile["relative_volume_min"]),
                stop_atr_multiple=float(fixed["stop_atr_multiple"]),
                target_r=float(fixed["target_r"]),
                max_hold_bars=int(fixed["max_hold_bars"]),
                expected_move_to_cost_min=float(threshold),
                quality_cutoff=float(fixed["quality_cutoff"]),
            )
            metrics, trades = engine.simulate_variant(
                strategy,
                args.inputs,
                config,
                variant_id,
                all_in_cost_pct,
            )
            enrich_metrics(metrics, trades)
            metrics["profile_id"] = profile["profile_id"]
            metrics["profile_role"] = profile["role"]
            metrics["expected_move_to_cost_min"] = float(threshold)
            metrics["config"] = {
                "regime_lookback": config.regime_lookback,
                "breakout_lookback": config.breakout_lookback,
                "directional_efficiency_min": config.directional_efficiency_min,
                "breakout_buffer_atr": config.breakout_buffer_atr,
                "expansion_atr_min": config.expansion_atr_min,
                "relative_volume_min": config.relative_volume_min,
                "stop_atr_multiple": config.stop_atr_multiple,
                "target_r": config.target_r,
                "max_hold_bars": config.max_hold_bars,
                "expected_move_to_cost_min": config.expected_move_to_cost_min,
                "quality_cutoff": config.quality_cutoff,
            }
            results.append(metrics)
            ledgers[variant_id] = trades

    base_trades = {
        profile["profile_id"]: next(
            int(row["trades"])
            for row in results
            if row["profile_id"] == profile["profile_id"] and row["expected_move_to_cost_min"] == 2.0
        )
        for profile in plan["profiles"]
    }
    gates = plan["hard_gates"]
    survivors: list[str] = []
    for row in results:
        denominator = max(base_trades[row["profile_id"]], 1)
        row["profile_retention_pct"] = float(row["trades"]) / denominator * 100.0
        row["hard_gate"] = {
            "minimum_trades": int(row["trades"]) >= int(gates["minimum_trades"]),
            "retention": row["profile_retention_pct"] >= float(gates["minimum_profile_retention_pct"]),
            "net_R": float(row["net_R"]) > float(gates["net_R_gt"]),
            "profit_factor": row["profit_factor"] is not None and float(row["profit_factor"]) >= float(gates["profit_factor_gte"]),
            "expectancy_R": float(row["expectancy_R"]) > float(gates["expectancy_R_gt"]),
            "payoff": row["payoff"] is not None and float(row["payoff"]) >= float(gates["payoff_gte"]),
        }
        row["hard_gate_pass"] = all(row["hard_gate"].values())
        if row["hard_gate_pass"]:
            survivors.append(row["variant_id"])

    ranking = [row["variant_id"] for row in sorted(
        results,
        key=lambda row: (
            float(row["net_R_per_day"]),
            float(row["expectancy_R"]),
            float(row["profile_retention_pct"]),
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
        raise SystemExit("duplicate cost geometry trades")

    state = (
        "PASS_COST_GEOMETRY_DIAGNOSIS_SURVIVOR_FOUND_SELECTION_NOT_AUTHORIZED"
        if survivors
        else "PASS_COST_GEOMETRY_DIAGNOSIS_NO_RETENTION_COMPLIANT_SURVIVOR"
    )
    next_gate = plan["next_if_survivor"] if survivors else plan["next_if_no_survivor"]
    receipt = {
        "schema_version": "zel.momentum.cost_geometry_receipt.v1",
        "state": state,
        "strategy_id": plan["strategy_id"],
        "window": plan["evaluation_window"],
        "single_causal_axis": plan["single_causal_axis"],
        "all_in_cost_pct": all_in_cost_pct,
        "references": required_bindings | {
            "materialized_manifest_sha256": sha256_file(manifest_path),
            "cost_binding_sha256": sha256_file(cost_path),
        },
        "results": results,
        "research_ranking": ranking,
        "hard_gate_survivors": survivors,
        "integrity": integrity,
        "selection_authority": False,
        "promotion_authority": False,
        "next_gate": next_gate,
        "action": "hold" if survivors else "route_change",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    (args.output / "cost_geometry_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    with gzip.open(args.output / "cost_geometry_trades.csv.gz", "wt", newline="") as handle:
        fieldnames = [
            "trade_id", "variant_id", "symbol", "signal_ts", "entry_ts", "exit_ts",
            "entry_price", "stop_price", "target_price", "planned_risk", "gross_R",
            "cost_R", "net_R", "exit_reason", "intent_sha256", "strategy_source_sha256",
            "feature_schema_sha256", "config_sha256",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for variant_id in ranking:
            writer.writerows(ledgers[variant_id])

    print(json.dumps({
        "state": state,
        "variants": len(results),
        "survivors": survivors,
        "top3": ranking[:3],
        "next_gate": next_gate,
        "receipt": receipt["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
