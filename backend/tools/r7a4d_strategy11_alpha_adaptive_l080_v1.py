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
L085_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_adaptive_l085_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_ADAPTIVE_L080_V1"


def load_l085() -> Any:
    name = "r7a4d_strategy11_alpha_adaptive_l085_for_l080"
    spec = importlib.util.spec_from_file_location(name, L085_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("L085_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


l085 = load_l085()
cost = l085.cost
p = l085.p
exact = l085.exact
base = l085.base


def strict_json(path: Path) -> Any:
    return l085.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return l085.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    l085.atomic_json(path, payload)


def worst(row: Mapping[str, Any], stress: bool = False) -> float:
    source = row.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}) if stress else row.get("loss_metrics", {})
    return metric(source.get("normal_worst_net_loss_R", source.get("worst_net_loss_R")), -math.inf)


def check(row: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    deltas = {
        "net": metric(row.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "pf": metric(row.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff": metric(row.get("payoff_ratio")) - metric(control.get("payoff_ratio")),
        "dd": metric(row.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
    }
    improved = sum(deltas[key] > 0.0 for key in ("net", "pf", "payoff"))
    retention = metric(row.get("trade_count")) / max(1.0, metric(control.get("trade_count"), 1.0)) * 100.0
    avg_loss_ok = metric(row.get("loss_metrics", {}).get("avg_loss_R"), -math.inf) >= metric(control.get("loss_metrics", {}).get("avg_loss_R"), -math.inf)
    passes = (
        row.get("parity", {}).get("state") == "PASS"
        and int(row.get("parity", {}).get("duplicate_trade_count") or 0) == 0
        and worst(row) >= -0.80
        and worst(row, True) >= -0.85
        and metric(row.get("max_drawdown_pct"), math.inf) <= metric(control.get("max_drawdown_pct"), math.inf) + 0.15
        and retention >= 80.0
        and metric(row.get("positive_fresh_windows_pct")) >= 70.0
        and avg_loss_ok
        and improved >= 1
        and deltas["net"] >= -0.20
        and deltas["pf"] >= -0.05
        and deltas["payoff"] >= -0.10
    )
    return {
        "stage": "L080_REFINEMENT",
        "normal_worst_net_loss_R": worst(row),
        "stress_worst_net_loss_R": worst(row, True),
        "trade_retention_pct": retention,
        "average_loss_nonworse": avg_loss_ok,
        "improved_primary_metrics": improved,
        "deltas_to_l085_control": deltas,
        "research_pass": passes,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--l085-summary", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    l085_path = Path(args.l085_summary).resolve()
    out = Path(args.out).resolve()

    baseline = strict_json(baseline_path)
    prior = strict_json(l085_path)
    if prior.get("strategy_id") != "alpha_combo" or prior.get("state") != "PASS_L085_RESEARCH_CANDIDATE":
        raise RuntimeError("L085_AUTHORITY_INVALID")
    if prior.get("winner") != "L085_STOP065_CONTROL":
        raise RuntimeError("L085_WINNER_UNEXPECTED")
    if prior.get("sealed_holdback_read") is not False:
        raise RuntimeError("SEALED_REUSE_VIOLATION")

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

    stop065 = replace(base_exit, exit_id="RR150_STOP065_L080", stop_mult=0.65)
    variants = [
        ("L080_STOP065_CONTROL", stop065),
        ("L080_STOP065_TIME60", replace(stop065, exit_id="RR150_STOP065_TIME60_L080", time_stop_bars=60)),
        ("L080_STOP065_BE075", replace(stop065, exit_id="RR150_STOP065_BE075_L080", breakeven_r=0.75)),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"ALPHA_L080_START variant={variant_id}", flush=True)
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
            cap_r=-0.85,
            out=out,
        )
        rows.append(row)
        print(f"ALPHA_L080_END variant={variant_id}", flush=True)

    control = rows[0]
    eligible: list[dict[str, Any]] = []
    control["adaptive_research_check"] = {
        "stage": "L080_REFINEMENT",
        "research_pass": True,
        "promotion_authority": False,
        "normal_worst_net_loss_R": worst(control),
        "stress_worst_net_loss_R": worst(control, True),
    }
    atomic_json(out / control["variant_id"] / "summary.json", control)
    for row in rows[1:]:
        row["adaptive_research_check"] = check(row, control)
        atomic_json(out / row["variant_id"] / "summary.json", row)
        if row["adaptive_research_check"]["research_pass"]:
            eligible.append(row)

    winner = max(
        eligible,
        key=lambda row: (
            metric(row.get("net_return_pct_sum")),
            metric(row.get("net_profit_factor")),
            metric(row.get("payoff_ratio")),
            -metric(row.get("max_drawdown_pct"), math.inf),
            worst(row, True),
        ),
    ) if eligible else control

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_L080_RESEARCH_CANDIDATE",
        "strategy_id": "alpha_combo",
        "loss_ladder_stage": "L080_REFINEMENT",
        "winner": winner["variant_id"],
        "winner_is_refinement": winner["variant_id"] != control["variant_id"],
        "promotion_authority": False,
        "requires_l075_and_w1": True,
        "sealed_holdback_read": False,
        "sealed_holdback_reuse_forbidden": True,
        "next": "ALPHA_L075_TARGET" if winner else "WAIT_W1_CONFIRMATION",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "l085_authority_run_id": "30327226304",
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "l085_summary_sha256": p.sha256(l085_path),
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
    print(json.dumps({"state": final["state"], "winner": final["winner"], "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
