from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPAIR_PATH = ROOT / "backend/tools/r7a4d_strategy11_alpha_repair_v1.py"
VERSION = "R7A4D_STRATEGY11_FEATURE_GATE_L085_COMMON_V1"


def load_module() -> Any:
    name = "r7a4d_strategy11_feature_gate_l085_repair"
    spec = importlib.util.spec_from_file_location(name, REPAIR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("REPAIR_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


repair = load_module()
p = repair.p
exact = repair.exact
base = repair.base


def metric(value: Any, default: float = 0.0) -> float:
    return repair.metric(value, default)


def strict_json(path: Path) -> Any:
    return repair.strict_json(path)


def find_summary(root: Path, strategy_id: str) -> Path:
    matches = sorted(root.glob(f"batch-*/{strategy_id}/summary.json"))
    if len(matches) != 1:
        raise RuntimeError(f"EVIDENCE_SUMMARY_MATCH:{strategy_id}:{len(matches)}")
    return matches[0]


def normal_breach_count(replay_path: Path, threshold: float) -> int:
    payload = strict_json(replay_path)
    count = 0
    for row in payload.get("trades", []):
        if not isinstance(row, Mapping) or bool(row.get("path_ambiguous")):
            continue
        risk = metric(row.get("risk_pct"))
        if risk > 0 and metric(row.get("net_return_pct")) / risk < threshold:
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fresh-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--block-when", choices=("LE", "GE"), required=True)
    parser.add_argument("--surgery-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    fresh_root = Path(args.fresh_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    baseline_path = find_summary(evidence_root, args.strategy_id)
    baseline_summary = strict_json(baseline_path)
    if str(baseline_summary.get("strategy_id")) != args.strategy_id:
        raise RuntimeError("BASELINE_STRATEGY_MISMATCH")
    if baseline_summary.get("surgery"):
        raise RuntimeError("BASELINE_ALREADY_HAS_SURGERY_COMPOSITE_FORBIDDEN")

    candidate = baseline_summary["candidate"]
    gate = exact._gate_from(candidate)
    exit_spec = exact._exit_from(candidate)
    symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry[args.strategy_id]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, args.strategy_id, registry_row)
    frames, features, funding, manifest = p.load_fresh_data(fresh_root)
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    proposed_surgery = p.surgery_from({
        "surgery_id": args.surgery_id,
        "feature": args.feature,
        "kind": "numeric",
        "value": args.threshold,
        "block_when": args.block_when,
    })

    specs = (("NO_CHANGE_CONTROL", None), (args.surgery_id, proposed_surgery))
    rows: list[dict[str, Any]] = []
    for variant_id, surgery in specs:
        row = repair.evaluate_variant(
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
            cap_r=-0.90,
            out=out,
        )
        row["feature_gate"] = None if surgery is None else {
            "surgery_id": args.surgery_id,
            "feature": args.feature,
            "threshold": args.threshold,
            "block_when": args.block_when,
        }
        repair.atomic_json(out / variant_id / "summary.json", row)
        rows.append(row)

    control, proposed = rows
    deltas = {
        "net": metric(proposed.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "pf": metric(proposed.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff": metric(proposed.get("payoff_ratio")) - metric(control.get("payoff_ratio")),
        "dd": metric(proposed.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
        "win_rate": metric(proposed.get("win_rate_pct")) - metric(control.get("win_rate_pct")),
    }
    improved = sum(deltas[key] > 0.0 for key in ("net", "pf", "payoff"))
    retention = metric(proposed.get("trade_count")) / max(1.0, metric(control.get("trade_count"), 1.0)) * 100.0
    normal_worst = metric(proposed.get("loss_metrics", {}).get("normal_worst_net_loss_R"), -math.inf)
    stress_worst = metric(proposed.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}).get("normal_worst_net_loss_R"), -math.inf)
    normal_breaches = normal_breach_count(out / args.surgery_id / "replay-A.json", -0.85)
    stress_breaches = int(proposed.get("stress_2x_p95_plus_one", {}).get("loss_metrics", {}).get("loss_cap_breach_count") or 0)
    checks = {
        "parity": proposed.get("parity", {}).get("state") == "PASS" and int(proposed.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
        "normal_cap": normal_worst >= -0.85 and normal_breaches == 0,
        "stress_cap": stress_worst >= -0.90 and stress_breaches == 0,
        "dd": deltas["dd"] <= 0.15,
        "retention": retention >= 80.0,
        "positive_windows": metric(proposed.get("positive_fresh_windows_pct")) >= 70.0,
        "economic": improved >= 2 and deltas["net"] >= 0.0 and deltas["pf"] >= 0.0 and deltas["payoff"] >= 0.0,
    }
    passed = all(checks.values())
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_L085_RESEARCH_CANDIDATE" if passed else "W1_CAUSAL_WAIT",
        "strategy_id": args.strategy_id,
        "axis": "FEATURE_GATE",
        "winner": args.surgery_id if passed else None,
        "loss_ladder_stage": "L085_DISCOVERY",
        "comparison": {"deltas": deltas, "improved_primary_metrics": improved, "trade_retention_pct": retention, "normal_worst_net_loss_R": normal_worst, "stress_worst_net_loss_R": stress_worst, "normal_breach_count": normal_breaches, "stress_breach_count": stress_breaches, "checks": checks},
        "variants": rows,
        "baseline_summary_sha256": p.sha256(baseline_path),
        "fresh_manifest_sha256": p.sha256(fresh_root / "manifest.json"),
        "strategy_source_sha": strategy_source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "research_candidate_only": passed,
        "promotion_authority": False,
        "sealed_holdback_read": False,
        "next": "L080_REFINEMENT" if passed else "W1_CAUSAL_WAIT",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
        "blockers": [],
    }
    repair.atomic_json(out / "summary.json", final)
    print(json.dumps({"state": final["state"], "strategy_id": args.strategy_id, "winner": final["winner"], "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
