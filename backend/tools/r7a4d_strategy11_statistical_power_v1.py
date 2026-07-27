from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

VERSION = "R7A4D_STRATEGY11_STATISTICAL_POWER_V1"
WINDOW_BARS = 480
WINDOW_DAYS = 5.0
CURRENT_WINDOWS = ("F1", "F2", "F3")
MIN_GATE_TRADES = 12
ALPHA_ONE_SIDED = 0.05
TARGET_POWER = 0.80


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def locate(root: Path, strategy_id: str, filename: str) -> Path:
    matches = list(root.glob(f"{strategy_id}/{filename}"))
    if len(matches) != 1:
        raise RuntimeError(f"EVIDENCE_FILE_MATCH:{strategy_id}:{filename}:{len(matches)}")
    return matches[0]


def sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def required_n_for_positive_mean(values: Sequence[float]) -> int | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    std = sample_std(values)
    if mean <= 0.0:
        return None
    if std <= 1e-12:
        return MIN_GATE_TRADES
    z_alpha = NormalDist().inv_cdf(1.0 - ALPHA_ONE_SIDED)
    z_power = NormalDist().inv_cdf(TARGET_POWER)
    estimate = math.ceil(((z_alpha + z_power) * std / mean) ** 2)
    return max(MIN_GATE_TRADES, estimate)


def windows_for_target(current: int, target: int | None, rate: float) -> int | None:
    if target is None:
        return None
    remaining = max(0, target - current)
    if remaining == 0:
        return 0
    if rate <= 0.0:
        return None
    return math.ceil(remaining / rate)


def positive_window_best_case(current_positive: int, current_total: int, threshold: float = 0.70) -> int:
    added = 0
    while (current_positive + added) / (current_total + added) < threshold:
        added += 1
    return added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre-diagnosis", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    diagnosis_path = Path(args.pre_diagnosis).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    out = Path(args.out).resolve()
    diagnosis = load(diagnosis_path)
    records = [dict(row) for row in diagnosis.get("rows", []) if isinstance(row, Mapping)]
    if len(records) != 22:
        raise RuntimeError(f"POOL_SIZE:{len(records)}!=22")

    rows: list[dict[str, Any]] = []
    finite_eta: list[dict[str, Any]] = []
    zero_signal = 0
    for diagnostic in records:
        strategy_id = str(diagnostic["strategy_id"])
        trades_path = locate(evidence_root, strategy_id, "baseline_trades.json")
        trades = [dict(row) for row in load(trades_path).get("trades", []) if isinstance(row, Mapping)]
        trade_count = len(trades)
        if trade_count != int(diagnostic.get("existing_fresh_trade_count") or 0):
            raise RuntimeError(f"TRADE_COUNT_MISMATCH:{strategy_id}")
        if trade_count == 0:
            zero_signal += 1

        returns = [number(trade.get("net_return_pct")) for trade in trades]
        mean_return = None if not returns else sum(returns) / len(returns)
        std_return = None if not returns else sample_std(returns)
        by_window = {
            window: sum(number(trade.get("net_return_pct")) for trade in trades if str(trade.get("window_id")) == window)
            for window in CURRENT_WINDOWS
        }
        positive_windows = sum(value > 0.0 for value in by_window.values())
        positive_pct = positive_windows / len(CURRENT_WINDOWS) * 100.0
        signal_rate = trade_count / len(CURRENT_WINDOWS)

        power_target_n = required_n_for_positive_mean(returns)
        to_twelve = windows_for_target(trade_count, MIN_GATE_TRADES, signal_rate)
        to_power = windows_for_target(trade_count, power_target_n, signal_rate)
        to_positive = positive_window_best_case(positive_windows, len(CURRENT_WINDOWS))

        finite_components = [value for value in (to_twelve, to_power, to_positive) if value is not None]
        unbounded_reasons: list[str] = []
        if signal_rate <= 0.0:
            unbounded_reasons.append("ZERO_OBSERVED_SIGNAL_RATE")
        if power_target_n is None:
            unbounded_reasons.append("POSITIVE_MEAN_POWER_TARGET_UNAVAILABLE_FROM_CURRENT_RETURNS")
        required_windows = None if unbounded_reasons else max(finite_components, default=0)
        eta_days = None if required_windows is None else required_windows * WINDOW_DAYS

        row = {
            "strategy_id": strategy_id,
            "current_trade_count": trade_count,
            "observed_trades_per_480_bar_window": signal_rate,
            "current_mean_net_return_pct": mean_return,
            "current_sample_std_return_pct": std_return,
            "current_positive_windows": positive_windows,
            "current_positive_windows_pct": positive_pct,
            "minimum_additional_windows_to_12_trades": to_twelve,
            "mean_detection_target": {
                "alpha_one_sided": ALPHA_ONE_SIDED,
                "target_power": TARGET_POWER,
                "estimated_required_trade_count": power_target_n,
                "minimum_additional_windows": to_power,
                "method": "NORMAL_APPROXIMATION_USING_CURRENT_MEAN_AND_SAMPLE_STD",
                "authority_gate": False,
            },
            "positive_window_70pct_best_case": {
                "minimum_all-positive_additional_windows": to_positive,
                "forecast": False,
            },
            "bootstrap_contract": {
                "available_at_minimum_gate_trades": MIN_GATE_TRADES,
                "actual_stability_requires_recalculation_after_each_new_window": True,
            },
            "dsr_contract": {
                "planning_proxy": "MEAN_DETECTION_TARGET_N",
                "trial_count_used_by_W1_compute": 25,
                "final_DSR_must_be_recomputed_from_real_W1_returns": True,
            },
            "bh_fdr_contract": {
                "state": "COHORT_DEPENDENT",
                "q": 0.10,
                "fixed_per_strategy_sample_target": None,
                "recompute_across_all_eligible_strategies_after_W1": True,
            },
            "combined_required_additional_windows": required_windows,
            "combined_required_additional_bars": None if required_windows is None else required_windows * WINDOW_BARS,
            "eta_days_at_continuous_15m_data": eta_days,
            "eta_state": "UNBOUNDED_CURRENT_EVIDENCE" if required_windows is None else "RATE_BASED_RANGE_NOT_PERFORMANCE_FORECAST",
            "unbounded_reasons": unbounded_reasons,
            "source_trade_ledger": str(trades_path),
            "source_trade_ledger_count": trade_count,
        }
        rows.append(row)
        if required_windows is not None:
            finite_eta.append(row)

    rows.sort(key=lambda row: row["strategy_id"])
    finite_eta.sort(key=lambda row: (row["combined_required_additional_windows"], -row["current_trade_count"], row["strategy_id"]))
    summary = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_STATISTICAL_WINDOW_PLAN",
        "pool_size": len(rows),
        "zero_signal_strategy_count": zero_signal,
        "finite_eta_strategy_count": len(finite_eta),
        "unbounded_eta_strategy_count": len(rows) - len(finite_eta),
        "next_five_by_data_rate": [row["strategy_id"] for row in finite_eta[:5]],
        "window_contract": {
            "bars": WINDOW_BARS,
            "interval_minutes": 15,
            "days": WINDOW_DAYS,
            "current_windows": list(CURRENT_WINDOWS),
        },
        "interpretation": [
            "ETA_IS_NOT_A_PERFORMANCE_PREDICTION",
            "POWER_TARGET_USES_CURRENT_MEAN_AND_VARIANCE_AND_MUST_BE_RECOMPUTED_AFTER_W1",
            "BH_FDR_HAS_NO_FIXED_PER_STRATEGY_SAMPLE_SIZE",
            "ZERO_SIGNAL_STRATEGIES_REMAIN_UNBOUNDED_UNTIL_A_REAL_NON_OVERLAP_WINDOW_PRODUCES_SIGNALS",
        ],
        "performance_claim_allowed": False,
        "next": "ORCHESTRATION_FAILURE_INJECTION",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write_json(out / "summary.json", summary)
    write_json(out / "strategies.json", {"rows": rows})
    out.mkdir(parents=True, exist_ok=True)
    fields = [
        "strategy_id", "current_trade_count", "observed_trades_per_480_bar_window",
        "current_mean_net_return_pct", "current_sample_std_return_pct", "current_positive_windows_pct",
        "minimum_additional_windows_to_12_trades", "estimated_power_required_trade_count",
        "minimum_additional_windows_to_power", "minimum_positive_windows_best_case",
        "combined_required_additional_windows", "combined_required_additional_bars",
        "eta_days_at_continuous_15m_data", "eta_state", "unbounded_reasons",
    ]
    with (out / "strategies.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "strategy_id": row["strategy_id"],
                "current_trade_count": row["current_trade_count"],
                "observed_trades_per_480_bar_window": row["observed_trades_per_480_bar_window"],
                "current_mean_net_return_pct": row["current_mean_net_return_pct"],
                "current_sample_std_return_pct": row["current_sample_std_return_pct"],
                "current_positive_windows_pct": row["current_positive_windows_pct"],
                "minimum_additional_windows_to_12_trades": row["minimum_additional_windows_to_12_trades"],
                "estimated_power_required_trade_count": row["mean_detection_target"]["estimated_required_trade_count"],
                "minimum_additional_windows_to_power": row["mean_detection_target"]["minimum_additional_windows"],
                "minimum_positive_windows_best_case": row["positive_window_70pct_best_case"]["minimum_all-positive_additional_windows"],
                "combined_required_additional_windows": row["combined_required_additional_windows"],
                "combined_required_additional_bars": row["combined_required_additional_bars"],
                "eta_days_at_continuous_15m_data": row["eta_days_at_continuous_15m_data"],
                "eta_state": row["eta_state"],
                "unbounded_reasons": "|".join(row["unbounded_reasons"]),
            })
    print(json.dumps({"state": summary["state"], "pool": len(rows), "finite": len(finite_eta), "unbounded": len(rows)-len(finite_eta), "next": summary["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
