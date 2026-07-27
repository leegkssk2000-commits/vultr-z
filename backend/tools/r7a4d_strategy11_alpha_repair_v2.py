from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
V1_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_REPAIR_V2"


def load_v1() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_repair_v1_for_v2"
        spec = importlib.util.spec_from_file_location(name, V1_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("V1_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


v1 = load_v1()
p = v1.p
exact = v1.exact
base = v1.base


def strict_json(path: Path) -> Any:
    return v1.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return v1.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    v1.atomic_json(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--iteration1-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    out = Path(args.out).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    iteration1_path = Path(args.iteration1_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    baseline_summary = strict_json(baseline_path)
    iteration1 = strict_json(iteration1_path)
    ssot = strict_json(ssot_path)

    if iteration1.get("strategy_id") != "alpha_combo":
        raise RuntimeError("ITERATION1_STRATEGY_MISMATCH")
    if iteration1.get("state") != "HOLD":
        raise RuntimeError("ITERATION1_STATE_MISMATCH")
    if iteration1.get("eligible_for_sealed_one_shot"):
        raise RuntimeError("ITERATION1_ALREADY_ELIGIBLE")
    if iteration1.get("sealed_holdback_read") is not False:
        raise RuntimeError("ITERATION1_SEALED_READ_VIOLATION")
    if iteration1.get("next") != "ITERATION_2_PARTIAL_OR_TRAILING":
        raise RuntimeError("ITERATION1_NEXT_MISMATCH")

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
    market_shas = v1.market_sha_map(manifest)
    cap_r = float(ssot["loss_budget"]["net_loss_cap_r"])

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        (
            "PARTIAL30_R075",
            replace(
                base_exit,
                exit_id="RR150_PARTIAL30_R075",
                partial_r=0.75,
                partial_fraction=0.30,
            ),
        ),
        (
            "TRAIL_R100_ATR100",
            replace(
                base_exit,
                exit_id="RR150_TRAIL_R100_ATR100",
                trail_activate_r=1.0,
                trail_atr_mult=1.0,
            ),
        ),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"REPAIR_V2_START variant={variant_id}", flush=True)
        rows.append(
            v1.evaluate_variant(
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
                cap_r=cap_r,
                out=out,
            )
        )
        print(f"REPAIR_V2_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    promotion = ssot["promotion"]
    eligible: list[str] = []
    for row in rows[1:]:
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
            and metric(row["loss_metrics"]["normal_worst_net_loss_R"], 0.0) >= cap_r
        )
        stress_cap = row["stress_2x_p95_plus_one"]["loss_metrics"]["loss_cap_breach_count"] == 0
        passes = (
            row["parity"]["state"] == "PASS"
            and normal_cap
            and stress_cap
            and metric(row["max_drawdown_pct"]) <= metric(incumbent["max_drawdown_pct"])
            and retention >= float(promotion["min_trade_retention_pct"])
            and row["positive_fresh_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
            and improved >= int(promotion["min_improved_primary_metrics"])
            and nonworse
        )
        row["comparison_to_incumbent"] = {
            "delta_net_pct_points": deltas["net"],
            "delta_profit_factor": deltas["pf"],
            "delta_payoff_ratio": deltas["payoff"],
            "improved_primary_metrics": improved,
            "trade_retention_pct": retention,
            "normal_loss_cap_pass": normal_cap,
            "stress_loss_cap_pass": stress_cap,
            "pass_to_sealed": passes,
        }
        if passes:
            eligible.append(str(row["variant_id"]))

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if eligible else "HOLD",
        "strategy_id": "alpha_combo",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "iteration1_run_id": "30262701736",
        "iteration1_summary_sha256": p.sha256(iteration1_path),
        "strategy_source_sha": strategy_source_sha,
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "ssot_sha256": p.sha256(ssot_path),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "variants": rows,
        "eligible_for_sealed_one_shot": eligible,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if eligible else "ITERATION_3_TIME_STOP_OR_SINGLE_GATE",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "ELIGIBLE": eligible}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
