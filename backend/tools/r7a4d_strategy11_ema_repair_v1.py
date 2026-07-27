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
TURTLE_PATH = ROOT / "backend/tools/r7a4d_strategy11_turtle_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_EMA_REPAIR_V1"
FRESH_ROLES = ("F1", "F2", "F3")


def load_turtle() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_turtle_for_ema_repair"
        spec = importlib.util.spec_from_file_location(name, TURTLE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("TURTLE_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


turtle = load_turtle()
sealed = turtle.sealed
p = turtle.p
v1 = turtle.v1
exact = turtle.exact
base = turtle.base


def strict_json(path: Path) -> Any:
    return turtle.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return turtle.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    turtle.atomic_json(path, payload)


def promotion_check(row: dict[str, Any], incumbent: dict[str, Any], ssot: Mapping[str, Any], cap_r: float) -> dict[str, Any]:
    promotion = ssot["promotion"]
    deltas = {
        "net": metric(row["net_return_pct_sum"]) - metric(incumbent["net_return_pct_sum"]),
        "pf": metric(row["net_profit_factor"]) - metric(incumbent["net_profit_factor"]),
        "payoff": metric(row["payoff_ratio"]) - metric(incumbent["payoff_ratio"]),
    }
    thresholds = {
        "net": float(promotion["min_delta_net_pct_points"]),
        "pf": float(promotion["min_delta_profit_factor"]),
        "payoff": float(promotion["min_delta_payoff_ratio"]),
    }
    improved = sum(deltas[key] >= thresholds[key] for key in deltas)
    nonworse = all(value >= 0.0 for value in deltas.values())
    retention = row["trade_count"] / max(1, incumbent["trade_count"]) * 100.0
    normal_cap = (
        row["loss_metrics"]["loss_cap_breach_count"] == 0
        and metric(row["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    )
    stress_cap = (
        row["stress_2x_p95_plus_one"]["loss_metrics"]["loss_cap_breach_count"] == 0
        and metric(row["stress_2x_p95_plus_one"]["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    )
    avg_loss_nonworse = metric(row["loss_metrics"]["avg_loss_R"], -math.inf) >= metric(incumbent["loss_metrics"]["avg_loss_R"], -math.inf)
    passes = (
        row["parity"]["state"] == "PASS"
        and row["bootstrap"].get("state") == "PASS"
        and row["deflated_sharpe"].get("state") == "PASS"
        and normal_cap and stress_cap and avg_loss_nonworse
        and metric(row["max_drawdown_pct"], math.inf) <= metric(incumbent["max_drawdown_pct"], math.inf)
        and retention >= float(promotion["min_trade_retention_pct"])
        and row["positive_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
        and improved >= int(promotion["min_improved_primary_metrics"])
        and nonworse
    )
    return {
        "delta_net_pct_points": deltas["net"],
        "delta_profit_factor": deltas["pf"],
        "delta_payoff_ratio": deltas["payoff"],
        "improved_primary_metrics": improved,
        "trade_retention_pct": retention,
        "normal_loss_cap_pass": normal_cap,
        "stress_loss_cap_pass": stress_cap,
        "average_loss_nonworse": avg_loss_nonworse,
        "pass_to_sealed": passes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--baseline-trades", required=True)
    parser.add_argument("--turtle-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    baseline_trades_path = Path(args.baseline_trades).resolve()
    turtle_path = Path(args.turtle_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    baseline_trades = strict_json(baseline_trades_path)
    turtle_summary = strict_json(turtle_path)
    ssot = strict_json(ssot_path)

    if baseline_summary.get("strategy_id") != "ema_ribbon_scalp" or baseline_summary.get("state") != "PASS":
        raise RuntimeError("EMA_BASELINE_AUTHORITY_INVALID")
    if turtle_summary.get("strategy_id") != "turtle_trend" or turtle_summary.get("state") != "RETAIN_INCUMBENT":
        raise RuntimeError("TURTLE_AUTHORITY_INVALID")
    if turtle_summary.get("next") != "ADVANCE_EMA_RIBBON_SCALP_REVIEW":
        raise RuntimeError("TURTLE_NEXT_INVALID")
    if turtle_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("TURTLE_SEALED_READ_VIOLATION")

    trades = [row for row in baseline_trades.get("trades", []) if isinstance(row, Mapping)]
    favorable_loss_count = sum(
        metric(row.get("net_return_pct")) < 0.0 and metric(row.get("mfe_r")) >= 0.75
        for row in trades
    )
    long_loss_count = sum(
        metric(row.get("net_return_pct")) < 0.0 and int(row.get("bars_held") or 0) > 6
        for row in trades
    )
    if favorable_loss_count < 3:
        raise RuntimeError(f"BE_EVIDENCE_LT_3:{favorable_loss_count}")
    if long_loss_count < 3:
        raise RuntimeError(f"TIME_STOP_EVIDENCE_LT_3:{long_loss_count}")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline_summary.get("surgery"))
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))

    registry = base._load_registry(root)
    registry_row = registry["ema_ribbon_scalp"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "ema_ribbon_scalp", registry_row)

    frames, features, funding, manifest, market_shas = sealed.load_role_data(
        fresh_root,
        fresh_root,
        FRESH_ROLES,
        sealed_required=False,
    )
    quantiles = p.funding_rate_quantiles(funding)
    cap_r = float(ssot["loss_budget"]["net_loss_cap_r"])

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        ("BREAKEVEN_075R", replace(base_exit, exit_id="TIGHT085_BE075", breakeven_r=0.75)),
        ("TIME_STOP_6", replace(base_exit, exit_id="TIGHT085_TIME6", time_stop_bars=6)),
    ]

    rows: list[dict[str, Any]] = []
    original_surgery_allows = p.surgery_allows
    for variant_id, exit_spec in variants:
        print(f"EMA_REPAIR_V1_START variant={variant_id}", flush=True)
        row = turtle.evaluate_variant_with_surgery(
            variant_id=variant_id,
            exit_spec=exit_spec,
            surgery=surgery,
            original_surgery_allows=original_surgery_allows,
            strategy=strategy,
            gate=gate,
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
            cap_r=cap_r,
            out=out,
        )
        rows.append(row)
        print(f"EMA_REPAIR_V1_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    eligible: list[dict[str, Any]] = []
    for row in rows[1:]:
        comparison = promotion_check(row, incumbent, ssot, cap_r)
        row["comparison_to_incumbent"] = comparison
        atomic_json(out / row["variant_id"] / "summary.json", row)
        if comparison["pass_to_sealed"]:
            eligible.append(row)

    winner = None
    if eligible:
        winner = max(
            eligible,
            key=lambda row: (
                metric(row["net_return_pct_sum"]),
                metric(row["net_profit_factor"]),
                metric(row["payoff_ratio"]),
                -metric(row["max_drawdown_pct"], math.inf),
            ),
        )

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if winner else "HOLD",
        "strategy_id": "ema_ribbon_scalp",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "turtle_authority_run_id": "30280820928",
        "turtle_summary_sha256": p.sha256(turtle_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "baseline_trades_sha256": p.sha256(baseline_trades_path),
        "ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "reference_r_lock": {
            "state": "PASS",
            "definition": "INCUMBENT_RAW_RISK_PCT_FIXED_ACROSS_EXIT_VARIANTS",
        },
        "diagnosis": {
            "classification": "EXIT_LEAK_REPAIRABLE",
            "losses_reaching_0_75R_before_loss": favorable_loss_count,
            "losses_held_over_6_bars": long_loss_count,
            "baseline_fresh_net": baseline_summary["baseline"]["net_return_pct_sum"],
            "baseline_fresh_pf": baseline_summary["baseline"]["net_profit_factor"],
            "baseline_positive_windows_pct": baseline_summary["baseline"]["positive_fresh_windows_pct"],
        },
        "iteration_budget": {"max_iterations": 3, "used_iterations": 1, "exhausted": False},
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner["candidate_config_sha"] if winner else None,
        "eligible_for_sealed_one_shot": [winner["variant_id"]] if winner else [],
        "blockers": [] if winner else ["EMA_ITERATION_1_NO_CANDIDATE_PASSED_ALL_GATES"],
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if winner else "EMA_ITERATION_2_GATE_OR_STOP",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "WINNER": final["winner"], "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
