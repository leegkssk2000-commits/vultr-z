from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_EMA_CAUSAL_HOLD_V1"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def summary(root: Path) -> tuple[Path, Mapping[str, Any]]:
    path = root / "summary.json"
    return path, load(path)


def compact(run_id: int, root: Path, doc: Mapping[str, Any]) -> dict[str, Any]:
    variants = []
    for row in doc.get("variants", []):
        if not isinstance(row, Mapping):
            continue
        comparison = row.get("comparison_to_incumbent") if isinstance(row.get("comparison_to_incumbent"), Mapping) else {}
        variants.append({
            "variant_id": row.get("variant_id"),
            "trade_count": row.get("trade_count"),
            "win_rate_pct": row.get("win_rate_pct"),
            "net_return_pct_sum": row.get("net_return_pct_sum"),
            "net_profit_factor": row.get("net_profit_factor"),
            "payoff_ratio": row.get("payoff_ratio"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "positive_fresh_windows_pct": row.get("positive_fresh_windows_pct"),
            "pass_to_sealed": comparison.get("pass_to_sealed"),
        })
    return {
        "run_id": run_id,
        "state": doc.get("state"),
        "winner": doc.get("winner"),
        "blockers": doc.get("blockers", []),
        "next": doc.get("next"),
        "variants": variants,
        "summary_sha256": sha(root / "summary.json"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ema-v1-root", required=True)
    ap.add_argument("--ema-v2-root", required=True)
    ap.add_argument("--ema-v3-root", required=True)
    ap.add_argument("--gemini-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    roots = [Path(args.ema_v1_root).resolve(), Path(args.ema_v2_root).resolve(), Path(args.ema_v3_root).resolve()]
    runs = [30281595921, 30282056363, 30282593225]
    docs = [summary(root)[1] for root in roots]
    history = [compact(run_id, root, doc) for run_id, root, doc in zip(runs, roots, docs)]

    gemini_root = Path(args.gemini_root).resolve()
    gemini_summary_path = gemini_root / "summary.json"
    gemini_analysis_path = gemini_root / "strategy_analysis" / "C.json"
    gemini_summary = load(gemini_summary_path)
    gemini_analysis = load(gemini_analysis_path)
    if gemini_summary.get("state") != "PASS" or gemini_summary.get("GEMINI_USED") is not True:
        raise RuntimeError("GEMINI_AUTHORITY_INVALID")

    tested_axes = [
        "BREAKEVEN_075R", "TIME_STOP_6", "STOP_MULT_065_REFERENCE_R",
        "BLOCK_HIGH_ATR_PCT", "PARTIAL30_R075", "TRAIL_R075_ATR100",
    ]
    terminal = docs[-1]
    baseline = next((row for row in terminal.get("variants", []) if row.get("variant_id") == "INCUMBENT_CONTROL"), {})
    best = max(
        [row for doc in docs for row in doc.get("variants", []) if isinstance(row, Mapping)],
        key=lambda row: (float(row.get("net_return_pct_sum") or -1e9), float(row.get("net_profit_factor") or 0.0)),
        default={},
    )

    reopen_conditions = {
        "new_non_overlap_window_required": True,
        "minimum_new_window_trades": 6,
        "minimum_cumulative_fresh_trades": 12,
        "positive_window_requirement_pct": 70.0,
        "causal_change_required": [
            "new_failure_cluster_with_at_least_3_losses_and_winner_contamination_le_20pct",
            "material_change_in_symbol_or_regime_loss_concentration",
            "new_distinct_gemini_hypothesis_approved_by_red_team",
        ],
        "same_axis_numeric_retuning_forbidden": True,
        "full_state_replay_required_after_reopen": True,
    }

    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_HOLD_PACKAGE",
        "strategy_id": "ema_ribbon_scalp",
        "classification": "RESEARCH_EXHAUSTED_HOLD",
        "internal_iteration_budget": {"max": 3, "used": 3, "exhausted": True},
        "tested_axes": tested_axes,
        "repair_history": history,
        "baseline_snapshot": baseline,
        "best_observed_non_promoted_variant": best,
        "gemini_authority": {
            "pr": 222,
            "run_id": 30302007460,
            "summary_sha256": sha(gemini_summary_path),
            "analysis_sha256": sha(gemini_analysis_path),
            "approved_hypothesis_count": gemini_summary.get("approved_hypothesis_count"),
            "strategy_candidate_hypotheses": gemini_analysis.get("candidate_hypotheses", []),
        },
        "reopen_conditions": reopen_conditions,
        "current_action": "WAIT_W1_NEW_CAUSAL_EVIDENCE",
        "deletion_allowed": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "next": "DATA_WAIT_POOL_PRE_DIAGNOSIS_22",
    }
    write(Path(args.out).resolve() / "summary.json", result)
    write(Path(args.out).resolve() / "repair_history.json", {"rows": history})
    print(json.dumps({"state": result["state"], "classification": result["classification"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
