#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}
TARGETS = ("supertrend_pullback", "trend_ma_macd")


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def ordered(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(trades, key=lambda x: (
        int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0),
        str(x.get("symbol") or ""), str(x.get("side") or ""), str(x.get("intent_sha") or ""),
    ))


def longest_loss_streak(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for row in ordered(trades):
        if float(row.get("net_bps") or 0.0) < 0.0:
            cur.append(row)
            if len(cur) > len(best):
                best = list(cur)
        else:
            cur = []
    return best


def realized_exit_bucket_dd_bps(trades: list[dict[str, Any]]) -> float:
    buckets: dict[int, float] = defaultdict(float)
    for row in trades:
        buckets[int(row.get("exit_ts") or 0)] += float(row.get("net_bps") or 0.0)
    equity = peak = max_dd = 0.0
    for _, pnl in sorted(buckets.items()):
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def max_open(trades: list[dict[str, Any]], *, same_side: bool = False, same_symbol: bool = False) -> int:
    events: list[tuple[int, int, str, str]] = []
    for row in trades:
        events.append((int(row.get("entry_ts") or 0), 1, str(row.get("side") or ""), str(row.get("symbol") or "")))
        events.append((int(row.get("exit_ts") or 0), -1, str(row.get("side") or ""), str(row.get("symbol") or "")))
    events.sort(key=lambda x: (x[0], x[1]))
    if same_symbol or same_side:
        active: Counter[str] = Counter()
        best = 0
        for _, delta, side, symbol in events:
            key = symbol if same_symbol else side
            active[key] += delta
            if active[key] <= 0:
                active.pop(key, None)
            best = max(best, max(active.values(), default=0))
        return best
    n = best = 0
    for _, delta, _, _ in events:
        n += delta
        best = max(best, n)
    return best


def one_active_per_symbol(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    active_until: dict[str, int] = {}
    for row in sorted(trades, key=lambda x: (
        int(x.get("entry_ts") or 0), str(x.get("symbol") or ""),
        int(x.get("exit_ts") or 0), str(x.get("intent_sha") or ""),
    )):
        symbol = str(row.get("symbol") or "")
        entry = int(row.get("entry_ts") or 0)
        if symbol in active_until and entry < active_until[symbol]:
            rejected.append(row)
        else:
            accepted.append(row)
            active_until[symbol] = int(row.get("exit_ts") or 0)
    return accepted, rejected


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    streak = longest_loss_streak(trades)
    pnl = sum(float(x.get("net_bps") or 0.0) for x in trades)
    wins = sum(float(x.get("net_bps") or 0.0) > 0.0 for x in trades)
    return {
        "completed_trades": len(trades),
        "win_rate": wins / len(trades) if trades else None,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": pnl / len(trades) if trades else None,
        "realized_exit_bucket_max_drawdown_bps": realized_exit_bucket_dd_bps(trades),
        "max_consecutive_losses_exit_order": len(streak),
        "worst_loss_streak_net_bps": sum(float(x.get("net_bps") or 0.0) for x in streak),
    }


def streak_anatomy(streak: list[dict[str, Any]]) -> dict[str, Any]:
    by_symbol: dict[str, float] = defaultdict(float)
    exit_buckets: Counter[int] = Counter()
    for row in streak:
        by_symbol[str(row.get("symbol") or "UNKNOWN")] += float(row.get("net_bps") or 0.0)
        exit_buckets[int(row.get("exit_ts") or 0)] += 1
    total_abs = sum(abs(v) for v in by_symbol.values())
    return {
        "trade_count": len(streak),
        "unique_symbols": sorted(by_symbol),
        "side_counts": dict(sorted(Counter(str(x.get("side") or "") for x in streak).items())),
        "symbol_loss_bps": dict(sorted(by_symbol.items())),
        "symbol_abs_loss_share": {k: abs(v) / total_abs if total_abs > 0 else 0.0 for k, v in sorted(by_symbol.items())},
        "exit_bucket_counts": {str(k): v for k, v in sorted(exit_buckets.items())},
        "largest_same_exit_loss_cluster": max(exit_buckets.values(), default=0),
        "trades": [{
            "symbol": x.get("symbol"), "side": x.get("side"), "entry_ts": x.get("entry_ts"),
            "exit_ts": x.get("exit_ts"), "net_bps": x.get("net_bps"), "reason": x.get("reason"),
        } for x in streak],
    }


def analyze(receipt: Mapping[str, Any]) -> dict[str, Any]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    if not trades:
        raise RuntimeError("TRADES_REQUIRED")
    if receipt.get("integrity_defects") or int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("SOURCE_RECEIPT_INTEGRITY_FAILED")
    parent = metrics(trades)
    child_trades, rejected = one_active_per_symbol(trades)
    child = metrics(child_trades)
    risk_improved = (
        child["max_consecutive_losses_exit_order"] < parent["max_consecutive_losses_exit_order"]
        or child["realized_exit_bucket_max_drawdown_bps"] < parent["realized_exit_bucket_max_drawdown_bps"]
    )
    no_expectancy_degradation = (
        child["net_expectancy_bps"] is not None and parent["net_expectancy_bps"] is not None
        and child["net_expectancy_bps"] >= parent["net_expectancy_bps"]
    )
    return {
        "strategy_id": receipt.get("strategy_id"),
        "source_receipt_sha256": receipt.get("receipt_sha256"),
        "drawdown_ordering_authority": "EXIT_TIMESTAMP_BUCKET_ASC",
        "parent": parent,
        "common_mode": {
            "max_concurrent_open_positions": max_open(trades),
            "max_concurrent_same_side_positions": max_open(trades, same_side=True),
            "max_concurrent_same_symbol_positions": max_open(trades, same_symbol=True),
            "worst_loss_streak": streak_anatomy(longest_loss_streak(trades)),
        },
        "one_axis_child": {
            "axis": "ONE_ACTIVE_POSITION_PER_SYMBOL",
            "numeric_threshold_invented": False,
            "accepted": child,
            "rejected_overlap_count": len(rejected),
            "rejected_by_symbol": dict(sorted(Counter(str(x.get("symbol") or "") for x in rejected).items())),
            "max_concurrent_open_positions": max_open(child_trades),
            "max_concurrent_same_side_positions": max_open(child_trades, same_side=True),
            "max_concurrent_same_symbol_positions": max_open(child_trades, same_symbol=True),
            "risk_diagnostic_improved": risk_improved,
            "no_expectancy_degradation": no_expectancy_degradation,
            "economic_upgrade_passed": bool(risk_improved and no_expectancy_degradation),
        },
        "conclusion": (
            "COMMON_MODE_STACKING_CONFIRMED_BUT_NAIVE_BLOCK_NOT_ECONOMIC_UPGRADE"
            if risk_improved and not no_expectancy_degradation else
            "ONE_AXIS_CHILD_PARETO_DOMINANT" if risk_improved else
            "COMMON_MODE_STACKING_NOT_CONFIRMED_BY_ONE_AXIS_CHILD"
        ),
        **AUTH,
    }


def run(supertrend: Path, trendma: Path, out: Path) -> dict[str, Any]:
    rows = {"supertrend_pullback": analyze(read(supertrend)), "trend_ma_macd": analyze(read(trendma))}
    if any(rows[s]["strategy_id"] != s for s in TARGETS):
        raise RuntimeError("STRATEGY_ID_MISMATCH")
    payload = {
        "schema_version": "zel.a1.finalist.common_mode_overlap_diagnostic.v1",
        "state": "PASS_COMMON_MODE_OVERLAP_DIAGNOSTIC",
        "source": {"github_actions_run_id": 32646262135, "artifact_id": 9495054717},
        "targets": rows,
        "policy_parameters_changed": False,
        "risk_parameters_changed": False,
        "exit_parameters_changed": False,
        "numeric_threshold_invented": False,
        "next": "REUSE_EXISTING_PORTFOLIO_GOVERNOR_RISK_SHARING; DO_NOT_PROMOTE_ONE_ACTIVE_PER_SYMBOL_CHILD",
        **AUTH,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def self_test() -> None:
    rows = [
        {"symbol": "A", "side": "long", "entry_ts": 1, "exit_ts": 5, "net_bps": -10.0, "intent_sha": "1"},
        {"symbol": "A", "side": "long", "entry_ts": 2, "exit_ts": 5, "net_bps": -20.0, "intent_sha": "2"},
        {"symbol": "B", "side": "long", "entry_ts": 2, "exit_ts": 5, "net_bps": -30.0, "intent_sha": "3"},
        {"symbol": "C", "side": "long", "entry_ts": 6, "exit_ts": 7, "net_bps": 100.0, "intent_sha": "4"},
    ]
    assert realized_exit_bucket_dd_bps(rows) == 60.0
    assert len(longest_loss_streak(rows)) == 3
    accepted, rejected = one_active_per_symbol(rows)
    assert len(accepted) == 3 and len(rejected) == 1
    assert max_open(rows) == 3 and max_open(rows, same_symbol=True) == 2
    assert metrics(accepted)["max_consecutive_losses_exit_order"] == 2
    print("PASS_A1_FINALIST_COMMON_MODE_OVERLAP_DIAGNOSTIC_V1_SELF_TEST")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--supertrend", type=Path)
    ap.add_argument("--trendma", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.supertrend or not args.trendma or not args.out:
        ap.error("--supertrend --trendma --out required")
    result = run(args.supertrend, args.trendma, args.out)
    print(json.dumps({sid: {
        "conclusion": x["conclusion"],
        "parent_streak": x["parent"]["max_consecutive_losses_exit_order"],
        "child_streak": x["one_axis_child"]["accepted"]["max_consecutive_losses_exit_order"],
        "parent_dd_bps": x["parent"]["realized_exit_bucket_max_drawdown_bps"],
        "child_dd_bps": x["one_axis_child"]["accepted"]["realized_exit_bucket_max_drawdown_bps"],
        "parent_expectancy_bps": x["parent"]["net_expectancy_bps"],
        "child_expectancy_bps": x["one_axis_child"]["accepted"]["net_expectancy_bps"],
    } for sid, x in result["targets"].items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
