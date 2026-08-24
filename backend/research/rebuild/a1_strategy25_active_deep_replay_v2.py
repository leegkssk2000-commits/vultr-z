#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_strategy25_active_deep_replay_v1 as core

AUTH = core.AUTH


def read(path: Path) -> dict[str, Any]:
    return core.read(path)


def quality_from_receipt(receipt: dict[str, Any], *, min_completed_trades: int = 12) -> dict[str, Any]:
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, dict)]
    net = [float(x.get("net_bps") or 0.0) for x in trades]
    total = sum(net)
    ordered = sorted(net, reverse=True)
    best = ordered[0] if ordered else None
    second = ordered[1] if len(ordered) > 1 else None
    without_best = total - best if best is not None else None
    without_best_two = total - sum(ordered[:2]) if ordered else None
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x < 0]
    symbols = sorted({str(x.get("symbol")) for x in trades if x.get("symbol")})
    by_symbol: dict[str, float] = {}
    by_reason: dict[str, int] = {}
    for t in trades:
        s = str(t.get("symbol") or "UNKNOWN")
        by_symbol[s] = by_symbol.get(s, 0.0) + float(t.get("net_bps") or 0.0)
        r = str(t.get("reason") or "UNKNOWN")
        by_reason[r] = by_reason.get(r, 0) + 1

    blockers: list[str] = []
    if len(trades) < min_completed_trades:
        blockers.append(f"SAMPLE_LT_{min_completed_trades}")
    if len(symbols) < 2:
        blockers.append("SYMBOL_BREADTH_LT_2")
    if total > 0 and without_best is not None and without_best <= 0:
        blockers.append("SINGLE_WINNER_FRAGILE")
    if receipt.get("integrity_defects"):
        blockers.append("INTEGRITY_DEFECTS_PRESENT")

    return {
        "state": "QUALIFIED_ROBUST_OBSERVATION" if not blockers else "HOLD_REPLAY_EVIDENCE_QUALITY",
        "pass": not blockers,
        "quality_role_only": True,
        "strict_certification_gate_mutated": False,
        "minimum_completed_trades": min_completed_trades,
        "completed_trades": len(trades),
        "distinct_symbol_count": len(symbols),
        "symbols_with_trades": symbols,
        "positive_symbol_count": sum(1 for v in by_symbol.values() if v > 0),
        "symbol_net_pnl_bps": dict(sorted(by_symbol.items())),
        "win_count": len(wins),
        "loss_count": len(losses),
        "median_net_bps": statistics.median(net) if net else None,
        "best_trade_net_bps": best,
        "second_best_trade_net_bps": second,
        "pnl_without_best_trade_bps": without_best,
        "pnl_without_best_two_trades_bps": without_best_two,
        "best_trade_share_of_total": (best / total) if best is not None and total > 0 else None,
        "best_two_trade_share_of_total": (sum(ordered[:2]) / total) if ordered and total > 0 else None,
        "exit_reason_counts": dict(sorted(by_reason.items())),
        "blockers": blockers,
    }


def run(league_path: Path, out_dir: Path, aggregate_path: Path, symbols: str) -> dict[str, Any]:
    result = core.run(league_path, out_dir, aggregate_path, symbols)
    quality_pass_count = 0
    for row in result.get("rows") or []:
        receipt_path = out_dir / f"{row['strategy_id']}.json"
        receipt = read(receipt_path)
        q = quality_from_receipt(receipt)
        row["evidence_quality"] = q
        quality_pass_count += int(bool(q["pass"]))
    result["schema_version"] = "zel.a1.strategy25_active_deep_replay.v2"
    result["evidence_quality_version"] = 2
    result["quality_pass_count"] = quality_pass_count
    result["quality_guard"] = {
        "role": "REPLAY_EVIDENCE_DIAGNOSTIC_ONLY",
        "minimum_completed_trades": 12,
        "minimum_distinct_symbols_with_trades": 2,
        "single_winner_robustness_required": True,
        "strict_h4_h5_a2_a3_threshold_mutation": False,
        "ranking_mutation": False,
    }
    core.write(aggregate_path, result)
    return result


def self_test() -> int:
    assert core.self_test() == 0
    stable = {
        "trades": [
            {"symbol": "BTC-USDT", "net_bps": 100, "reason": "TP"},
            {"symbol": "ETH-USDT", "net_bps": 60, "reason": "TIMEOUT"},
        ] * 6,
        "integrity_defects": [],
    }
    q = quality_from_receipt(stable)
    assert q["pass"] is True and q["completed_trades"] == 12 and q["distinct_symbol_count"] == 2, q
    fragile = {
        "trades": [
            {"symbol": "BTC-USDT", "net_bps": 1000, "reason": "TIMEOUT"},
            *[{"symbol": "ETH-USDT", "net_bps": -50, "reason": "SL"} for _ in range(11)],
        ],
        "integrity_defects": [],
    }
    q2 = quality_from_receipt(fragile)
    assert q2["pass"] is False and "SINGLE_WINNER_FRAGILE" in q2["blockers"], q2
    print("PASS_A1_STRATEGY25_ACTIVE_DEEP_REPLAY_V2_QUALITY_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--league", type=Path, default=Path("out/a1_strategy25_improvement_league_pre.json"))
    p.add_argument("--out-dir", type=Path, default=Path("out/strategy25_active_deep"))
    p.add_argument("--aggregate", type=Path, default=Path("out/a1_strategy25_active_deep_replay_latest.json"))
    p.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,LINK-USDT,DOGE-USDT")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.league, args.out_dir, args.aggregate, args.symbols)
    print("ACTIVE5_DEEP_REPLAY_V2=" + json.dumps({
        "active": r["active_top5"],
        "success": r["success_count"],
        "errors": r["error_count"],
        "quality_pass": r["quality_pass_count"],
        "symbols": r["symbols"],
        "bar_fetch_unique": r["shared_cache"]["bar_fetch_unique_count"],
        "execution_snapshot_unique": r["shared_cache"]["execution_snapshot_unique_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
