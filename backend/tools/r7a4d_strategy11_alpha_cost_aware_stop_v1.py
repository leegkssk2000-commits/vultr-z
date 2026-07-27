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
REFERENCE_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_reference_r_lock_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_COST_AWARE_STOP_V1"


def load_reference() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_reference_r_for_cost_aware"
        spec = importlib.util.spec_from_file_location(name, REFERENCE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("REFERENCE_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


ref = load_reference()
v1 = ref.v1
p = ref.p
exact = ref.exact
base = ref.base


def strict_json(path: Path) -> Any:
    return ref.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return ref.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    ref.atomic_json(path, payload)


def evaluate_with_reference_r(*, variant_id: str, exit_spec: Any, strategy: Any, gate: Any, surgery: Any,
                              symbols: tuple[str, ...], frames: Mapping[Any, Any], features: Mapping[Any, Any],
                              funding: Mapping[str, Any], quantiles: Mapping[str, Any], manifest: Mapping[str, Any],
                              market_shas: Mapping[Any, str], strategy_source_sha: str, source_run_id: str,
                              source_head_sha: str, cap_r: float, out: Path) -> dict[str, Any]:
    stop_mult = float(exit_spec.stop_mult)
    original = v1.loss_metrics
    try:
        v1.loss_metrics = lambda trades, cap, sm=stop_mult: ref.reference_loss_metrics(trades, cap, sm)
        row = v1.evaluate_variant(
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
            source_run_id=source_run_id,
            source_head_sha=source_head_sha,
            cap_r=cap_r,
            out=out,
        )
    finally:
        v1.loss_metrics = original
    row["reference_r_lock"] = {
        "state": "PASS",
        "definition": "NET_RETURN_PCT_DIVIDED_BY_INCUMBENT_RAW_RISK_PCT",
        "candidate_stop_mult": stop_mult,
    }
    ref.rewrite_reference_ledgers(out, variant_id, stop_mult, row)
    return row


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
        and normal_cap
        and stress_cap
        and avg_loss_nonworse
        and metric(row["max_drawdown_pct"], math.inf) <= metric(incumbent["max_drawdown_pct"], math.inf)
        and retention >= float(promotion["min_trade_retention_pct"])
        and row["positive_fresh_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
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
    parser.add_argument("--reference-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    reference_path = Path(args.reference_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    reference_summary = strict_json(reference_path)
    ssot = strict_json(ssot_path)

    if reference_summary.get("strategy_id") != "alpha_combo" or reference_summary.get("state") != "HOLD":
        raise RuntimeError("REFERENCE_AUTHORITY_INVALID")
    if reference_summary.get("blockers") != ["STRESS_REFERENCE_R_CAP_FAIL"]:
        raise RuntimeError(f"REFERENCE_BLOCKER_UNEXPECTED:{reference_summary.get('blockers')}")
    if reference_summary.get("next") != "ITERATION_3_COST_AWARE_STOP_OR_RETAIN_INCUMBENT":
        raise RuntimeError("REFERENCE_NEXT_INVALID")
    if reference_summary.get("sealed_holdback_read") is not False:
        raise RuntimeError("SEALED_READ_VIOLATION")

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
        ("STOP_MULT_070_REFERENCE_R", replace(base_exit, exit_id="RR150_STOP070_REFERENCE_R", stop_mult=0.70)),
        ("STOP_MULT_065_REFERENCE_R", replace(base_exit, exit_id="RR150_STOP065_REFERENCE_R", stop_mult=0.65)),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"COST_AWARE_STOP_START variant={variant_id}", flush=True)
        row = evaluate_with_reference_r(
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
        rows.append(row)
        print(f"COST_AWARE_STOP_END variant={variant_id}", flush=True)

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

    blockers: list[str] = []
    if winner is None:
        blockers.append("NO_COST_AWARE_STOP_PASSED_ALL_GATES")

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if winner else "RETAIN_INCUMBENT",
        "strategy_id": "alpha_combo",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "reference_authority_run_id": "30277717051",
        "reference_summary_sha256": p.sha256(reference_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "reference_r_lock": {
            "state": "PASS",
            "definition": "INCUMBENT_RAW_RISK_PCT_FIXED_ACROSS_EXIT_VARIANTS",
        },
        "iteration_budget": {
            "max_iterations": 3,
            "used_iterations": 3,
            "exhausted": True,
        },
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner["candidate_config_sha"] if winner else None,
        "eligible_for_sealed_one_shot": [winner["variant_id"]] if winner else [],
        "blockers": blockers,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if winner else "RETAIN_INCUMBENT_AND_ADVANCE_TURTLE_TREND",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "WINNER": final["winner"], "BLOCKERS": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
