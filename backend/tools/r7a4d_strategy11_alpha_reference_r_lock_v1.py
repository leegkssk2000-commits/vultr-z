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
V1_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_ALPHA_REFERENCE_R_LOCK_V1"


def load_v1() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_alpha_repair_v1_for_reference_r"
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


def reference_loss_metrics(trades: list[dict[str, Any]], cap_r: float, stop_mult: float) -> dict[str, Any]:
    if not math.isfinite(stop_mult) or stop_mult <= 0.0:
        raise RuntimeError(f"STOP_MULT_INVALID:{stop_mult}")
    wins: list[float] = []
    losses: list[float] = []
    normal_losses: list[float] = []
    unavoidable: list[float] = []
    for trade in trades:
        candidate_risk_pct = metric(trade.get("risk_pct"))
        reference_risk_pct = candidate_risk_pct / stop_mult
        if reference_risk_pct <= 0.0:
            continue
        value = metric(trade.get("net_return_pct")) / reference_risk_pct
        if value > 0.0:
            wins.append(value)
        elif value < 0.0:
            losses.append(value)
            if bool(trade.get("path_ambiguous")):
                unavoidable.append(value)
            else:
                normal_losses.append(value)
    return {
        "r_definition": "NET_RETURN_PCT_DIVIDED_BY_INCUMBENT_RAW_RISK_PCT",
        "candidate_stop_mult": stop_mult,
        "avg_win_R": sum(wins) / len(wins) if wins else None,
        "avg_loss_R": sum(losses) / len(losses) if losses else None,
        "worst_net_loss_R": min(losses) if losses else None,
        "normal_worst_net_loss_R": min(normal_losses) if normal_losses else None,
        "loss_cap_breach_count": sum(value < cap_r for value in normal_losses),
        "unavoidable_execution_breach_count": sum(value < cap_r for value in unavoidable),
        "loss_count": len(losses),
        "win_count": len(wins),
    }


def rewrite_reference_ledgers(out: Path, variant_id: str, stop_mult: float, row: dict[str, Any]) -> None:
    ledgers: list[list[dict[str, Any]]] = []
    for replay_name in ("A", "B"):
        path = out / variant_id / f"replay-{replay_name}.json"
        payload = strict_json(path)
        trades = []
        for source in payload.get("trades", []):
            trade = dict(source)
            candidate_risk_pct = metric(trade.get("risk_pct"))
            reference_risk_pct = candidate_risk_pct / stop_mult if stop_mult > 0.0 else 0.0
            trade["candidate_risk_pct"] = candidate_risk_pct
            trade["reference_risk_pct"] = reference_risk_pct
            trade["net_reference_R"] = metric(trade.get("net_return_pct")) / reference_risk_pct if reference_risk_pct > 0.0 else None
            trade["reference_r_lock"] = "INCUMBENT_RAW_RISK_PCT"
            trades.append(trade)
        trades = v1.sorted_ledger(trades)
        atomic_json(path, {"variant_id": variant_id, "trades": trades})
        ledgers.append(trades)
    sha_a = v1.ledger_sha(ledgers[0])
    sha_b = v1.ledger_sha(ledgers[1])
    duplicates = len(ledgers[0]) - len({trade["trade_id"] for trade in ledgers[0]})
    row["parity"] = {
        "state": "PASS" if sha_a == sha_b and duplicates == 0 else "HOLD",
        "replay_a_sha256": sha_a,
        "replay_b_sha256": sha_b,
        "duplicate_trade_count": duplicates,
        "trade_count_a": len(ledgers[0]),
        "trade_count_b": len(ledgers[1]),
        "reference_r_lock": "PASS",
    }
    atomic_json(out / variant_id / "summary.json", row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--iteration1-summary", required=True)
    parser.add_argument("--iteration2-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    iteration1_path = Path(args.iteration1_summary).resolve()
    iteration2_path = Path(args.iteration2_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    iteration1 = strict_json(iteration1_path)
    iteration2 = strict_json(iteration2_path)
    ssot = strict_json(ssot_path)

    if iteration1.get("strategy_id") != "alpha_combo" or iteration1.get("state") != "HOLD":
        raise RuntimeError("ITERATION1_AUTHORITY_INVALID")
    if iteration2.get("strategy_id") != "alpha_combo" or iteration2.get("state") != "HOLD":
        raise RuntimeError("ITERATION2_AUTHORITY_INVALID")
    if iteration2.get("next") != "ITERATION_3_TIME_STOP_OR_SINGLE_GATE":
        raise RuntimeError("ITERATION2_NEXT_INVALID")
    if iteration1.get("sealed_holdback_read") is not False or iteration2.get("sealed_holdback_read") is not False:
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
        ("STOP_MULT_085_REFERENCE_R", replace(base_exit, exit_id="RR150_STOP085_REFERENCE_R", stop_mult=0.85)),
    ]

    rows: list[dict[str, Any]] = []
    original_loss_metrics = v1.loss_metrics
    try:
        for variant_id, exit_spec in variants:
            stop_mult = float(exit_spec.stop_mult)
            v1.loss_metrics = lambda trades, cap, sm=stop_mult: reference_loss_metrics(trades, cap, sm)
            print(f"REFERENCE_R_RECHECK_START variant={variant_id}", flush=True)
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
                source_run_id=args.source_run_id,
                source_head_sha=args.source_head_sha,
                cap_r=cap_r,
                out=out,
            )
            row["reference_r_lock"] = {
                "state": "PASS",
                "definition": "NET_RETURN_PCT_DIVIDED_BY_INCUMBENT_RAW_RISK_PCT",
                "candidate_stop_mult": stop_mult,
            }
            rewrite_reference_ledgers(out, variant_id, stop_mult, row)
            rows.append(row)
            print(f"REFERENCE_R_RECHECK_END variant={variant_id}", flush=True)
    finally:
        v1.loss_metrics = original_loss_metrics

    incumbent, challenger = rows
    promotion = ssot["promotion"]
    deltas = {
        "net": metric(challenger["net_return_pct_sum"]) - metric(incumbent["net_return_pct_sum"]),
        "pf": metric(challenger["net_profit_factor"]) - metric(incumbent["net_profit_factor"]),
        "payoff": metric(challenger["payoff_ratio"]) - metric(incumbent["payoff_ratio"]),
    }
    thresholds = {
        "net": float(promotion["min_delta_net_pct_points"]),
        "pf": float(promotion["min_delta_profit_factor"]),
        "payoff": float(promotion["min_delta_payoff_ratio"]),
    }
    improved = sum(deltas[key] >= thresholds[key] for key in deltas)
    nonworse = all(value >= 0.0 for value in deltas.values())
    retention = challenger["trade_count"] / max(1, incumbent["trade_count"]) * 100.0
    normal_cap = (
        challenger["loss_metrics"]["loss_cap_breach_count"] == 0
        and metric(challenger["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    )
    stress_cap = (
        challenger["stress_2x_p95_plus_one"]["loss_metrics"]["loss_cap_breach_count"] == 0
        and metric(challenger["stress_2x_p95_plus_one"]["loss_metrics"]["normal_worst_net_loss_R"], -math.inf) >= cap_r
    )
    avg_loss_nonworse = metric(challenger["loss_metrics"]["avg_loss_R"], -math.inf) >= metric(incumbent["loss_metrics"]["avg_loss_R"], -math.inf)
    passes = (
        challenger["parity"]["state"] == "PASS"
        and normal_cap
        and stress_cap
        and avg_loss_nonworse
        and metric(challenger["max_drawdown_pct"], math.inf) <= metric(incumbent["max_drawdown_pct"], math.inf)
        and retention >= float(promotion["min_trade_retention_pct"])
        and challenger["positive_fresh_windows_pct"] >= float(promotion["min_positive_fresh_windows_pct"])
        and improved >= int(promotion["min_improved_primary_metrics"])
        and nonworse
    )
    challenger["comparison_to_incumbent"] = {
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
    atomic_json(out / challenger["variant_id"] / "summary.json", challenger)

    eligible = [challenger["variant_id"]] if passes else []
    blockers: list[str] = []
    if not normal_cap:
        blockers.append("NORMAL_REFERENCE_R_CAP_FAIL")
    if not stress_cap:
        blockers.append("STRESS_REFERENCE_R_CAP_FAIL")
    if not avg_loss_nonworse:
        blockers.append("AVERAGE_LOSS_WORSE")
    if improved < int(promotion["min_improved_primary_metrics"]):
        blockers.append("ECONOMIC_IMPROVEMENT_LT_MIN")
    if not nonworse:
        blockers.append("PRIMARY_METRIC_DEGRADATION")

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if passes else "HOLD",
        "strategy_id": "alpha_combo",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "iteration1_run_id": "30262701736",
        "iteration2_run_id": "30264493769",
        "iteration1_summary_sha256": p.sha256(iteration1_path),
        "iteration2_summary_sha256": p.sha256(iteration2_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "reference_r_lock": {
            "state": "PASS",
            "definition": "INCUMBENT_RAW_RISK_PCT_FIXED_ACROSS_EXIT_VARIANTS",
            "reason": "CANDIDATE_STOP_MULT_MUST_NOT_CHANGE_THE_R_DENOMINATOR",
        },
        "variants": rows,
        "eligible_for_sealed_one_shot": eligible,
        "blockers": blockers,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if passes else "ITERATION_3_COST_AWARE_STOP_OR_RETAIN_INCUMBENT",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "ELIGIBLE": eligible, "BLOCKERS": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
