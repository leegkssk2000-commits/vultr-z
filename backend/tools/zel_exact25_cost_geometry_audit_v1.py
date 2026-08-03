from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_COST_GEOMETRY_AUDIT_V1"
SCHEMA = "zel.exact25.cost_geometry.audit.v1"


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


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def normalize(row: Mapping[str, Any]) -> dict[str, Any]:
    risk = finite(row.get("initial_risk_usdt"))
    entry = finite(row.get("entry_price"))
    qty = finite(row.get("original_qty")) or finite(row.get("qty"))
    notional = entry * qty if entry is not None and qty is not None else None
    gross_pnl = finite(row.get("gross_pnl_usdt"))
    realized = finite(row.get("realized_R"))
    net = finite(row.get("realized_R_including_funding_estimate"))
    fee = finite(row.get("fee")) or 0.0
    slippage = finite(row.get("slippage")) or 0.0
    funding = finite(row.get("funding_pnl_estimate_usdt")) or 0.0
    gross_R = (
        gross_pnl / risk
        if gross_pnl is not None and risk is not None and risk > 0
        else realized
    )
    net_R = net if net is not None else realized
    fee_R = fee / risk if risk is not None and risk > 0 else None
    slippage_R = slippage / risk if risk is not None and risk > 0 else None
    funding_R = funding / risk if risk is not None and risk > 0 else None
    cost_drag_R = (
        gross_R - net_R
        if gross_R is not None and net_R is not None
        else None
    )
    modeled_cost_R = (
        fee_R + slippage_R - funding_R
        if fee_R is not None and slippage_R is not None and funding_R is not None
        else None
    )
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "window_id": str(row.get("window_id") or ""),
        "symbol": str(row.get("symbol") or "unknown"),
        "side": str(row.get("side") or "unknown"),
        "risk_usdt": risk,
        "entry_notional_usdt": notional,
        "gross_R": gross_R,
        "net_R": net_R,
        "fee_R": fee_R,
        "slippage_R": slippage_R,
        "funding_R": funding_R,
        "cost_drag_R": cost_drag_R,
        "modeled_cost_R": modeled_cost_R,
        "accounting_error_R": (
            cost_drag_R - modeled_cost_R
            if cost_drag_R is not None and modeled_cost_R is not None
            else None
        ),
        "risk_distance_pct_of_notional": (
            risk / notional * 100.0
            if risk is not None and notional is not None and notional > 0
            else None
        ),
        "execution_cost_bps_of_notional": (
            (fee + slippage) / notional * 10000.0
            if notional is not None and notional > 0
            else None
        ),
        "MFE_R": finite(row.get("MFE_R")),
        "MAE_R": finite(row.get("MAE_R")),
        "time_exposure_min": finite(row.get("time_exposure_min")),
    }


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def values(key: str) -> list[float]:
        return [
            float(value)
            for row in rows
            if (value := finite(row.get(key))) is not None
        ]

    gross = values("gross_R")
    net = values("net_R")
    cost = values("cost_drag_R")
    risk_pct = values("risk_distance_pct_of_notional")
    cost_bps = values("execution_cost_bps_of_notional")
    errors = [abs(value) for value in values("accounting_error_R")]
    mfe = values("MFE_R")
    cost_flip_count = sum(
        1
        for row in rows
        if finite(row.get("gross_R")) is not None
        and finite(row.get("net_R")) is not None
        and float(row["gross_R"]) > 0
        and float(row["net_R"]) <= 0
    )
    gross_positive = sum(value > 0 for value in gross)
    return {
        "sample_count": len(rows),
        "gross_net_R": sum(gross),
        "net_R": sum(net),
        "total_cost_drag_R": sum(cost),
        "average_cost_drag_R": statistics.fmean(cost) if cost else None,
        "median_cost_drag_R": statistics.median(cost) if cost else None,
        "p90_cost_drag_R": quantile(cost, 0.9),
        "average_risk_distance_pct_of_notional": (
            statistics.fmean(risk_pct) if risk_pct else None
        ),
        "median_risk_distance_pct_of_notional": (
            statistics.median(risk_pct) if risk_pct else None
        ),
        "p10_risk_distance_pct_of_notional": quantile(risk_pct, 0.1),
        "average_execution_cost_bps_of_notional": (
            statistics.fmean(cost_bps) if cost_bps else None
        ),
        "max_abs_accounting_error_R": max(errors) if errors else None,
        "accounting_mismatch_count_gt_1e_8": sum(value > 1e-8 for value in errors),
        "gross_positive_trade_count": gross_positive,
        "gross_positive_to_net_nonpositive_count": cost_flip_count,
        "gross_positive_to_net_nonpositive_share_pct": (
            cost_flip_count / gross_positive * 100.0 if gross_positive else 0.0
        ),
        "average_MFE_R": statistics.fmean(mfe) if mfe else None,
        "average_cost_to_MFE_ratio": (
            statistics.fmean(
                float(row["cost_drag_R"]) / float(row["MFE_R"])
                for row in rows
                if finite(row.get("cost_drag_R")) is not None
                and finite(row.get("MFE_R")) is not None
                and float(row["MFE_R"]) > 0
            )
            if any(
                finite(row.get("cost_drag_R")) is not None
                and finite(row.get("MFE_R")) is not None
                and float(row["MFE_R"]) > 0
                for row in rows
            )
            else None
        ),
    }


def grouped(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    return {name: metrics(items) for name, items in sorted(groups.items())}


def run(terminal_root: Path) -> dict[str, Any]:
    rows = [normalize(row) for row in load_rows(terminal_root / "trades.jsonl.gz")]
    complete = [
        row
        for row in rows
        if all(
            finite(row.get(key)) is not None
            for key in ("gross_R", "net_R", "cost_drag_R", "modeled_cost_R")
        )
    ]
    portfolio = metrics(complete)
    by_strategy = grouped(complete, "strategy_id")
    cost_flip_strategies = sorted(
        (
            {"strategy_id": strategy_id, **summary}
            for strategy_id, summary in by_strategy.items()
            if float(summary.get("gross_net_R") or 0.0) > 0
            and float(summary.get("net_R") or 0.0) < 0
        ),
        key=lambda row: float(row["total_cost_drag_R"]),
        reverse=True,
    )
    accounting_ok = int(portfolio["accounting_mismatch_count_gt_1e_8"] or 0) == 0
    if not accounting_ok:
        route = "COST_ACCOUNTING_INTEGRITY_REPAIR"
    elif cost_flip_strategies:
        route = "COST_GEOMETRY_AND_TURNOVER_REDESIGN"
    elif float(portfolio.get("gross_net_R") or 0.0) > 0 and float(
        portfolio.get("net_R") or 0.0
    ) < 0:
        route = "PORTFOLIO_COST_FLOOR_GATE"
    else:
        route = "COST_NOT_PRIMARY"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_COST_GEOMETRY_AUDIT",
        "trade_count": len(rows),
        "complete_trade_count": len(complete),
        "portfolio": portfolio,
        "by_strategy": by_strategy,
        "by_window": grouped(complete, "window_id"),
        "by_symbol": grouped(complete, "symbol"),
        "by_side": grouped(complete, "side"),
        "cost_flip_strategies": cost_flip_strategies,
        "selected_route": route,
        "accounting_integrity_pass": accounting_ok,
        "future_MFE_used_for_promotion": False,
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
        "next": (
            "RUN_EXIT_CAUSAL_SCREEN_THEN_COST_INTERACTION"
            if route in {
                "COST_GEOMETRY_AND_TURNOVER_REDESIGN",
                "PORTFOLIO_COST_FLOOR_GATE",
            }
            else "REPAIR_COST_ACCOUNTING_BEFORE_RESEARCH"
            if route == "COST_ACCOUNTING_INTEGRITY_REPAIR"
            else "KEEP_COST_AS_SECONDARY_DIAGNOSTIC"
        ),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    sample = [
        {
            "strategy_id": "a",
            "gross_R": 1.0,
            "net_R": 0.5,
            "cost_drag_R": 0.5,
            "modeled_cost_R": 0.5,
            "accounting_error_R": 0.0,
            "risk_distance_pct_of_notional": 0.2,
            "execution_cost_bps_of_notional": 10.0,
            "MFE_R": 1.2,
        }
    ]
    result = metrics(sample)
    assert result["gross_net_R"] == 1.0
    assert result["total_cost_drag_R"] == 0.5
    assert result["accounting_mismatch_count_gt_1e_8"] == 0
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.terminal_root is None:
        parser.error("--terminal-root required")
    receipt = run(args.terminal_root.resolve())
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
