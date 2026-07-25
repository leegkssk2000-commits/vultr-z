from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
PARENT_PATH = ROOT / "backend/tools/r7a4d_strategy25_selected_single_loss_surgery.py"


def _load_parent() -> Any:
    module_name = "r7a4d_strategy25_selected_single_loss_surgery_parent_v2"
    spec = importlib.util.spec_from_file_location(module_name, PARENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PARENT_SURGERY_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


parent = _load_parent()


def _number(value: Any, default: float = 0.0) -> float:
    return parent._number(value, default)


def _row_level_candidates(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one causal loss cluster for full replay; final economics remain fail-closed."""
    baseline = parent._stats(trades)
    baseline_net = _number(baseline.get("net_return_pct_sum"), -math.inf)
    baseline_pf = _number(baseline.get("net_profit_factor"), 0.0)
    baseline_count = int(baseline.get("trade_count") or 0)
    rows: list[dict[str, Any]] = []
    seen_memberships: set[tuple[int, ...]] = set()

    for candidate in parent._generate_candidates(trades):
        membership = tuple(index for index, row in enumerate(trades) if parent._matches_trade(row, candidate))
        if not membership or len(membership) == len(trades) or membership in seen_memberships:
            continue
        seen_memberships.add(membership)
        removed = [trades[index] for index in membership]
        remaining = [row for index, row in enumerate(trades) if index not in set(membership)]
        removed_stats = parent._stats(removed)
        remaining_stats = parent._stats(remaining)
        removed_count = int(removed_stats.get("trade_count") or 0)
        losses_removed = int(removed_stats.get("loss_count") or 0)
        wins_removed = int(removed_stats.get("win_count") or 0)
        remaining_count = int(remaining_stats.get("trade_count") or 0)
        precision = losses_removed / max(removed_count, 1) * 100.0
        remaining_net = _number(remaining_stats.get("net_return_pct_sum"), -math.inf)
        remaining_pf = _number(remaining_stats.get("net_profit_factor"), 0.0)
        baseline_payoff = _number(baseline.get("payoff_ratio"), 0.0)
        remaining_payoff = _number(remaining_stats.get("payoff_ratio"), 0.0)

        eligible = bool(
            removed_count >= 5
            and losses_removed >= 4
            and precision >= 70.0
            and remaining_count >= 5
            and remaining_count >= max(5, int(baseline_count * 0.20))
            and remaining_net > baseline_net
            and remaining_pf >= baseline_pf
        )
        capped_pf_gain = min(remaining_pf, 5.0) - min(baseline_pf, 5.0)
        payoff_ratio = (
            remaining_payoff / baseline_payoff
            if baseline_payoff > 0.0 and remaining_payoff > 0.0
            else 0.0
        )
        score = (
            (remaining_net - baseline_net)
            + 8.0 * capped_pf_gain
            + 0.15 * precision
            + 0.08 * remaining_count
            + 2.0 * min(payoff_ratio, 1.5)
            - 0.35 * wins_removed
        )
        rows.append(
            {
                "candidate": candidate,
                "label": parent._candidate_label(candidate),
                "eligible": eligible,
                "score": score,
                "removed": removed_stats,
                "remaining": remaining_stats,
                "loss_precision_pct": precision,
                "losses_removed": losses_removed,
                "wins_removed": wins_removed,
                "remaining_trade_count": remaining_count,
                "row_level_payoff_preserved_within_5pct": bool(
                    baseline_payoff <= 0.0 or remaining_payoff >= baseline_payoff * 0.95
                ),
            }
        )
    return sorted(rows, key=lambda row: float(row["score"]), reverse=True)


def main() -> int:
    parent._row_level_candidates = _row_level_candidates
    parent.OUTPUT_DIR = "artifacts/strategy25_selected_single_loss_surgery_v2"
    return int(parent.main())


if __name__ == "__main__":
    raise SystemExit(main())
