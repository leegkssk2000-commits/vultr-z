#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_delayed_fill_evaluator_v1 as delayed
from backend.research.rebuild.policy_kernel_v1 import atr, ema

ROOT = Path(__file__).resolve().parents[3]
A5_CONTRACT = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
PARENT_EVALUATOR = ROOT / "backend/research/rebuild/a1_trend_rider_delayed_fill_evaluator_v1.py"
PARENT_CONTRACT = ROOT / "backend/research/contracts/a1_trend_rider_delayed_fill_v1.json"
SCHEMA = "zel.a1.trend_rider.exact_parent_repair_batch.v1"

AXES = (
    "MULTISPEED_TREND_OWNER_ONLY",
    "RELATIVE_VOLUME_CONFIRMATION_ONLY",
    "LIQUIDITY_REGIME_OWNER_ONLY",
    "LONG_SHORT_ASYMMETRY_LONG_ONLY",
    "LONG_SHORT_ASYMMETRY_SHORT_ONLY",
)

EVIDENCE_BY_AXIS = {
    "MULTISPEED_TREND_OWNER_ONLY": ["A5E2", "A5E3"],
    "RELATIVE_VOLUME_CONFIRMATION_ONLY": ["A5E2", "A5E4"],
    "LIQUIDITY_REGIME_OWNER_ONLY": ["A5E2", "A5E4"],
    "LONG_SHORT_ASYMMETRY_LONG_ONLY": ["A5E3"],
    "LONG_SHORT_ASYMMETRY_SHORT_ONLY": ["A5E3"],
}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0, "gross_pnl_bps": 0.0, "gross_expectancy_bps": None,
            "net_pnl_bps": 0.0, "net_expectancy_bps": None, "profit_factor": None,
            "payoff": None, "win_rate": None, "drawdown_bps": 0.0,
        }
    values = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    aw = gp / len(wins) if wins else None
    al = gl / len(losses) if losses else None
    return {
        "trades": len(trades),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross),
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values),
        "profit_factor": ev.profit_factor(gp, gl),
        "payoff": aw / al if aw is not None and al not in (None, 0) else None,
        "win_rate": len(wins) / len(values),
        "drawdown_bps": ev.max_drawdown(values),
    }


def _session(ts_ms: int) -> str:
    hour = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).hour
    return "APAC" if hour < 8 else "EU" if hour < 16 else "US"


def _regime(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> str:
    symbol = str(trade["symbol"])
    bars = bars_by[symbol]
    idx = maps[symbol].get(int(trade["signal_ts"]))
    if idx is None or idx < 50:
        return "UNKNOWN"
    a14 = atr(bars[: idx + 1], 14)
    a50 = atr(bars[: idx + 1], 50)
    return "VOL_HIGH" if a14 >= a50 else "VOL_LOW"


def concentration(
    trades: list[dict[str, Any]],
    bars_by: Mapping[str, list[dict[str, Any]]],
    maps: Mapping[str, dict[int, int]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    h5 = policy["h5_concentration_fragility"]
    total_net = sum(float(x["net_bps"]) for x in trades)
    total_profit = sum(max(0.0, float(x["net_bps"])) for x in trades)
    groupers: dict[str, Callable[[Mapping[str, Any]], str]] = {
        "symbol": lambda x: str(x["symbol"]),
        "regime": lambda x: _regime(x, bars_by, maps),
        "side": lambda x: str(x["side"]),
        "session": lambda x: _session(int(x["signal_ts"])),
        "window": lambda x: datetime.fromtimestamp(int(x["entry_ts"]) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d"),
    }
    dimensions: dict[str, list[dict[str, Any]]] = {}
    loo: list[dict[str, Any]] = []
    for dim, fn in groupers.items():
        groups: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            groups.setdefault(fn(trade), []).append(trade)
        rows: list[dict[str, Any]] = []
        for group, items in sorted(groups.items()):
            net = sum(float(x["net_bps"]) for x in items)
            profit = sum(max(0.0, float(x["net_bps"])) for x in items)
            rows.append({
                "group": group,
                "trade_count": len(items),
                "net_R": net / 100.0,
                "profit_share": profit / total_profit if total_profit > 0 else 0.0,
            })
            loo.append({"dimension": dim, "group": group, "net_R": (total_net - net) / 100.0})
        dimensions[dim] = rows

    top10 = (
        sum(sorted((max(0.0, float(x["net_bps"])) for x in trades), reverse=True)[:10]) / total_profit
        if total_profit > 0 else 0.0
    )
    symbol_share = max((x["profit_share"] for x in dimensions.get("symbol", [])), default=0.0)
    regime_share = max((x["profit_share"] for x in dimensions.get("regime", [])), default=0.0)
    min_loo = min((float(x["net_R"]) for x in loo), default=0.0)
    blockers: list[str] = []
    if symbol_share > float(h5["maximum_single_symbol_profit_share"]):
        blockers.append("SINGLE_SYMBOL_CONCENTRATION")
    if regime_share > float(h5["maximum_single_regime_profit_share"]):
        blockers.append("SINGLE_REGIME_CONCENTRATION")
    if top10 > float(h5["maximum_top10_trade_profit_share"]):
        blockers.append("TOP10_TRADE_CONCENTRATION")
    if min_loo < float(h5["minimum_leave_one_group_out_net_R"]):
        blockers.append("LEAVE_ONE_GROUP_OUT_NON_POSITIVE")
    return {
        "state": "PASS_CONCENTRATION_FRAGILITY" if not blockers else "HOLD_CONCENTRATION_FRAGILITY",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "maximum_single_symbol_profit_share": symbol_share,
        "maximum_single_regime_profit_share": regime_share,
        "top10_trade_profit_share": top10,
        "minimum_leave_one_group_out_net_R": min_loo,
        "dimensions": dimensions,
        "leave_one_group_out": loo,
    }


def _maps(parent: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[int, int]]]:
    symbols = sorted({str(x["symbol"]) for x in parent.get("trades") or []})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {
        symbol: {int(row["ts_ms"]): idx for idx, row in enumerate(rows)}
        for symbol, rows in bars_by.items()
    }
    return bars_by, maps


def _signal_index(trade: Mapping[str, Any], maps: Mapping[str, dict[int, int]]) -> int | None:
    return maps[str(trade["symbol"])].get(int(trade["signal_ts"]))


def keep_multispeed(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"]); idx = _signal_index(trade, maps)
    if idx is None or idx < 56:
        return False
    bars = bars_by[symbol][: idx + 1]
    closes = [float(x["close"]) for x in bars]
    e21, e50, e55 = ema(closes, 21), ema(closes, 50), ema(closes, 55)
    side = str(trade["side"])
    if side == "long":
        return e21[-1] > e50[-1] > e55[-1] and e21[-1] > e21[-2] and e55[-1] >= e55[-2]
    return e21[-1] < e50[-1] < e55[-1] and e21[-1] < e21[-2] and e55[-1] <= e55[-2]


def keep_relative_volume(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"]); idx = _signal_index(trade, maps)
    if idx is None or idx < 20:
        return False
    bars = bars_by[symbol]
    current = float(bars[idx]["volume"])
    prior = [float(x["volume"]) for x in bars[idx - 20:idx]]
    mean = sum(prior) / len(prior)
    return current >= mean


def keep_liquidity(trade: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> bool:
    symbol = str(trade["symbol"]); idx = _signal_index(trade, maps)
    if idx is None or idx < 20:
        return False
    bars = bars_by[symbol]
    current = float(bars[idx]["close"]) * float(bars[idx]["volume"])
    prior = [float(x["close"]) * float(x["volume"]) for x in bars[idx - 20:idx]]
    return current >= statistics.median(prior)


def select_axis(parent: Mapping[str, Any], axis: str, bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> list[dict[str, Any]]:
    trades = [dict(x) for x in parent.get("trades") or []]
    if axis == "MULTISPEED_TREND_OWNER_ONLY":
        return [x for x in trades if keep_multispeed(x, bars_by, maps)]
    if axis == "RELATIVE_VOLUME_CONFIRMATION_ONLY":
        return [x for x in trades if keep_relative_volume(x, bars_by, maps)]
    if axis == "LIQUIDITY_REGIME_OWNER_ONLY":
        return [x for x in trades if keep_liquidity(x, bars_by, maps)]
    if axis == "LONG_SHORT_ASYMMETRY_LONG_ONLY":
        return [x for x in trades if str(x["side"]) == "long"]
    if axis == "LONG_SHORT_ASYMMETRY_SHORT_ONLY":
        return [x for x in trades if str(x["side"]) == "short"]
    raise RuntimeError(f"UNKNOWN_AXIS:{axis}")


def economic_gate(metric: Mapping[str, Any], retention_pct: float, policy: Mapping[str, Any]) -> tuple[bool, list[str]]:
    gate = policy["survivor_gate"]
    blockers: list[str] = []
    if int(metric.get("trades") or 0) < 1:
        blockers.append("NO_TRADES")
        return False, blockers
    if float(metric.get("net_expectancy_bps") or 0.0) <= float(gate["minimum_expectancy_R"]) * 100.0:
        blockers.append("NET_EXPECTANCY_NON_POSITIVE")
    if float(metric.get("net_pnl_bps") or 0.0) <= float(gate["minimum_net_R"]) * 100.0:
        blockers.append("NET_PNL_NON_POSITIVE")
    pf = metric.get("profit_factor")
    if pf is None or float(pf) < float(gate["minimum_profit_factor"]):
        blockers.append("PROFIT_FACTOR_BELOW_GATE")
    payoff = metric.get("payoff")
    if payoff is None or float(payoff) < float(gate["minimum_payoff_ratio"]):
        blockers.append("PAYOFF_BELOW_GATE")
    if retention_pct < float(gate["minimum_retention_pct"]):
        blockers.append("RETENTION_BELOW_GATE")
    return not blockers, blockers


def run(parent_path: Path, output: Path) -> dict[str, Any]:
    parent = read(parent_path)
    if parent.get("schema_version") != "zel.a1.trend_rider.delayed_fill_economics.v1":
        raise RuntimeError("EXACT_DELAYED_FILL_PARENT_REQUIRED")
    if parent.get("parent_strategy_id") != "trend_rider" or parent.get("challenger_id") != "trend_rider_one_bar_delayed_fill_v1":
        raise RuntimeError("TREND_RIDER_PARENT_IDENTITY_MISMATCH")
    if parent.get("parameter_sweep") is not False:
        raise RuntimeError("PARENT_PARAMETER_SWEEP_NOT_FALSE")
    if parent.get("execution_authority") != "NONE" or parent.get("order_authority") != "BLOCKED":
        raise RuntimeError("PARENT_AUTHORITY_NOT_BLOCKED")

    a5 = read(A5_CONTRACT)
    hard = read(HARDENING_POLICY)
    external_ids = {str(x.get("id")) for x in (a5.get("external_evidence") or []) if isinstance(x, Mapping)}
    for axis, ids in EVIDENCE_BY_AXIS.items():
        if not set(ids).issubset(external_ids):
            raise RuntimeError(f"EVIDENCE_ID_NOT_FROZEN:{axis}")

    bars_by, maps = _maps(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    parent_metrics = metrics(parent_trades)
    parent_h5 = concentration(parent_trades, bars_by, maps, hard)
    parent_n = len(parent_trades)
    candidates: list[dict[str, Any]] = []

    for axis in AXES:
        child_trades = select_axis(parent, axis, bars_by, maps)
        child_metrics = metrics(child_trades)
        retention = 100.0 * len(child_trades) / max(1, parent_n)
        child_h5 = concentration(child_trades, bars_by, maps, hard)
        economic_ok, economic_blockers = economic_gate(child_metrics, retention, hard)
        h5_improvement = int(child_h5["blocker_count"]) < int(parent_h5["blocker_count"])
        candidate = {
            "candidate_id": "trend_rider_delayed_fill__" + axis.lower(),
            "parent_strategy_id": "trend_rider",
            "parent_challenger_id": parent["challenger_id"],
            "changed_axis": axis,
            "changed_axis_count": 1,
            "evidence_ids": EVIDENCE_BY_AXIS[axis],
            "parent_signal_geometry_changed": False,
            "parent_stop_geometry_changed": False,
            "parent_timeout_changed": False,
            "parent_cost_model_changed": False,
            "post_outcome_trade_deletion": False,
            "parameter_sweep": False,
            "completed_trades": len(child_trades),
            "trade_retention_pct": retention,
            "metrics": child_metrics,
            "concentration": child_h5,
            "economic_gate_pass": economic_ok,
            "economic_gate_blockers": economic_blockers,
            "h5_blocker_count_improved_vs_parent": h5_improvement,
            "development_candidate_ready": bool(economic_ok and h5_improvement),
            "trade_identity_sha256": stable([(x.get("symbol"), x.get("signal_ts"), x.get("entry_ts"), x.get("side")) for x in child_trades]),
        }
        candidate["candidate_sha256"] = stable(candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda x: (
        not bool(x["development_candidate_ready"]),
        int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        -float(x["trade_retention_pct"]),
        str(x["candidate_id"]),
    ))
    ready = [x for x in candidates if x["development_candidate_ready"]]
    next_candidate = ready[0] if ready else None
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_EXACT_PARENT_DEVELOPMENT_REPAIR_READY" if next_candidate else "HOLD_EXACT_PARENT_NEXT_DISTINCT_AXIS_REQUIRED",
        "strategy_id": "trend_rider",
        "incumbent": "trend_rider_one_bar_delayed_fill_v1",
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_evaluator_path": str(PARENT_EVALUATOR.relative_to(ROOT)),
        "parent_evaluator_sha256": file_sha(PARENT_EVALUATOR),
        "parent_contract_path": str(PARENT_CONTRACT.relative_to(ROOT)),
        "parent_contract_sha256": file_sha(PARENT_CONTRACT),
        "a5_contract_sha256": file_sha(A5_CONTRACT),
        "hardening_policy_sha256": file_sha(HARDENING_POLICY),
        "parent_metrics": parent_metrics,
        "parent_concentration": parent_h5,
        "tested_axes": list(AXES),
        "candidates": candidates,
        "development_ready_count": len(ready),
        "next_exact_parent_candidate": next_candidate,
        "policy": {
            "exact_parent_trade_identity_required": True,
            "parent_entry_signal_geometry_frozen": True,
            "parent_stop_timeout_cost_frozen": True,
            "one_axis_only": True,
            "internet_evidence_is_hypothesis_authority_only": True,
            "paper_numeric_threshold_copy_forbidden": True,
            "h5_uses_existing_frozen_policy": True,
            "development_pass_requires_positive_economics_and_h5_blocker_reduction": True,
            "fresh_prospective_validation_still_required": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    a5 = read(A5_CONTRACT)
    axes = [str(x.get("axis")) for x in a5["strategies"]["trend_rider"]["repair_axes"]]
    assert "MULTISPEED_TREND_OWNER_ONLY" in axes
    assert "RELATIVE_VOLUME_CONFIRMATION_ONLY" in axes
    assert "LIQUIDITY_REGIME_OWNER_ONLY" in axes
    assert "LONG_SHORT_ASYMMETRY_ONLY" in axes
    assert read(PARENT_CONTRACT)["challenger_id"] == "trend_rider_one_bar_delayed_fill_v1"
    assert read(HARDENING_POLICY)["survivor_gate"]["minimum_retention_pct"] == 60.0
    assert set(EVIDENCE_BY_AXIS["MULTISPEED_TREND_OWNER_ONLY"]).issubset({x["id"] for x in a5["external_evidence"]})
    print("PASS_A1_TREND_RIDER_EXACT_PARENT_REPAIR_BATCH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_exact_parent_repair_batch_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise RuntimeError("--parent required")
    result = run(args.parent, args.out)
    print("A1_TREND_RIDER_EXACT_PARENT_REPAIR_BATCH=" + json.dumps({
        "state": result["state"],
        "parent_metrics": result["parent_metrics"],
        "parent_h5_blockers": result["parent_concentration"]["blockers"],
        "ready": result["development_ready_count"],
        "next": result["next_exact_parent_candidate"],
        "receipt": result["receipt_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
