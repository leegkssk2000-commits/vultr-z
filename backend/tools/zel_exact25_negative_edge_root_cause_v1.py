from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_EXACT25_NEGATIVE_EDGE_ROOT_CAUSE_V1"
SCHEMA = "zel.exact25.negative_edge_root_cause.receipt.v1"
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")


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


def row_values(row: Mapping[str, Any]) -> dict[str, Any]:
    risk = finite(row.get("initial_risk_usdt"))
    gross_pnl = finite(row.get("gross_pnl_usdt"))
    realized = finite(row.get("realized_R"))
    net = finite(row.get("realized_R_including_funding_estimate"))
    if net is None:
        net = realized
    gross_r = ratio(gross_pnl, risk) if gross_pnl is not None and risk and risk > 0 else None
    if gross_r is None:
        gross_r = realized
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "window_id": str(row.get("window_id") or ""),
        "side": str(row.get("side") or "unknown").lower(),
        "symbol": str(row.get("symbol") or "unknown"),
        "exit_reason": str(row.get("exit_reason") or "unknown"),
        "gross_R": gross_r,
        "realized_R": realized,
        "net_R": net,
        "mfe_R": finite(row.get("MFE_R")),
        "mae_R": finite(row.get("MAE_R")),
        "time_exposure_min": finite(row.get("time_exposure_min")),
        "fee": finite(row.get("fee")),
        "slippage": finite(row.get("slippage")),
        "funding_R": (realized - net) if realized is not None and net is not None else None,
        "nonfunding_cost_R": (gross_r - realized) if gross_r is not None and realized is not None else None,
    }


def metrics(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values = [finite(row.get(field)) for row in rows]
    clean = [value for value in values if value is not None]
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
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss_abs = abs(sum(losses) / len(losses)) if losses else 0.0
    payoff = ratio(average_win, average_loss_abs)
    return {
        "sample_count": len(clean),
        "net_R": sum(clean),
        "profit_factor": ratio(gross_win, gross_loss),
        "win_rate_pct": ratio(len(wins) * 100.0, len(clean)),
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss_abs,
        "payoff_ratio": payoff,
        "expectancy_R": ratio(sum(clean), len(clean)),
        "max_drawdown_R": max_dd,
    }


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gross = metrics(rows, "gross_R")
    realized = metrics(rows, "realized_R")
    net = metrics(rows, "net_R")
    nonfunding_cost = sum(value for row in rows if (value := finite(row.get("nonfunding_cost_R"))) is not None)
    funding_cost = sum(value for row in rows if (value := finite(row.get("funding_R"))) is not None)
    mfes = [value for row in rows if (value := finite(row.get("mfe_R"))) is not None]
    maes = [value for row in rows if (value := finite(row.get("mae_R"))) is not None]
    exposures = [value for row in rows if (value := finite(row.get("time_exposure_min"))) is not None]
    return {
        "gross": gross,
        "realized_ex_funding": realized,
        "net_including_funding": net,
        "cost_drag_R": gross["net_R"] - net["net_R"],
        "nonfunding_cost_drag_R": nonfunding_cost,
        "funding_drag_R": funding_cost,
        "average_mfe_R": ratio(sum(mfes), len(mfes)),
        "average_mae_R": ratio(sum(maes), len(maes)),
        "average_time_exposure_min": ratio(sum(exposures), len(exposures)),
    }


def grouped(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key) or "unknown")].append(row)
    return {name: summarize_group(bucket) for name, bucket in sorted(buckets.items())}


def root_cause(policy: Mapping[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    thresholds = policy["thresholds"]
    by_strategy_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy_rows[row["strategy_id"]].append(row)
    strategy_summaries = {key: summarize_group(value) for key, value in by_strategy_rows.items()}
    eligible = [summary for summary in strategy_summaries.values() if summary["net_including_funding"]["sample_count"] >= int(thresholds["minimum_strategy_sample"])]
    gross_negative = sum(summary["gross"]["net_R"] < 0 for summary in eligible)
    cost_flip = sum(summary["gross"]["net_R"] > 0 and summary["net_including_funding"]["net_R"] <= 0 for summary in eligible)
    strategy_count = len(eligible)
    gross_negative_share = ratio(gross_negative * 100.0, strategy_count)
    cost_flip_share = ratio(cost_flip * 100.0, strategy_count)

    mfe_threshold = float(thresholds["mfe_opportunity_R"])
    leak_realized_max = float(thresholds["exit_leak_realized_R_max"])
    entry_mfe_max = float(thresholds["entry_failure_mfe_R_max"])
    exit_leaks = [row for row in rows if finite(row.get("mfe_R")) is not None and float(row["mfe_R"]) >= mfe_threshold and finite(row.get("net_R")) is not None and float(row["net_R"]) <= leak_realized_max]
    entry_failures = [row for row in rows if finite(row.get("mfe_R")) is not None and float(row["mfe_R"]) <= entry_mfe_max and finite(row.get("net_R")) is not None and float(row["net_R"]) < 0]
    exit_leak_share = ratio(len(exit_leaks) * 100.0, len(rows))
    entry_failure_share = ratio(len(entry_failures) * 100.0, len(rows))

    side = grouped(rows, "side")
    long_net = side.get("long", {}).get("net_including_funding", {}).get("net_R", 0.0)
    short_net = side.get("short", {}).get("net_including_funding", {}).get("net_R", 0.0)
    side_gap = abs(float(long_net) - float(short_net))

    window = grouped(rows, "window_id")
    window_signs = []
    for name in WINDOWS:
        summary = window.get(name)
        if summary and summary["net_including_funding"]["sample_count"] >= int(thresholds["minimum_window_sample"]):
            value = summary["net_including_funding"]["net_R"]
            window_signs.append(1 if value > 0 else -1 if value < 0 else 0)
    sign_disagreement = len(set(window_signs)) > int(thresholds["window_sign_disagreement_count"])

    total = summarize_group(rows)
    missing_critical = sum(
        1
        for row in rows
        if finite(row.get("gross_R")) is None
        or finite(row.get("realized_R")) is None
        or finite(row.get("net_R")) is None
    )
    causes = [
        {
            "cause": "INTEGRITY_AND_UNIT_AUDIT",
            "score": 100.0 if missing_critical else 0.0,
            "evidence": {"missing_critical_rows": missing_critical, "trade_count": len(rows)},
        },
        {
            "cause": "COST_FREQUENCY_AUDIT",
            "score": max(cost_flip_share, min(100.0, abs(total["cost_drag_R"]) / max(abs(total["gross"]["net_R"]), 1.0) * 100.0)),
            "evidence": {"cost_flip_strategy_share_pct": cost_flip_share, "total_cost_drag_R": total["cost_drag_R"], "gross_net_R": total["gross"]["net_R"], "net_R": total["net_including_funding"]["net_R"]},
        },
        {
            "cause": "EXIT_CAPTURE_AUDIT",
            "score": exit_leak_share,
            "evidence": {"exit_leak_trade_share_pct": exit_leak_share, "exit_leak_trade_count": len(exit_leaks), "mfe_opportunity_R": mfe_threshold},
        },
        {
            "cause": "SIDE_DIRECTION_AUDIT",
            "score": min(100.0, side_gap / max(float(thresholds["side_net_R_gap_abs"]), 1.0) * 25.0),
            "evidence": {"long_net_R": long_net, "short_net_R": short_net, "side_net_R_gap_abs": side_gap},
        },
        {
            "cause": "REGIME_WINDOW_AUDIT",
            "score": 60.0 if sign_disagreement else 0.0,
            "evidence": {"window_signs": window_signs, "sign_disagreement": sign_disagreement},
        },
        {
            "cause": "ENTRY_QUALITY_AUDIT",
            "score": max(gross_negative_share, entry_failure_share),
            "evidence": {"gross_negative_strategy_share_pct": gross_negative_share, "entry_failure_trade_share_pct": entry_failure_share, "eligible_strategy_count": strategy_count},
        },
    ]
    priority = {name: index for index, name in enumerate(policy["routing_priority"])}
    causes.sort(key=lambda row: (-float(row["score"]), priority.get(str(row["cause"]), 999)))
    next_axis = str(causes[0]["cause"])
    return causes, next_axis


def run(policy: Mapping[str, Any], terminal_root: Path) -> dict[str, Any]:
    report = read_json(terminal_root / "report.json")
    raw_rows = load_rows(terminal_root / "trades.jsonl.gz")
    rows = [row_values(row) for row in raw_rows]
    strategy_ids = sorted({row["strategy_id"] for row in rows if row["strategy_id"]})
    checks = {
        "strategy_count": len(strategy_ids) == int(policy["expected_strategy_count"]),
        "closed_trade_count": len(rows) == int(policy["expected_closed_trade_count"]),
        "no_empty_strategy_id": all(row["strategy_id"] for row in rows),
        "all_windows_present": all(any(row["window_id"] == window for row in rows) for window in WINDOWS),
    }
    causes, next_axis = root_cause(policy, rows)
    by_strategy = grouped(rows, "strategy_id")
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_NEGATIVE_EDGE_ROOT_CAUSE_AUDIT" if all(checks.values()) else "HOLD_NEGATIVE_EDGE_INPUT_INTEGRITY",
        "checks": checks,
        "strategy_count": len(strategy_ids),
        "trade_count": len(rows),
        "terminal_report_sha256": stable_sha(report),
        "portfolio": summarize_group(rows),
        "by_strategy": by_strategy,
        "by_window": grouped(rows, "window_id"),
        "by_side": grouped(rows, "side"),
        "by_exit_reason": grouped(rows, "exit_reason"),
        "by_symbol": grouped(rows, "symbol"),
        "root_causes": causes,
        "next_research_axis": next_axis,
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
        "next": "BUILD_EXACT_SOURCE_" + next_axis,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    rows = [
        {"gross_R": 1.0, "realized_R": 0.8, "net_R": 0.7},
        {"gross_R": -0.5, "realized_R": -0.6, "net_R": -0.7},
    ]
    result = summarize_group(rows)
    assert result["gross"]["net_R"] == 0.5
    assert abs(result["cost_drag_R"] - 0.5) < 1e-12
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
