#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.production_compression.gate.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _num(metrics: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = metrics.get(key)
        if value is not None:
            return float(value)
    return None


def _trades(metrics: Mapping[str, Any]) -> int:
    value = metrics.get("trades", metrics.get("completed_trades", 0))
    return int(value or 0)


def strategy_route(strategy_id: str, production_policy: Mapping[str, Any]) -> str:
    if strategy_id in set(production_policy.get("archive_direct_disabled") or []):
        return "ARCHIVE_DIRECT_DISABLED"
    if strategy_id in set(production_policy.get("survivor_hosts") or []):
        return "SURVIVOR_HOST_DIRECT_IMPROVEMENT"
    if strategy_id in set(production_policy.get("donor_rank1") or []):
        return "DONOR_MODULE_EVOLUTION_RANK1"
    if strategy_id in set(production_policy.get("donor_rank2") or []):
        return "DONOR_MODULE_EVOLUTION_RANK2"
    return "HOLD_UNCLASSIFIED"


def _absolute_blockers(child: Mapping[str, Any], retention_pct: float, hard: Mapping[str, Any]) -> list[str]:
    gate = hard["survivor_gate"]
    blockers: list[str] = []
    if _trades(child) < 1:
        return ["NO_TRADES"]
    expectancy = _num(child, "net_expectancy_bps")
    pnl = _num(child, "net_pnl_bps")
    pf = _num(child, "profit_factor", "net_profit_factor")
    payoff = _num(child, "payoff", "net_payoff")
    if expectancy is None or expectancy <= float(gate["minimum_expectancy_R"]) * 100.0:
        blockers.append("NET_EXPECTANCY_NON_POSITIVE")
    if pnl is None or pnl <= float(gate["minimum_net_R"]) * 100.0:
        blockers.append("NET_PNL_NON_POSITIVE")
    if pf is None or pf < float(gate["minimum_profit_factor"]):
        blockers.append("PROFIT_FACTOR_BELOW_GATE")
    if payoff is None or payoff < float(gate["minimum_payoff_ratio"]):
        blockers.append("PAYOFF_BELOW_GATE")
    if retention_pct < float(gate["minimum_retention_pct"]):
        blockers.append("RETENTION_BELOW_GATE")
    return blockers


def evaluate_child(parent: Mapping[str, Any], child: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    parent_trades = _trades(parent)
    child_trades = _trades(child)
    if parent_trades < 1:
        return {
            "schema_version": SCHEMA,
            "state": "HOLD_PARENT_SAMPLE_REQUIRED",
            "production_ready": False,
            "blockers": ["PARENT_NO_TRADES"],
        }

    retention_pct = 100.0 * child_trades / parent_trades
    parent_pnl = _num(parent, "net_pnl_bps")
    child_pnl = _num(child, "net_pnl_bps")
    parent_exp = _num(parent, "net_expectancy_bps")
    child_exp = _num(child, "net_expectancy_bps")
    parent_pf = _num(parent, "profit_factor", "net_profit_factor")
    child_pf = _num(child, "profit_factor", "net_profit_factor")
    parent_dd = _num(parent, "drawdown_bps", "max_drawdown_bps")
    child_dd = _num(child, "drawdown_bps", "max_drawdown_bps")

    blockers = _absolute_blockers(child, retention_pct, hard)
    pnl_delta = None if parent_pnl is None or child_pnl is None else child_pnl - parent_pnl
    exp_delta = None if parent_exp is None or child_exp is None else child_exp - parent_exp
    pf_delta = None if parent_pf is None or child_pf is None else child_pf - parent_pf
    dd_improvement = None if parent_dd is None or child_dd is None else parent_dd - child_dd

    if child_trades == 0 and "NO_TRADES" not in blockers:
        blockers.append("NO_TRADES")
    if pnl_delta is not None and exp_delta is not None and pnl_delta < 0.0 and exp_delta < 0.0:
        blockers.append("PARENT_RELATIVE_PNL_AND_EXPECTANCY_REGRESSION")

    economic_improvements = [
        pnl_delta is not None and pnl_delta > 0.0,
        exp_delta is not None and exp_delta > 0.0,
        pf_delta is not None and pf_delta > 0.0,
    ]
    if dd_improvement is not None and dd_improvement > 0.0 and not any(economic_improvements):
        blockers.append("DRAWDOWN_ONLY_IMPROVEMENT_NOT_PROMOTABLE")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": SCHEMA,
        "state": "PASS_PRODUCTION_CHILD_GATE" if not blockers else "REJECT_PRODUCTION_CHILD_GATE",
        "production_ready": not blockers,
        "parent_trades": parent_trades,
        "child_trades": child_trades,
        "trade_retention_pct": retention_pct,
        "minimum_retention_pct": float(hard["survivor_gate"]["minimum_retention_pct"]),
        "delta": {
            "net_pnl_bps": pnl_delta,
            "net_expectancy_bps_per_trade": exp_delta,
            "profit_factor": pf_delta,
            "drawdown_improvement_bps": dd_improvement,
            "trades": child_trades - parent_trades,
        },
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--child", type=Path, required=True)
    parser.add_argument("--hardening-policy", type=Path, default=HARDENING_POLICY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_child(read(args.parent), read(args.child), read(args.hardening_policy))
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["production_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
