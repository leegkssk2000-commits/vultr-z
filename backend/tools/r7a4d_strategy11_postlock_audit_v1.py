from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def walk_items(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            current = f"{path}.{key}"
            yield current, item
            yield from walk_items(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            current = f"{path}[{index}]"
            yield current, item
            yield from walk_items(item, current)


def metric(metrics: Mapping[str, Any], phase: str, name: str) -> Any:
    row = metrics.get(phase) if isinstance(metrics.get(phase), Mapping) else {}
    return row.get(name)


def csv_write(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--lock-root", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    lock_root = Path(args.lock_root).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()

    ssot = strict_json(ssot_path)
    final_path = lock_root / "final.json"
    if not final_path.is_file():
        raise FileNotFoundError(f"FINAL_JSON_MISSING:{final_path}")
    final = strict_json(final_path)

    exact_root = run_root / "strategy11_exact_v1"
    roster_path = run_root / "strategy11_final_roster_v1" / "summary.json"
    orchestrator_path = run_root / "strategy11_orchestrator_v1" / "summary.json"
    exact_paths = sorted(exact_root.glob("*/summary.json"))
    roster = strict_json(roster_path) if roster_path.is_file() else {}
    orchestrator = strict_json(orchestrator_path) if orchestrator_path.is_file() else {}

    all_rows: list[dict[str, Any]] = []
    best_rows: list[dict[str, Any]] = []
    failure_reasons: Counter[str] = Counter()
    observed_keys: Counter[str] = Counter()
    observed_cost_values: dict[str, set[str]] = {}
    accepted_total = 0
    fresh_nonzero_candidates = 0
    total_fresh_trades = 0
    max_fresh_trades = 0
    low_n_metric_explosions: list[dict[str, Any]] = []

    min_pf_trades = int(ssot["ranking_safety"]["min_trades_for_profit_factor_ranking"])
    pf_cap = float(ssot["ranking_safety"]["profit_factor_cap_for_score"])
    payoff_cap = float(ssot["ranking_safety"]["payoff_ratio_cap_for_score"])

    for summary_path in exact_paths:
        summary = strict_json(summary_path)
        strategy_id = str(summary.get("strategy_id") or summary_path.parent.name)
        accepted_total += int(summary.get("accepted_count") or 0)
        strategy_candidates: list[dict[str, Any]] = []

        for item_path, item_value in walk_items(summary):
            key = item_path.rsplit(".", 1)[-1].lower()
            observed_keys[key] += 1
            if any(token in key for token in ("cost", "fee", "slip", "funding", "latency")):
                observed_cost_values.setdefault(key, set()).add(str(item_value))

        for index, result in enumerate(summary.get("results") or []):
            if not isinstance(result, Mapping):
                continue
            evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), Mapping) else {}
            metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), Mapping) else {}
            candidate = result.get("candidate") if isinstance(result.get("candidate"), Mapping) else {}
            failures = [str(value) for value in evaluation.get("failure_reasons") or []]
            failure_reasons.update(failures)

            fresh_trades = int(metric(metrics, "fresh", "trade_count") or 0)
            total_fresh_trades += fresh_trades
            max_fresh_trades = max(max_fresh_trades, fresh_trades)
            if fresh_trades > 0:
                fresh_nonzero_candidates += 1

            all_trades = int(metric(metrics, "all", "trade_count") or 0)
            profit_factor = metric(metrics, "all", "net_profit_factor")
            payoff = metric(metrics, "all", "payoff_ratio")
            explosion_reasons: list[str] = []
            if all_trades < min_pf_trades and finite(profit_factor) and float(profit_factor) > pf_cap:
                explosion_reasons.append("LOW_N_PROFIT_FACTOR_EXPLOSION")
            if all_trades < min_pf_trades and finite(payoff) and float(payoff) > payoff_cap:
                explosion_reasons.append("LOW_N_PAYOFF_EXPLOSION")
            if explosion_reasons:
                low_n_metric_explosions.append({
                    "strategy_id": strategy_id,
                    "result_index": index,
                    "trade_count": all_trades,
                    "profit_factor": profit_factor,
                    "payoff_ratio": payoff,
                    "reasons": explosion_reasons,
                })

            row = {
                "strategy_id": strategy_id,
                "result_index": index,
                "candidate_sha256": stable_sha(candidate),
                "family": candidate.get("family") or summary.get("family"),
                "lane": candidate.get("lane"),
                "mode": result.get("mode"),
                "gate_id": ((candidate.get("gate") or {}).get("gate_id") if isinstance(candidate.get("gate"), Mapping) else None),
                "exit_id": ((candidate.get("exit") or {}).get("exit_id") if isinstance(candidate.get("exit"), Mapping) else None),
                "pass": bool(evaluation.get("pass")),
                "score_raw": evaluation.get("score"),
                "failure_reasons": "|".join(failures),
            }
            for phase in ("selection", "validation", "holdout", "fresh", "all"):
                for name in (
                    "trade_count", "win_rate_pct", "net_return_pct_sum", "net_profit_factor",
                    "payoff_ratio", "max_drawdown_pct", "average_win_pct", "average_loss_pct_abs",
                ):
                    row[f"{phase}_{name}"] = metric(metrics, phase, name)
            all_rows.append(row)
            strategy_candidates.append(row)

        if strategy_candidates:
            ranked = sorted(
                strategy_candidates,
                key=lambda value: float(value["score_raw"]) if finite(value.get("score_raw")) else float("-inf"),
                reverse=True,
            )
            best_rows.append(ranked[0])

    mfe_present = any("mfe" in key for key in observed_keys)
    mae_present = any("mae" in key for key in observed_keys)
    cost_stress_present = any(
        any(token in key for token in ("stress", "scenario", "multiplier"))
        and any(cost in key for cost in ("cost", "fee", "slip", "funding", "latency"))
        for key in observed_keys
    )
    funding_present = any("funding" in key for key in observed_keys)
    latency_present = any("latency" in key for key in observed_keys)

    blockers: list[str] = []
    warnings: list[str] = []
    if final.get("state") != "PASS" or final.get("blockers"):
        blockers.append("STRUCTURE_LOCK_NOT_PASS")
    if len(exact_paths) != 25:
        blockers.append(f"EXACT_SUMMARY_COUNT:{len(exact_paths)}")
    if total_fresh_trades == 0:
        blockers.append("NO_FRESH_TRADES_ACROSS_ALL_CANDIDATES")
    if accepted_total == 0:
        blockers.append("NO_ACCEPTED_CANDIDATES")
    if not (mfe_present and mae_present):
        blockers.append("MFE_MAE_EVIDENCE_MISSING")
    if not cost_stress_present:
        blockers.append("COST_STRESS_GRID_MISSING")
    if not funding_present:
        blockers.append("FUNDING_STRESS_MISSING")
    if not latency_present:
        blockers.append("LATENCY_STRESS_MISSING")
    if low_n_metric_explosions:
        blockers.append(f"LOW_SAMPLE_METRIC_EXPLOSION:{len(low_n_metric_explosions)}")
    if int(roster.get("accepted_unique_strategy_count") or 0) == 0:
        warnings.append("FINAL_ROSTER_EMPTY")

    fields = [
        "strategy_id", "result_index", "candidate_sha256", "family", "lane", "mode", "gate_id", "exit_id",
        "pass", "score_raw", "failure_reasons",
    ]
    for phase in ("selection", "validation", "holdout", "fresh", "all"):
        for name in (
            "trade_count", "win_rate_pct", "net_return_pct_sum", "net_profit_factor",
            "payoff_ratio", "max_drawdown_pct", "average_win_pct", "average_loss_pct_abs",
        ):
            fields.append(f"{phase}_{name}")

    out.mkdir(parents=True, exist_ok=True)
    csv_write(out / "all_candidates.csv", all_rows, fields)
    csv_write(out / "strategy_best.csv", best_rows, fields)
    atomic_json(out / "low_sample_metric_explosions.json", {
        "count": len(low_n_metric_explosions),
        "rows": low_n_metric_explosions,
    })
    atomic_json(out / "failure_reason_counts.json", dict(failure_reasons.most_common()))

    payload = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_POSTLOCK_AUDIT_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "structure_lock_state": final.get("state"),
        "structure_lock_sha256": sha256(final_path),
        "authority_run_id": os.environ.get("AUTHORITY_RUN_ID"),
        "authority_run_attempt": os.environ.get("AUTHORITY_RUN_ATTEMPT"),
        "authority_source_head_sha": os.environ.get("AUTHORITY_SOURCE_HEAD_SHA"),
        "authority_data_set_sha256": ((orchestrator.get("lineage") or {}).get("data_set_sha256") if isinstance(orchestrator.get("lineage"), Mapping) else None),
        "ssot_sha256": sha256(ssot_path),
        "exact_summary_count": len(exact_paths),
        "candidate_result_count": len(all_rows),
        "accepted_candidate_count": accepted_total,
        "final_roster_count": int(roster.get("accepted_unique_strategy_count") or 0),
        "fresh_nonzero_candidate_count": fresh_nonzero_candidates,
        "fresh_trade_count_total": total_fresh_trades,
        "fresh_trade_count_max_per_candidate": max_fresh_trades,
        "mfe_present": mfe_present,
        "mae_present": mae_present,
        "cost_stress_grid_present": cost_stress_present,
        "funding_stress_present": funding_present,
        "latency_stress_present": latency_present,
        "observed_cost_fields": {key: sorted(values)[:20] for key, values in sorted(observed_cost_values.items())},
        "low_sample_metric_explosion_count": len(low_n_metric_explosions),
        "top_failure_reasons": dict(failure_reasons.most_common(20)),
        "gemini_allowed": False if blockers else True,
        "auto_improvement_allowed": False if blockers else True,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
        "blockers": blockers,
        "warnings": warnings,
        "next": "BUILD_FRESH_DATA_MFE_MAE_AND_COST_EVIDENCE" if blockers else "GLOBAL_PERFORMANCE_REVIEW",
    }
    atomic_json(out / "summary.json", payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
