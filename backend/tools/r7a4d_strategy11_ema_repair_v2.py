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
EMA_V1_PATH = ROOT / "backend/tools/r7a4d_strategy11_ema_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_EMA_REPAIR_V2"
FRESH_ROLES = ("F1", "F2", "F3")
ATR_PCT_BLOCK_THRESHOLD = 0.5388052243085617


def load_v1() -> Any:
    original = importlib.util.module_from_spec

    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_ema_repair_v1_for_v2"
        spec = importlib.util.spec_from_file_location(name, EMA_V1_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("EMA_V1_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original


ema1 = load_v1()
turtle = ema1.turtle
sealed = ema1.sealed
p = ema1.p
exact = ema1.exact
base = ema1.base


def strict_json(path: Path) -> Any:
    return ema1.strict_json(path)


def metric(value: Any, default: float = 0.0) -> float:
    return ema1.metric(value, default)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    ema1.atomic_json(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--baseline-trades", required=True)
    parser.add_argument("--iteration1-summary", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    baseline_trades_path = Path(args.baseline_trades).resolve()
    iteration1_path = Path(args.iteration1_summary).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline_summary = strict_json(baseline_path)
    baseline_trades = strict_json(baseline_trades_path)
    iteration1 = strict_json(iteration1_path)
    ssot = strict_json(ssot_path)

    if baseline_summary.get("strategy_id") != "ema_ribbon_scalp" or baseline_summary.get("state") != "PASS":
        raise RuntimeError("EMA_BASELINE_AUTHORITY_INVALID")
    if iteration1.get("strategy_id") != "ema_ribbon_scalp" or iteration1.get("state") != "HOLD":
        raise RuntimeError("EMA_ITERATION1_AUTHORITY_INVALID")
    if iteration1.get("next") != "EMA_ITERATION_2_GATE_OR_STOP":
        raise RuntimeError("EMA_ITERATION1_NEXT_INVALID")
    if iteration1.get("sealed_holdback_read") is not False:
        raise RuntimeError("EMA_ITERATION1_SEALED_READ_VIOLATION")

    trades = [row for row in baseline_trades.get("trades", []) if isinstance(row, Mapping)]
    blocked = [
        row for row in trades
        if metric((row.get("features") or {}).get("atr_pct"), -math.inf) >= ATR_PCT_BLOCK_THRESHOLD
    ]
    blocked_losses = sum(metric(row.get("net_return_pct")) < 0.0 for row in blocked)
    blocked_wins = sum(metric(row.get("net_return_pct")) > 0.0 for row in blocked)
    expected_retention = (len(trades) - len(blocked)) / max(1, len(trades)) * 100.0
    if len(blocked) != 3 or blocked_losses != 3 or blocked_wins != 0:
        raise RuntimeError(f"ATR_GATE_EVIDENCE_INVALID:{len(blocked)}:{blocked_losses}:{blocked_wins}")
    if expected_retention < float(ssot["promotion"]["min_trade_retention_pct"]):
        raise RuntimeError(f"ATR_GATE_RETENTION_LT_MIN:{expected_retention}")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    original_surgery = p.surgery_from(baseline_summary.get("surgery"))
    atr_gate = p.EvidenceSurgery(
        surgery_id="BLOCK_atr_pct_GE_0.538805",
        feature="atr_pct",
        kind="numeric",
        value=ATR_PCT_BLOCK_THRESHOLD,
        block_when="GE",
    )
    composite_surgery = tuple(item for item in (original_surgery, atr_gate) if item is not None)
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
        ("INCUMBENT_CONTROL", base_exit, original_surgery),
        (
            "STOP_MULT_065_REFERENCE_R",
            replace(base_exit, exit_id="TIGHT065_REFERENCE_R", stop_mult=0.65),
            original_surgery,
        ),
        (
            "BLOCK_HIGH_ATR_PCT",
            base_exit,
            composite_surgery,
        ),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec, surgery in variants:
        print(f"EMA_REPAIR_V2_START variant={variant_id}", flush=True)
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
        print(f"EMA_REPAIR_V2_END variant={variant_id}", flush=True)

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

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_TO_SEALED" if winner else "HOLD",
        "strategy_id": "ema_ribbon_scalp",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "iteration1_run_id": "30281595921",
        "iteration1_summary_sha256": p.sha256(iteration1_path),
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
            "classification": ["STOP_COST_REPAIRABLE", "ENTRY_GATE_REPAIRABLE"],
            "atr_pct_gate_threshold": ATR_PCT_BLOCK_THRESHOLD,
            "atr_gate_baseline_blocked_trades": len(blocked),
            "atr_gate_baseline_blocked_losses": blocked_losses,
            "atr_gate_baseline_blocked_wins": blocked_wins,
            "atr_gate_expected_retention_pct": expected_retention,
        },
        "iteration_budget": {"max_iterations": 3, "used_iterations": 2, "exhausted": False},
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "winner_candidate_config_sha": winner["candidate_config_sha"] if winner else None,
        "eligible_for_sealed_one_shot": [winner["variant_id"]] if winner else [],
        "blockers": [] if winner else ["EMA_ITERATION_2_NO_CANDIDATE_PASSED_ALL_GATES"],
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "SEALED_HOLDBACK_ONE_SHOT" if winner else "EMA_ITERATION_3_PARTIAL_OR_TRAILING",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": final["state"], "WINNER": final["winner"], "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
