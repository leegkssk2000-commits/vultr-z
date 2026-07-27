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
VERSION = "R7A4D_STRATEGY11_TURTLE_GEMINI_TRAILING_V1"
FRESH_ROLES = ("F1", "F2", "F3")


def load_turtle() -> Any:
    original = importlib.util.module_from_spec
    def registered(spec):
        module = original(spec)
        sys.modules[spec.name] = module
        return module
    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_turtle_for_gemini_trailing"
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
exact = turtle.exact
base = turtle.base


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def metric(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    turtle.atomic_json(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--research-summary", required=True)
    parser.add_argument("--repair-queue", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    research_path = Path(args.research_summary).resolve()
    queue_path = Path(args.repair_queue).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    baseline = strict_json(baseline_path)
    research = strict_json(research_path)
    queue = strict_json(queue_path)
    ssot = strict_json(ssot_path)

    if baseline.get("strategy_id") != "turtle_trend" or baseline.get("state") != "PASS":
        raise RuntimeError("TURTLE_BASELINE_AUTHORITY_INVALID")
    if research.get("GEMINI_USED") is not True or research.get("free_only") is not True:
        raise RuntimeError("GEMINI_RESEARCH_AUTHORITY_INVALID")
    if research.get("approved_strategies") != ["turtle_trend"]:
        raise RuntimeError(f"APPROVED_STRATEGIES_UNEXPECTED:{research.get('approved_strategies')}")
    approved = [row for row in queue.get("rows", []) if row.get("strategy_id") == "turtle_trend"]
    if len(approved) != 1:
        raise RuntimeError(f"TURTLE_APPROVED_QUEUE_INVALID:{len(approved)}")
    hypothesis = approved[0]
    if hypothesis.get("label") != "HYPOTHESIS_EXTERNAL" or hypothesis.get("change_type") != "EXIT_POLICY":
        raise RuntimeError("TURTLE_HYPOTHESIS_INVALID")
    if "Widen trailing ATR stop multiplier" not in str(hypothesis.get("single_cause_change")):
        raise RuntimeError("TURTLE_HYPOTHESIS_CAUSE_MISMATCH")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry["turtle_trend"]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, "turtle_trend", registry_row)

    frames, features, funding, manifest, market_shas = sealed.load_role_data(
        fresh_root, fresh_root, FRESH_ROLES, sealed_required=False
    )
    quantiles = p.funding_rate_quantiles(funding)
    cap_r = float(ssot["loss_budget"]["net_loss_cap_r"])
    original_surgery_allows = p.surgery_allows

    variants = [
        ("INCUMBENT_CONTROL", base_exit),
        ("TRAIL_ACT100_ATR200", replace(base_exit, exit_id="TIGHT085_TRAIL_ACT100_ATR200", trail_activate_r=1.0, trail_atr_mult=2.0)),
        ("TRAIL_ACT100_ATR250", replace(base_exit, exit_id="TIGHT085_TRAIL_ACT100_ATR250", trail_activate_r=1.0, trail_atr_mult=2.5)),
    ]

    rows: list[dict[str, Any]] = []
    for variant_id, exit_spec in variants:
        print(f"TURTLE_GEMINI_TRAILING_START variant={variant_id}", flush=True)
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
        print(f"TURTLE_GEMINI_TRAILING_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    eligible: list[dict[str, Any]] = []
    for row in rows[1:]:
        comparison = turtle.promotion_check(row, incumbent, ssot, cap_r)
        row["comparison_to_incumbent"] = comparison
        atomic_json(out / row["variant_id"] / "summary.json", row)
        if comparison["pass_to_sealed"]:
            eligible.append(row)

    winner = None
    if eligible:
        winner = max(eligible, key=lambda row: (
            metric(row.get("net_return_pct_sum")),
            metric(row.get("net_profit_factor")),
            metric(row.get("payoff_ratio")),
            -metric(row.get("max_drawdown_pct"), math.inf),
        ))

    state = "PASS_NEW_SEALED_WAIT" if winner else "RESEARCH_DERIVED_REPAIR_HOLD"
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "strategy_id": "turtle_trend",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "research_authority_run_id": "30301475688",
        "research_summary_sha256": p.sha256(research_path),
        "repair_queue_sha256": p.sha256(queue_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "baseline_summary_sha256": p.sha256(baseline_path),
        "ssot_sha256": p.sha256(ssot_path),
        "strategy_source_sha": strategy_source_sha,
        "hypothesis": hypothesis,
        "single_cause_contract": {
            "activation_r_fixed": 1.0,
            "only_changed_axis": "trail_atr_mult",
            "tested_values": [2.0, 2.5],
            "no_change_control": True,
        },
        "variants": rows,
        "winner": winner["variant_id"] if winner else None,
        "eligible_for_new_sealed": [winner["variant_id"]] if winner else [],
        "existing_sealed_reused": False,
        "sealed_holdback_read": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "blockers": [] if winner else ["NO_RESEARCH_DERIVED_TRAILING_CANDIDATE_PASSED_ALL_GATES"],
        "next": "WAIT_NEW_NON_OVERLAP_SEALED" if winner else "EMA_CAUSAL_HOLD_PACKAGE",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"STATE": state, "WINNER": final["winner"], "NEXT": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
