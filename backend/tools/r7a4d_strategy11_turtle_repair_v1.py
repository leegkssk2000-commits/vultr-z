from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SEALED_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_sealed_one_shot_v1.py"
VERSION = "R7A4D_STRATEGY11_TURTLE_REPAIR_V1"
FRESH_ROLES = ("F1", "F2", "F3")


def load_sealed_runner() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_sealed_for_turtle_repair"
        spec = importlib.util.spec_from_file_location(name, SEALED_RUNNER_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("SEALED_RUNNER_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


sealed = load_sealed_runner()
p = sealed.p
v1 = sealed.v1
ref = sealed.ref
exact = sealed.exact
base = sealed.base


def strict_json(path: Path) -> Any:
    return sealed.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return sealed.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    sealed.atomic_json(path, payload)


def surgery_payload(spec: Any) -> Any:
    if spec is None:
        return None
    if isinstance(spec, (tuple, list)):
        return [surgery_payload(item) for item in spec]
    return {
        "surgery_id": str(spec.surgery_id),
        "feature": str(spec.feature),
        "kind": str(spec.kind),
        "value": spec.value,
        "block_when": str(spec.block_when),
    }


def evaluate_variant_with_surgery(
    *,
    variant_id: str,
    exit_spec: Any,
    surgery: Any,
    original_surgery_allows: Callable[[Any, Mapping[str, Any]], bool],
    strategy: Any,
    gate: Any,
    symbols: tuple[str, ...],
    frames: Mapping[Any, Any],
    features: Mapping[Any, Any],
    funding: Mapping[str, Any],
    quantiles: Mapping[str, Any],
    manifest: Mapping[str, Any],
    market_shas: Mapping[Any, str],
    strategy_source_sha: str,
    source_run_id: str,
    source_head_sha: str,
    cap_r: float,
    out: Path,
) -> dict[str, Any]:
    def composite_allows(spec: Any, values: Mapping[str, Any]) -> bool:
        if isinstance(spec, (tuple, list)):
            return all(original_surgery_allows(item, values) for item in spec)
        return original_surgery_allows(spec, values)

    p.surgery_allows = composite_allows
    try:
        row = sealed.evaluate_variant(
            variant_id=variant_id,
            exit_spec=exit_spec,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            roles=FRESH_ROLES,
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
        p.surgery_allows = original_surgery_allows
    row["surgery_contract"] = surgery_payload(surgery)
    row["candidate_identity"] = {
        "variant_id": variant_id,
        "exit": row["exit"],
        "surgery": row["surgery_contract"],
        "strategy_source_sha": strategy_source_sha,
    }
    atomic_json(out / variant_id / "summary.json", row)
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
    avg_loss_nonworse = (
        metric(row["loss_metrics"]["avg_loss_R"], -math.inf)
        >= metric(incumbent["loss_metrics"]["avg_loss_R"], -math.inf)
    )
    passes = (
        row["parity"]["state"] == "PASS"
        and row["bootstrap"].get("state") == "PASS"
        and row["deflated_sharpe"].get("state") == "PASS"
        and normal_cap
        and stress_cap
        and avg_loss_nonworse
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
    parser.add_argument("--alpha-sealed-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    alpha_sealed_path = Path(args.alpha_sealed_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    alpha_sealed = strict_json(alpha_sealed_path)
    ssot = strict_json(ssot_path)

    if baseline_summary.get("strategy_id") != "turtle_trend" or baseline_summary.get("state") != "PASS":
        raise RuntimeError("TURTLE_BASELINE_AUTHORITY_INVALID")
    if alpha_sealed.get("strategy_id") != "alpha_combo":
        raise RuntimeError("ALPHA_SEALED_STRATEGY_INVALID")
    if alpha_sealed.get("state") != "SEALED_REJECT_ROLLBACK":
        raise RuntimeError("ALPHA_SEALED_STATE_INVALID")
    if alpha_sealed.get("classification") != "NEAR_MISS_REPAIR_EXHAUSTED":
        raise RuntimeError("ALPHA_CLASSIFICATION_INVALID")
    if alpha_sealed.get("sealed_one_shot_consumed") is not True:
        raise RuntimeError("ALPHA_SEALED_NOT_CONSUMED")
    if alpha_sealed.get("next") != "ADVANCE_TURTLE_TREND_REVIEW":
        raise RuntimeError("ALPHA_NEXT_INVALID")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    original_surgery = p.surgery_from(baseline_summary.get("surgery"))
    directional_gate = p.EvidenceSurgery(
        surgery_id="BLOCK_directional_close_long_FALSE",
        feature="directional_close_long",
        kind="bool",
        value=False,
        block_when="EQ",
    )
    composite_surgery = tuple(item for item in (original_surgery, directional_gate) if item is not None)
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))

    registry = base._load_registry(root)
    registry_row = registry["turtle_trend"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "turtle_trend", registry_row)

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
        ("INCUMBENT_CONTROL", base_exit, original_surgery),
        (
            "STOP_MULT_065_REFERENCE_R",
            replace(base_exit, exit_id="TIGHT065_REFERENCE_R", stop_mult=0.65),
            original_surgery,
        ),
        (
            "REQUIRE_DIRECTIONAL_CLOSE_LONG",
            base_exit,
            composite_surgery,
        ),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec, surgery in variants:
        print(f"TURTLE_REPAIR_START variant={variant_id}", flush=True)
        row = evaluate_variant_with_surgery(
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
        print(f"TURTLE_REPAIR_END variant={variant_id}", flush=True)

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
        "state": "PASS_TO_SEALED" if winner else "RETAIN_INCUMBENT",
        "strategy_id": "turtle_trend",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "alpha_sealed_authority_run_id": "30279647167",
        "alpha_sealed_summary_sha256": p.sha256(alpha_sealed_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "reference_r_lock": {
            "state": "PASS",
            "definition": "INCUMBENT_RAW_RISK_PCT_FIXED_ACROSS_EXIT_VARIANTS",
        },
        "diagnosis": {
            "classification": ["STOP_COST_REPAIRABLE", "ENTRY_GATE_REPAIRABLE"],
            "directional_close_long_false_baseline_evidence": {
                "trade_count": 4,
                "loss_count": 4,
                "win_count": 0,
                "expected_trade_retention_pct": 80.95238095238095,
            },
        },
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner["candidate_config_sha"] if winner else None,
        "eligible_for_sealed_one_shot": [winner["variant_id"]] if winner else [],
        "blockers": [] if winner else ["NO_TURTLE_CANDIDATE_PASSED_ALL_GATES"],
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if winner else "ADVANCE_EMA_RIBBON_SCALP_REVIEW",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "WINNER": final["winner"], "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
