from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
COST_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_cost_aware_stop_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_ADAPTIVE_L085_V1"


def load_cost() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_cost_for_adaptive_l085"
        spec = importlib.util.spec_from_file_location(name, COST_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("COST_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


cost = load_cost()
p = cost.p
exact = cost.exact
base = cost.base


def strict_json(path: Path) -> Any:
    return cost.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return cost.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    cost.atomic_json(path, payload)


def worst(row: Mapping[str, Any], *, stress: bool = False) -> float:
    source = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}) if stress else row.get("loss_metrics", {})
    return metric(source.get("normal_worst_net_loss_R", source.get("worst_net_loss_R")), -math.inf)


def research_check(
    row: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    provisional: Mapping[str, Any],
    ladder: Mapping[str, Any],
    tolerances: Mapping[str, Any],
) -> dict[str, Any]:
    deltas_incumbent = {
        "net": metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct")),
    }
    deltas_provisional = {
        "net": metric(row.get("net_return_pct_sum")) - metric(provisional.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(provisional.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(provisional.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(provisional.get("max_drawdown_pct")),
    }
    improved = sum(
        value > 0.0
        for value in (deltas_incumbent["net"], deltas_incumbent["pf"], deltas_incumbent["payoff"])
    )
    retention = metric(row.get("trade_count")) / max(1.0, metric(incumbent.get("trade_count"), 1.0)) * 100.0
    avg_loss_nonworse = metric(row.get("loss_metrics", {}).get("avg_loss_R"), -math.inf) >= metric(
        incumbent.get("loss_metrics", {}).get("avg_loss_R"), -math.inf
    )
    normal_cap = worst(row) >= float(ladder["normal_worst_net_loss_R_min"])
    stress_cap = worst(row, stress=True) >= float(ladder["stress_worst_net_loss_R_min"])
    economic_floor = (
        deltas_incumbent["net"] >= -float(tolerances["max_net_degradation_pct_points"])
        and deltas_incumbent["pf"] >= -float(tolerances["max_profit_factor_degradation"])
        and deltas_incumbent["payoff"] >= -float(tolerances["max_payoff_degradation"])
    )
    passes = (
        row.get("parity", {}).get("state") == "PASS"
        and int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0
        and normal_cap
        and stress_cap
        and avg_loss_nonworse
        and metric(row.get("max_drawdown_pct"), math.inf)
        <= metric(incumbent.get("max_drawdown_pct"), math.inf)
        + float(ladder["max_drawdown_degradation_pct_points"])
        and retention >= float(ladder["min_trade_retention_pct"])
        and metric(row.get("positive_fresh_windows_pct")) >= float(ladder["min_positive_fresh_windows_pct"])
        and improved >= int(tolerances["min_improved_primary_metrics"])
        and economic_floor
    )
    return {
        "stage": ladder["stage"],
        "normal_cap_pass": normal_cap,
        "stress_cap_pass": stress_cap,
        "average_loss_nonworse": avg_loss_nonworse,
        "economic_floor_pass": economic_floor,
        "improved_primary_metrics": improved,
        "trade_retention_pct": retention,
        "deltas_to_incumbent": deltas_incumbent,
        "deltas_to_stop065_provisional": deltas_provisional,
        "research_pass": passes,
        "promotion_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--prior-summary", required=True)
    parser.add_argument("--adaptive-ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    prior_path = Path(args.prior_summary).resolve()
    ssot_path = Path(args.adaptive_ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    prior_summary = strict_json(prior_path)
    ssot = strict_json(ssot_path)
    ladder = next(row for row in ssot["loss_ladder"] if row["stage"] == "L085_DISCOVERY")
    tolerances = ssot["research_metric_tolerances"]

    if baseline_summary.get("strategy_id") != "alpha_combo":
        raise RuntimeError("BASELINE_STRATEGY_MISMATCH")
    if prior_summary.get("strategy_id") != "alpha_combo":
        raise RuntimeError("PRIOR_STRATEGY_MISMATCH")
    if prior_summary.get("winner") != "STOP_MULT_065_REFERENCE_R":
        raise RuntimeError("PRIOR_WINNER_MISMATCH")
    if prior_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("PRIOR_REPAIR_READ_SEALED")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline_summary.get("surgery"))
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)

    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = cost.v1.market_sha_map(manifest)

    stop065 = replace(base_exit, exit_id="RR150_STOP065_L085", stop_mult=0.65)
    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        ("L085_STOP065_CONTROL", stop065),
        (
            "L085_STOP065_TIME48",
            replace(stop065, exit_id="RR150_STOP065_TIME48_L085", time_stop_bars=48),
        ),
        (
            "L085_STOP065_TRAIL_R100_ATR150",
            replace(
                stop065,
                exit_id="RR150_STOP065_TRAIL_R100_ATR150_L085",
                trail_activate_r=1.0,
                trail_atr_mult=1.5,
            ),
        ),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"ADAPTIVE_L085_START variant={variant_id}", flush=True)
        row = cost.evaluate_with_reference_r(
            variant_id=variant_id,
            exit_spec=exit_spec,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            quantiles=quantiles,
            manifest=manifest,
            market_shas=market_shas,
            strategy_source_sha=strategy_source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            cap_r=float(ladder["stress_worst_net_loss_R_min"]),
            out=out,
        )
        rows.append(row)
        print(f"ADAPTIVE_L085_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    provisional = rows[1]
    eligible: list[dict[str, Any]] = []
    for row in rows[1:]:
        check = research_check(row, incumbent, provisional, ladder, tolerances)
        row["adaptive_research_check"] = check
        atomic_json(out / row["variant_id"] / "summary.json", row)
        if check["research_pass"]:
            eligible.append(row)

    winner = None
    if eligible:
        winner = max(
            eligible,
            key=lambda row: (
                metric(row.get("net_return_pct_sum")),
                metric(row.get("net_profit_factor")),
                metric(row.get("payoff_ratio")),
                -metric(row.get("max_drawdown_pct"), math.inf),
                worst(row, stress=True),
            ),
        )

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_L085_RESEARCH_CANDIDATE" if winner else "NO_L085_CANDIDATE",
        "strategy_id": "alpha_combo",
        "loss_ladder_stage": "L085_DISCOVERY",
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner.get("candidate_config_sha") if winner else None,
        "research_candidate_only": bool(winner),
        "promotion_authority": False,
        "sealed_holdback_read": False,
        "sealed_holdback_reuse_forbidden": True,
        "next": "ALPHA_L080_REFINEMENT" if winner else "TURTLE_L085_DISCOVERY",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "prior_summary_sha256": p.sha256(prior_path),
        "adaptive_ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "metric_coverage": [
            "trade_count",
            "win_rate_pct",
            "net_return_pct_sum",
            "net_profit_factor",
            "payoff_ratio",
            "max_drawdown_pct",
            "avg_loss_R",
            "normal_worst_net_loss_R",
            "stress_worst_net_loss_R",
            "positive_fresh_windows_pct",
            "trade_retention_pct",
            "independent_replay_parity",
        ],
        "variants": rows,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
        "blockers": [],
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({
        "state": final["state"],
        "winner": final["winner"],
        "next": final["next"],
        "variant_count": len(rows),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
