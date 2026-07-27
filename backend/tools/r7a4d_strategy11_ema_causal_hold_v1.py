from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_EMA_CAUSAL_HOLD_V1"


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def variant_view(row: Mapping[str, Any]) -> dict[str, Any]:
    comparison = row.get("comparison_to_incumbent") if isinstance(row.get("comparison_to_incumbent"), Mapping) else {}
    loss = row.get("loss_metrics") if isinstance(row.get("loss_metrics"), Mapping) else {}
    return {
        "variant_id": row.get("variant_id"),
        "trade_count": row.get("trade_count"),
        "win_rate_pct": row.get("win_rate_pct"),
        "net_return_pct_sum": row.get("net_return_pct_sum"),
        "net_profit_factor": row.get("net_profit_factor"),
        "payoff_ratio": row.get("payoff_ratio"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "positive_windows_pct": row.get("positive_windows_pct"),
        "avg_loss_R": loss.get("avg_loss_R"),
        "worst_net_loss_R": loss.get("worst_net_loss_R"),
        "delta_net_pct_points": comparison.get("delta_net_pct_points"),
        "delta_profit_factor": comparison.get("delta_profit_factor"),
        "delta_payoff_ratio": comparison.get("delta_payoff_ratio"),
        "pass_to_sealed": comparison.get("pass_to_sealed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ema1", required=True)
    parser.add_argument("--ema2", required=True)
    parser.add_argument("--ema3", required=True)
    parser.add_argument("--gemini", required=True)
    parser.add_argument("--turtle", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    paths = {key: Path(value).resolve() for key, value in vars(args).items() if key != "out"}
    out = Path(args.out).resolve()
    ema1, ema2, ema3 = (strict_json(paths[name]) for name in ("ema1", "ema2", "ema3"))
    gemini = strict_json(paths["gemini"])
    turtle = strict_json(paths["turtle"])

    blockers: list[str] = []
    if any(row.get("strategy_id") != "ema_ribbon_scalp" for row in (ema1, ema2, ema3)):
        blockers.append("EMA_AUTHORITY_MISMATCH")
    if gemini.get("GEMINI_USED") is not True or gemini.get("free_only") is not True:
        blockers.append("GEMINI_AUTHORITY_INVALID")
    if turtle.get("next") != "EMA_CAUSAL_HOLD_PACKAGE":
        blockers.append("TURTLE_NEXT_MISMATCH")
    if any(row.get("sealed_holdback_read") not in {False, None} for row in (ema1, ema2, ema3)):
        blockers.append("SEALED_READ_VIOLATION")

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (ema1, ema2, ema3):
        for row in source.get("variants", []):
            if not isinstance(row, Mapping):
                continue
            variant_id = str(row.get("variant_id") or "")
            if not variant_id or variant_id in seen:
                continue
            seen.add(variant_id)
            variants.append(variant_view(row))

    incumbent = next((row for row in variants if row["variant_id"] == "INCUMBENT_CONTROL"), None)
    best = max(variants, key=lambda row: float(row.get("net_return_pct_sum") or -1e99)) if variants else None
    if incumbent is None or best is None:
        blockers.append("EMA_VARIANTS_MISSING")

    reopen = {
        "minimum_new_nonoverlap_window_count": 1,
        "minimum_cumulative_trade_count": 12,
        "minimum_positive_windows_pct": 70.0,
        "failure_cluster_change_required": True,
        "failure_cluster_change_tests": [
            "exit_reason_distribution_total_variation_distance>=0.20",
            "symbol_loss_share_max_absolute_delta>=0.20",
            "favorable_then_loss_rate_absolute_delta>=0.15",
            "immediate_fail_rate_absolute_delta>=0.15",
        ],
        "new_single_cause_hypothesis_required_if_metrics_still_fail": True,
        "same_axis_micro_tuning_forbidden": True,
    }

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "HOLD" if blockers else "RESEARCH_EXHAUSTED_HOLD",
        "strategy_id": "ema_ribbon_scalp",
        "classification": "INTERNAL_REPAIR_BUDGET_EXHAUSTED_RESEARCH_REVIEWED",
        "authority_sha256": {name: sha256(path) for name, path in paths.items()},
        "internal_iterations_used": 3,
        "gemini_call_count": gemini.get("gemini_call_count"),
        "gemini_approved_hypothesis_count": gemini.get("approved_hypothesis_count"),
        "baseline": incumbent,
        "best_tested": best,
        "variants": variants,
        "causal_summary": {
            "fresh_edge_not_established": True,
            "best_tested_net_still_negative": bool(best and float(best.get("net_return_pct_sum") or 0.0) < 0.0),
            "best_tested_pf_below_one": bool(best and float(best.get("net_profit_factor") or 0.0) < 1.0),
            "positive_window_reproducibility_below_gate": bool(best and float(best.get("positive_windows_pct") or 0.0) < 70.0),
            "distinct_research_hypothesis_available": False,
        },
        "reopen_contract": reopen,
        "deleted": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "sealed_holdback_read": False,
        "blockers": blockers,
        "next": "DATA_WAIT_POOL_PRE_DIAGNOSIS_22" if not blockers else "HOLD",
    }
    atomic_json(out / "summary.json", final)
    print(json.dumps({"state": final["state"], "next": final["next"], "blockers": blockers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
