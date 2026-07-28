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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
L080_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_adaptive_l080_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_ADAPTIVE_L075_V1"


def load_l080() -> Any:
    name = "r7a4d_strategy11_alpha_adaptive_l080_for_l075"
    spec = importlib.util.spec_from_file_location(name, L080_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("L080_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


l080 = load_l080()
l085 = l080.l085
cost = l080.cost
p = l080.p
exact = l080.exact
base = l080.base
strict_json = l080.strict_json
metric = l080.metric
atomic_json = l080.atomic_json
worst = l080.worst


def loss_breaches(row: Mapping[str, Any], *, stress: bool = False) -> int:
    source = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}) if stress else row.get("loss_metrics", {})
    return int(source.get("loss_cap_breach_count") or 0)


def strict_check(row: Mapping[str, Any], incumbent: Mapping[str, Any]) -> dict[str, Any]:
    deltas = {
        "net": metric(row.get("net_return_pct_sum")) - metric(incumbent.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(incumbent.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(incumbent.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(incumbent.get("max_drawdown_pct")),
    }
    threshold_passes = {
        "net_plus_0_50pp": deltas["net"] >= 0.50,
        "pf_plus_0_10": deltas["pf"] >= 0.10,
        "payoff_plus_0_10": deltas["payoff"] >= 0.10,
    }
    threshold_count = sum(bool(value) for value in threshold_passes.values())
    no_economic_degradation = all(deltas[key] >= 0.0 for key in ("net", "pf", "payoff"))
    retention = metric(row.get("trade_count")) / max(1.0, metric(incumbent.get("trade_count"), 1.0)) * 100.0
    avg_loss_ok = metric(row.get("loss_metrics", {}).get("avg_loss_R"), -math.inf) >= metric(
        incumbent.get("loss_metrics", {}).get("avg_loss_R"), -math.inf
    )
    checks = {
        "parity_pass": row.get("parity", {}).get("state") == "PASS",
        "duplicate_free": int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
        "normal_cap_pass": worst(row) >= -0.75 and loss_breaches(row) == 0,
        "stress_cap_pass": worst(row, True) >= -0.75 and loss_breaches(row, stress=True) == 0,
        "dd_no_worse": deltas["dd"] <= 0.0,
        "trade_retention_pass": retention >= 80.0,
        "positive_windows_pass": metric(row.get("positive_fresh_windows_pct")) >= 70.0,
        "average_loss_nonworse": avg_loss_ok,
        "economic_threshold_count_pass": threshold_count >= 2,
        "economic_no_degradation": no_economic_degradation,
    }
    passes = all(checks.values())
    return {
        "stage": "L075_TARGET",
        "normal_worst_net_loss_R": worst(row),
        "stress_worst_net_loss_R": worst(row, True),
        "normal_breach_count": loss_breaches(row),
        "stress_breach_count": loss_breaches(row, stress=True),
        "trade_retention_pct": retention,
        "threshold_passes": threshold_passes,
        "threshold_pass_count": threshold_count,
        "deltas_to_incumbent": deltas,
        "checks": checks,
        "strict_target_pass": passes,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--l085-summary", required=True)
    parser.add_argument("--l080-summary", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    l085_path = Path(args.l085_summary).resolve()
    l080_path = Path(args.l080_summary).resolve()
    out = Path(args.out).resolve()

    baseline = strict_json(baseline_path)
    discovery = strict_json(l085_path)
    refinement = strict_json(l080_path)
    if discovery.get("state") != "PASS_L085_RESEARCH_CANDIDATE" or discovery.get("winner") != "L085_STOP065_CONTROL":
        raise RuntimeError("L085_AUTHORITY_INVALID")
    if refinement.get("state") != "PASS_L080_RESEARCH_CANDIDATE" or refinement.get("winner") != "L080_STOP065_CONTROL":
        raise RuntimeError("L080_AUTHORITY_INVALID")
    if discovery.get("sealed_holdback_read") is not False or refinement.get("sealed_holdback_read") is not False:
        raise RuntimeError("SEALED_REUSE_VIOLATION")

    incumbent = next((row for row in discovery.get("variants", []) if row.get("variant_id") == "INCUMBENT_CONTROL"), None)
    if not isinstance(incumbent, Mapping):
        raise RuntimeError("INCUMBENT_CONTROL_MISSING")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["alpha_combo"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "alpha_combo", registry_row)

    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = cost.v1.market_sha_map(manifest)

    stop065 = replace(base_exit, exit_id="RR150_STOP065_L075", stop_mult=0.65)
    variants = [
        ("L075_STOP065_CONTROL", stop065),
        ("L075_STOP0625", replace(base_exit, exit_id="RR150_STOP0625_L075", stop_mult=0.625)),
        ("L075_STOP060", replace(base_exit, exit_id="RR150_STOP060_L075", stop_mult=0.60)),
    ]

    rows: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"ALPHA_L075_START variant={variant_id}", flush=True)
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
            cap_r=-0.75,
            out=out,
        )
        row["strict_target_check"] = strict_check(row, incumbent)
        atomic_json(out / variant_id / "summary.json", row)
        rows.append(row)
        if row["strict_target_check"]["strict_target_pass"]:
            eligible.append(row)
        print(f"ALPHA_L075_END variant={variant_id}", flush=True)

    winner = max(
        eligible,
        key=lambda row: (
            metric(row.get("net_return_pct_sum")),
            metric(row.get("net_profit_factor")),
            metric(row.get("payoff_ratio")),
            -metric(row.get("max_drawdown_pct"), math.inf),
            worst(row, True),
        ),
    ) if eligible else None

    state = "PASS_L075_RESEARCH_CANDIDATE" if winner else "HOLD_L075_TARGET"
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "strategy_id": "alpha_combo",
        "loss_ladder_stage": "L075_TARGET",
        "winner": winner.get("variant_id") if winner else None,
        "eligible_count": len(eligible),
        "strict_target_pass": winner is not None,
        "promotion_authority": False,
        "requires_w1_confirmation": True,
        "requires_new_sealed_holdback": True,
        "sealed_holdback_read": False,
        "sealed_holdback_reuse_forbidden": True,
        "next": "ALPHA_W1_INDEPENDENT_CONFIRMATION" if winner else "WAIT_W1_CAUSAL_REVIEW",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "l085_authority_run_id": "30327226304",
        "l080_authority_run_id": "30328459739",
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "l085_summary_sha256": p.sha256(l085_path),
        "l080_summary_sha256": p.sha256(l080_path),
        "strategy_source_sha": strategy_source_sha,
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
    print(json.dumps({"state": state, "winner": final["winner"], "eligible_count": len(eligible), "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
