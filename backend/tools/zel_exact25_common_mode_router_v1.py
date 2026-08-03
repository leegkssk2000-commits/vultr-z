from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_EXACT25_COMMON_MODE_ROUTER_V1"
SCHEMA = "zel.exact25.common_mode_router.receipt.v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    risk = finite(row.get("initial_risk_usdt"))
    gross_pnl = finite(row.get("gross_pnl_usdt"))
    realized = finite(row.get("realized_R"))
    net = finite(row.get("realized_R_including_funding_estimate"))
    if net is None:
        net = realized
    gross_r = ratio(gross_pnl, risk) if gross_pnl is not None and risk and risk > 0 else realized
    cost_drag = gross_r - net if gross_r is not None and net is not None else None
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "window_id": str(row.get("window_id") or ""),
        "symbol": str(row.get("symbol") or "unknown"),
        "side": str(row.get("side") or "unknown").lower(),
        "exit_reason": str(row.get("exit_reason") or "unknown"),
        "gross_R": gross_r,
        "realized_R": realized,
        "net_R": net,
        "cost_drag_R": cost_drag,
        "mfe_R": finite(row.get("MFE_R")),
        "mae_R": finite(row.get("MAE_R")),
        "time_exposure_min": finite(row.get("time_exposure_min")),
    }


def metrics(values: Iterable[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    wins = [value for value in clean if value > 0]
    losses = [value for value in clean if value < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in clean:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    average_win = ratio(sum(wins), len(wins))
    average_loss_abs = ratio(abs(sum(losses)), len(losses))
    return {
        "sample_count": len(clean),
        "net_R": sum(clean),
        "profit_factor": ratio(gross_win, gross_loss),
        "win_rate_pct": ratio(len(wins) * 100.0, len(clean)),
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss_abs,
        "payoff_ratio": ratio(average_win, average_loss_abs),
        "expectancy_R": ratio(sum(clean), len(clean)),
        "max_drawdown_R": max_dd,
    }


def scenario_summary(
    rows: Sequence[Mapping[str, Any]],
    values: Sequence[float],
    windows: Sequence[str],
    baseline_counts: Mapping[str, int],
) -> dict[str, Any]:
    if len(rows) != len(values):
        raise RuntimeError("SCENARIO_ROW_VALUE_LENGTH_MISMATCH")
    by_window: dict[str, Any] = {}
    for window in windows:
        selected = [value for row, value in zip(rows, values) if row["window_id"] == window]
        summary = metrics(selected)
        base_count = int(baseline_counts.get(window) or 0)
        summary["retention_pct"] = ratio(summary["sample_count"] * 100.0, base_count)
        by_window[window] = summary
    all_metrics = metrics(values)
    all_metrics["retention_pct"] = ratio(
        all_metrics["sample_count"] * 100.0,
        sum(int(value) for value in baseline_counts.values()),
    )
    return {"all": all_metrics, "by_window": by_window}


def gate(summary: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    contract = policy["positive_gate"]
    blockers: list[str] = []
    for window in policy["windows"]:
        metrics_row = summary["by_window"][window]
        prefix = window.upper()
        if int(metrics_row["sample_count"]) < int(contract["minimum_window_trade_count"]):
            blockers.append(f"{prefix}:SAMPLE_BELOW_MIN")
        if float(metrics_row["retention_pct"]) < float(contract["minimum_retention_pct"]):
            blockers.append(f"{prefix}:RETENTION_BELOW_MIN")
        if float(metrics_row["net_R"]) <= float(contract["net_R_gt"]):
            blockers.append(f"{prefix}:NET_R_NOT_POSITIVE")
        if float(metrics_row["profit_factor"]) < float(contract["profit_factor_gte"]):
            blockers.append(f"{prefix}:PF_BELOW_ONE")
        if float(metrics_row["expectancy_R"]) <= float(contract["expectancy_R_gt"]):
            blockers.append(f"{prefix}:EXPECTANCY_NOT_POSITIVE")
        if float(metrics_row["payoff_ratio"]) < float(contract["payoff_ratio_gte"]):
            blockers.append(f"{prefix}:PAYOFF_BELOW_ONE")
    return not blockers, blockers


def time_bucket(value: float | None, cutoffs: Sequence[float]) -> str:
    if value is None:
        return "unknown"
    lower = 0.0
    for upper in cutoffs:
        if value <= upper:
            return f"{int(lower)}-{int(upper)}m"
        lower = upper
    return f">{int(cutoffs[-1])}m"


def grouped_net(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = finite(row.get("net_R"))
        if value is not None:
            buckets[str(row.get(key) or "unknown")].append(value)
    return {name: metrics(values) for name, values in sorted(buckets.items())}


def run(policy: Mapping[str, Any], terminal_root: Path) -> dict[str, Any]:
    raw_rows = load_rows(terminal_root / "trades.jsonl.gz")
    rows = [normalize_row(row) for row in raw_rows]
    windows = [str(value) for value in policy["windows"]]
    strategies = sorted({row["strategy_id"] for row in rows if row["strategy_id"]})
    baseline_counts = {
        window: sum(row["window_id"] == window for row in rows) for window in windows
    }
    missing = sum(
        finite(row.get("gross_R")) is None
        or finite(row.get("net_R")) is None
        or not row["strategy_id"]
        for row in rows
    )
    checks = {
        "strategy_count": len(strategies) == int(policy["expected_strategy_count"]),
        "trade_count": len(rows) == int(policy["expected_closed_trade_count"]),
        "all_windows_present": all(baseline_counts[window] > 0 for window in windows),
        "critical_fields_complete": missing == 0,
    }

    baseline_values = [float(row["net_R"]) for row in rows]
    baseline = scenario_summary(rows, baseline_values, windows, baseline_counts)
    baseline_pass, baseline_blockers = gate(baseline, policy)

    cost_scenarios: list[dict[str, Any]] = []
    for scale in policy["diagnostic_scenarios"]["cost_scales"]:
        values = [
            float(row["gross_R"]) - float(scale) * float(row["cost_drag_R"])
            for row in rows
        ]
        summary = scenario_summary(rows, values, windows, baseline_counts)
        passed, blockers = gate(summary, policy)
        cost_scenarios.append(
            {"cost_scale": float(scale), "summary": summary, "positive_gate": passed, "blockers": blockers}
        )

    side_scenarios: list[dict[str, Any]] = []
    for side in ("long", "short"):
        selected_rows = [row for row in rows if row["side"] == side]
        values = [float(row["net_R"]) for row in selected_rows]
        summary = scenario_summary(selected_rows, values, windows, baseline_counts)
        passed, blockers = gate(summary, policy)
        side_scenarios.append(
            {"side": side, "summary": summary, "positive_gate": passed, "blockers": blockers}
        )

    exit_scenarios: list[dict[str, Any]] = []
    for fraction in policy["diagnostic_scenarios"]["exit_mfe_capture_fractions"]:
        values: list[float] = []
        for row in rows:
            current = float(row["net_R"])
            mfe = finite(row.get("mfe_R"))
            cost = float(row["cost_drag_R"])
            ceiling = current if mfe is None else max(current, float(fraction) * mfe - cost)
            values.append(ceiling)
        summary = scenario_summary(rows, values, windows, baseline_counts)
        passed, blockers = gate(summary, policy)
        exit_scenarios.append(
            {
                "mfe_capture_fraction": float(fraction),
                "ceiling_only_noncausal": True,
                "summary": summary,
                "positive_gate": passed,
                "blockers": blockers,
            }
        )

    entry_scenarios: list[dict[str, Any]] = []
    for minimum_mfe in policy["diagnostic_scenarios"]["entry_oracle_mfe_minimums"]:
        selected_rows = [
            row for row in rows
            if finite(row.get("mfe_R")) is not None and float(row["mfe_R"]) >= float(minimum_mfe)
        ]
        values = [float(row["net_R"]) for row in selected_rows]
        summary = scenario_summary(selected_rows, values, windows, baseline_counts)
        passed, blockers = gate(summary, policy)
        entry_scenarios.append(
            {
                "minimum_future_mfe_R": float(minimum_mfe),
                "ceiling_only_noncausal": True,
                "summary": summary,
                "positive_gate": passed,
                "blockers": blockers,
            }
        )

    time_rows = [
        {**row, "time_bucket": time_bucket(finite(row.get("time_exposure_min")), policy["diagnostic_scenarios"]["time_exposure_bins_min"])}
        for row in rows
    ]
    baseline_positive_windows = [
        window for window in windows if baseline["by_window"][window]["net_R"] > 0
    ]

    route = "STRUCTURAL_STRATEGY_REBUILD"
    selected_evidence: dict[str, Any] = {}
    if not all(checks.values()):
        route = "INTEGRITY_AND_UNIT_REPAIR"
        selected_evidence = {"checks": checks, "missing_critical_rows": missing}
    else:
        passing_sides = [scenario for scenario in side_scenarios if scenario["positive_gate"]]
        passing_cost = [scenario for scenario in cost_scenarios if scenario["positive_gate"]]
        passing_exit = [scenario for scenario in exit_scenarios if scenario["positive_gate"]]
        passing_entry = [scenario for scenario in entry_scenarios if scenario["positive_gate"]]
        if passing_sides:
            route = "SIDE_DIRECTION_EXACT_REPLAY"
            selected_evidence = passing_sides[0]
        elif passing_cost:
            best_realistic = max(passing_cost, key=lambda row: row["cost_scale"])
            route = "COST_FREQUENCY_REDESIGN"
            selected_evidence = best_realistic
        elif passing_exit:
            route = "EXIT_CAPTURE_INTRATRADE_REPLAY"
            selected_evidence = min(passing_exit, key=lambda row: row["mfe_capture_fraction"])
        elif passing_entry:
            route = "ENTRY_QUALITY_CAUSAL_FEATURE_SEARCH"
            selected_evidence = min(passing_entry, key=lambda row: row["minimum_future_mfe_R"])
        elif baseline_positive_windows:
            route = "REGIME_WINDOW_SPECIALIZATION"
            selected_evidence = {"positive_windows": baseline_positive_windows}

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_COMMON_MODE_ROUTE_SELECTED" if all(checks.values()) else "HOLD_COMMON_MODE_INPUT_INTEGRITY",
        "checks": checks,
        "strategy_count": len(strategies),
        "trade_count": len(rows),
        "baseline": baseline,
        "baseline_positive_gate": baseline_pass,
        "baseline_blockers": baseline_blockers,
        "cost_scenarios": cost_scenarios,
        "side_scenarios": side_scenarios,
        "exit_capture_ceiling_scenarios": exit_scenarios,
        "entry_oracle_ceiling_scenarios": entry_scenarios,
        "by_strategy": grouped_net(rows, "strategy_id"),
        "by_symbol": grouped_net(rows, "symbol"),
        "by_side": grouped_net(rows, "side"),
        "by_exit_reason": grouped_net(rows, "exit_reason"),
        "by_time_exposure": grouped_net(time_rows, "time_bucket"),
        "selected_route": route,
        "selected_route_evidence": selected_evidence,
        "diagnostic_oracles_are_ceiling_only": True,
        "oracle_promotion_forbidden": True,
        "exact_causal_replay_required": True,
        "raw_trade_rows_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "BUILD_EXACT_SOURCE_" + route,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    result = metrics([2.0, -1.0, 1.0, -0.5])
    assert result["sample_count"] == 4
    assert result["net_R"] == 1.5
    assert result["profit_factor"] == 2.0
    assert result["payoff_ratio"] == 2.0
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy or not args.terminal_root:
        parser.error("--policy and --terminal-root are required")
    receipt = run(read_json(args.policy), args.terminal_root.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
