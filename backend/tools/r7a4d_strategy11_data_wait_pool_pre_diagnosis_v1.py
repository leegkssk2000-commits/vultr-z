from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_DATA_WAIT_POOL_PRE_DIAGNOSIS_V1"
PRIMARY = {"alpha_combo", "turtle_trend", "ema_ribbon_scalp"}
FRESH_WINDOWS = ("F1", "F2", "F3")
TARGET_TRADES = 12
BARS_PER_NEW_WINDOW = 480


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def trade_fingerprint(row: Mapping[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("window_id", "symbol", "signal_ts", "entry_ts", "exit_ts"))


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def gate_description(summary: Mapping[str, Any]) -> dict[str, Any]:
    candidate = summary.get("candidate") if isinstance(summary.get("candidate"), Mapping) else {}
    gate = candidate.get("gate") if isinstance(candidate.get("gate"), Mapping) else {}
    surgery = summary.get("surgery") if isinstance(summary.get("surgery"), Mapping) else None
    required = gate.get("required") if isinstance(gate.get("required"), list) else []
    forbidden = gate.get("forbidden") if isinstance(gate.get("forbidden"), list) else []
    dimensions = len(required) + len(forbidden) + (1 if surgery else 0)
    return {
        "gate_id": gate.get("gate_id"),
        "description": gate.get("description"),
        "required": required,
        "forbidden": forbidden,
        "surgery": surgery,
        "constraint_dimension_count": dimensions,
        "rejection_counts": "NOT_AVAILABLE_FROM_IMMUTABLE_EVIDENCE_AUTHORITY",
        "narrowest_gate_claim_allowed": False,
    }


def estimate_wait(trade_count: int) -> dict[str, Any]:
    if trade_count <= 0:
        return {
            "observed_trades_per_fresh_window": 0.0,
            "estimated_additional_windows_to_12": None,
            "estimated_additional_bars_to_12": None,
            "eta_state": "UNBOUNDED_FROM_ZERO_SIGNAL_SAMPLE",
        }
    rate = trade_count / len(FRESH_WINDOWS)
    remaining = max(0, TARGET_TRADES - trade_count)
    windows = math.ceil(remaining / rate) if remaining else 0
    return {
        "observed_trades_per_fresh_window": rate,
        "estimated_additional_windows_to_12": windows,
        "estimated_additional_bars_to_12": windows * BARS_PER_NEW_WINDOW,
        "eta_state": "RATE_BASED_DIAGNOSTIC_NOT_PERFORMANCE_FORECAST",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-run-id", required=True)
    ap.add_argument("--source-head-sha", required=True)
    args = ap.parse_args()

    root = Path(args.evidence_root).resolve()
    out = Path(args.out).resolve()
    summaries = sorted(root.glob("*/summary.json"))
    records: list[dict[str, Any]] = []
    signal_sets: dict[str, set[str]] = {}
    config_groups: dict[str, list[str]] = defaultdict(list)

    for summary_path in summaries:
        summary = load(summary_path)
        strategy_id = str(summary.get("strategy_id") or summary_path.parent.name)
        if strategy_id in PRIMARY:
            continue
        trades_path = summary_path.parent / "baseline_trades.json"
        if not trades_path.exists():
            raise RuntimeError(f"BASELINE_TRADES_MISSING:{strategy_id}")
        trades_doc = load(trades_path)
        trades = [dict(row) for row in trades_doc.get("trades", []) if isinstance(row, Mapping)]
        baseline = summary.get("baseline") if isinstance(summary.get("baseline"), Mapping) else {}
        trade_count = int(baseline.get("trade_count") or 0)
        if trade_count != len(trades):
            raise RuntimeError(f"TRADE_COUNT_MISMATCH:{strategy_id}:{trade_count}!={len(trades)}")

        by_symbol = Counter(str(row.get("symbol") or "UNKNOWN") for row in trades)
        by_window = Counter(str(row.get("window_id") or "UNKNOWN") for row in trades)
        signal_set = {trade_fingerprint(row) for row in trades}
        signal_sets[strategy_id] = signal_set
        candidate = summary.get("candidate") if isinstance(summary.get("candidate"), Mapping) else {}
        config_signature = stable_sha({"candidate": candidate, "surgery": summary.get("surgery"), "symbols": summary.get("symbols")})
        config_groups[config_signature].append(strategy_id)
        wait = estimate_wait(trade_count)
        classification = "NO_SIGNAL_DIAGNOSIS" if trade_count == 0 else ("LOW_FREQUENCY_DIAGNOSIS" if trade_count < TARGET_TRADES else "SAMPLE_READY_DIAGNOSIS")

        records.append({
            "strategy_id": strategy_id,
            "classification": classification,
            "authority_state": summary.get("state"),
            "authority_blockers": summary.get("blockers", []),
            "existing_fresh_trade_count": trade_count,
            "signal_count_by_window": {window: int(by_window.get(window, 0)) for window in FRESH_WINDOWS},
            "signal_count_by_symbol": dict(sorted(by_symbol.items())),
            "signal_density_per_480_bar_window": trade_count / len(FRESH_WINDOWS),
            "positive_fresh_windows_pct": baseline.get("positive_fresh_windows_pct"),
            "net_return_pct_sum": baseline.get("net_return_pct_sum"),
            "net_profit_factor": baseline.get("net_profit_factor"),
            "payoff_ratio": baseline.get("payoff_ratio"),
            "max_drawdown_pct": baseline.get("max_drawdown_pct"),
            "gate_diagnosis": gate_description(summary),
            "wait_estimate": wait,
            "signal_reachability": "UNOBSERVED_IN_3_FRESH_WINDOWS" if trade_count == 0 else "OBSERVED",
            "duplicate_signal_group": None,
            "near_duplicate_signal_peers": [],
            "source_lineage": {
                "source_run_id": str(args.source_run_id),
                "source_head_sha": str(args.source_head_sha),
                "summary_sha256": sha(summary_path),
                "baseline_trades_sha256": sha(trades_path),
                "authority_exact_summary_sha256": summary.get("authority_exact_summary_sha256"),
                "selected_authority_result_sha256": summary.get("selected_authority_result_sha256"),
                "candidate_config_sha256": config_signature,
            },
        })

    records.sort(key=lambda row: row["strategy_id"])
    if len(records) != 22:
        raise RuntimeError(f"DATA_WAIT_POOL_SIZE:{len(records)}!=22")

    duplicate_groups: list[dict[str, Any]] = []
    group_index = 0
    for signature, members in sorted(config_groups.items()):
        if len(members) > 1:
            group_index += 1
            group_id = f"CONFIG_DUP_{group_index:02d}"
            duplicate_groups.append({"group_id": group_id, "kind": "CONFIG_EXACT", "members": sorted(members), "config_sha256": signature})
            for row in records:
                if row["strategy_id"] in members:
                    row["duplicate_signal_group"] = group_id

    for i, left in enumerate(records):
        left_id = left["strategy_id"]
        if not signal_sets[left_id]:
            continue
        for right in records[i + 1:]:
            right_id = right["strategy_id"]
            if not signal_sets[right_id]:
                continue
            score = jaccard(signal_sets[left_id], signal_sets[right_id])
            if score > 0.85:
                left["near_duplicate_signal_peers"].append({"strategy_id": right_id, "jaccard": score})
                right["near_duplicate_signal_peers"].append({"strategy_id": left_id, "jaccard": score})
                duplicate_groups.append({"kind": "SIGNAL_JACCARD_GT_085", "members": [left_id, right_id], "jaccard": score})

    class_counts = Counter(row["classification"] for row in records)
    total_trades = sum(row["existing_fresh_trade_count"] for row in records)
    zero_signal = [row["strategy_id"] for row in records if row["existing_fresh_trade_count"] == 0]
    ranked_wait = sorted(
        [row for row in records if row["wait_estimate"]["estimated_additional_windows_to_12"] is not None],
        key=lambda row: (row["wait_estimate"]["estimated_additional_windows_to_12"], -row["existing_fresh_trade_count"], row["strategy_id"]),
    )
    next_likely = [row["strategy_id"] for row in ranked_wait[:5]]

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_PRE_DIAGNOSIS",
        "pool_size": len(records),
        "primary_excluded": sorted(PRIMARY),
        "source_authority": {
            "run_id": str(args.source_run_id),
            "head_sha": str(args.source_head_sha),
            "artifact_batches": 5,
            "fresh_windows": list(FRESH_WINDOWS),
            "bars_per_new_window": BARS_PER_NEW_WINDOW,
        },
        "counts": {
            "total_existing_fresh_trades": total_trades,
            "classifications": dict(sorted(class_counts.items())),
            "zero_signal_strategy_count": len(zero_signal),
            "duplicate_group_count": len(duplicate_groups),
        },
        "zero_signal_strategies": zero_signal,
        "next_likely_to_reach_12_by_observed_rate": next_likely,
        "limitations": [
            "GATE_REJECTION_COUNTS_NOT_PRESENT_IN_IMMUTABLE_EVIDENCE_ARTIFACTS",
            "WAIT_ESTIMATES_ARE_RATE_DIAGNOSTICS_NOT_PERFORMANCE_FORECASTS",
            "ZERO_SIGNAL_STRATEGIES_HAVE_NO_FINITE_ETA_FROM_CURRENT_AUTHORITY",
        ],
        "next": "W1_PIPELINE_DRY_RUN",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }

    write_json(out / "summary.json", final)
    write_json(out / "strategies.json", {"rows": records})
    write_json(out / "duplicate_groups.json", {"rows": duplicate_groups})
    out.mkdir(parents=True, exist_ok=True)
    fields = [
        "strategy_id", "classification", "existing_fresh_trade_count", "signal_density_per_480_bar_window",
        "positive_fresh_windows_pct", "net_return_pct_sum", "net_profit_factor", "payoff_ratio", "max_drawdown_pct",
        "estimated_additional_windows_to_12", "estimated_additional_bars_to_12", "signal_reachability",
        "candidate_config_sha256",
    ]
    with (out / "strategies.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({
                "strategy_id": row["strategy_id"],
                "classification": row["classification"],
                "existing_fresh_trade_count": row["existing_fresh_trade_count"],
                "signal_density_per_480_bar_window": row["signal_density_per_480_bar_window"],
                "positive_fresh_windows_pct": row["positive_fresh_windows_pct"],
                "net_return_pct_sum": row["net_return_pct_sum"],
                "net_profit_factor": row["net_profit_factor"],
                "payoff_ratio": row["payoff_ratio"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "estimated_additional_windows_to_12": row["wait_estimate"]["estimated_additional_windows_to_12"],
                "estimated_additional_bars_to_12": row["wait_estimate"]["estimated_additional_bars_to_12"],
                "signal_reachability": row["signal_reachability"],
                "candidate_config_sha256": row["source_lineage"]["candidate_config_sha256"],
            })

    print(json.dumps({"state": final["state"], "pool": len(records), "trades": total_trades, "zero_signal": len(zero_signal), "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
