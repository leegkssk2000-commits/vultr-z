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
EMA_V2_PATH = ROOT / "backend/tools/r7a4d_strategy11_ema_repair_v2.py"
VERSION = "R7A4D_STRATEGY11_EMA_REPAIR_V3"
FRESH_ROLES = ("F1", "F2", "F3")


def load_v2() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_ema_repair_v2_for_v3"
        spec = importlib.util.spec_from_file_location(name, EMA_V2_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("EMA_V2_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


ema2 = load_v2()
ema1 = ema2.ema1
turtle = ema2.turtle
sealed = ema2.sealed
p = ema2.p
exact = ema2.exact
base = ema2.base


def strict_json(path: Path) -> Any:
    return ema2.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return ema2.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    ema2.atomic_json(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--baseline-trades", required=True)
    parser.add_argument("--iteration2-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    baseline_trades_path = Path(args.baseline_trades).resolve()
    iteration2_path = Path(args.iteration2_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    baseline_trades = strict_json(baseline_trades_path)
    iteration2 = strict_json(iteration2_path)
    ssot = strict_json(ssot_path)

    if baseline_summary.get("strategy_id") != "ema_ribbon_scalp" or baseline_summary.get("state") != "PASS":
        raise RuntimeError("EMA_BASELINE_AUTHORITY_INVALID")
    if iteration2.get("strategy_id") != "ema_ribbon_scalp" or iteration2.get("state") != "HOLD":
        raise RuntimeError("EMA_ITERATION2_AUTHORITY_INVALID")
    if iteration2.get("next") != "EMA_ITERATION_3_PARTIAL_OR_TRAILING":
        raise RuntimeError("EMA_ITERATION2_NEXT_INVALID")
    if iteration2.get("sealed_holdback_read") is not False:
        raise RuntimeError("EMA_ITERATION2_SEALED_READ_VIOLATION")

    trades = [row for row in baseline_trades.get("trades", []) if isinstance(row, Mapping)]
    losses_reaching_075 = sum(
        metric(row.get("net_return_pct")) < 0.0 and metric(row.get("mfe_r")) >= 0.75
        for row in trades
    )
    losses_reaching_100 = sum(
        metric(row.get("net_return_pct")) < 0.0 and metric(row.get("mfe_r")) >= 1.0
        for row in trades
    )
    if losses_reaching_075 < 3 or losses_reaching_100 < 2:
        raise RuntimeError(f"RUNNER_EVIDENCE_INSUFFICIENT:{losses_reaching_075}:{losses_reaching_100}")

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
    original_surgery_allows = p.surgery_allows

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        (
            "PARTIAL30_R075",
            replace(
                base_exit,
                exit_id="TIGHT085_PARTIAL30_R075",
                partial_r=0.75,
                partial_fraction=0.30,
            ),
        ),
        (
            "TRAIL_R075_ATR100",
            replace(
                base_exit,
                exit_id="TIGHT085_TRAIL_R075_ATR100",
                trail_activate_r=0.75,
                trail_atr_mult=1.0,
            ),
        ),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"EMA_REPAIR_V3_START variant={variant_id}", flush=True)
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
        print(f"EMA_REPAIR_V3_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    eligible: list[dict[str, Any]] = []
    for row in rows[1:]:
        comparison = ema1.promotion_check(row, incumbent, ssot, cap_r)
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

    state = "PASS_TO_SEALED" if winner else "STRUCTURAL_REJECT"
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "classification": "IMPROVED_CANDIDATE" if winner else "STRUCTURAL_REJECT",
        "strategy_id": "ema_ribbon_scalp",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "iteration2_run_id": "30282056363",
        "iteration2_summary_sha256": p.sha256(iteration2_path),
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
            "losses_reaching_0_75R_before_loss": losses_reaching_075,
            "losses_reaching_1_00R_before_loss": losses_reaching_100,
            "baseline_fresh_net": baseline_summary["baseline"]["net_return_pct_sum"],
            "baseline_fresh_pf": baseline_summary["baseline"]["net_profit_factor"],
            "baseline_positive_windows_pct": baseline_summary["baseline"]["positive_fresh_windows_pct"],
        },
        "iteration_budget": {"max_iterations": 3, "used_iterations": 3, "exhausted": True},
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner["candidate_config_sha"] if winner else None,
        "eligible_for_sealed_one_shot": [winner["variant_id"]] if winner else [],
        "blockers": [] if winner else ["EMA_REPAIR_BUDGET_EXHAUSTED_NO_POSITIVE_REPRODUCIBLE_EDGE"],
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if winner else "START_DATA_WAIT_POOL_REFRESH",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "WINNER": final["winner"], "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
