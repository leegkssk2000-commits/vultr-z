#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import fetch_bars

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "backend/research/rebuild/a1_break_and_continue_original_gen1_snapshot_v1.json"
BASELINE_ID = "GEN1_ORIGINAL_BREAK_AND_CONTINUE"
EXPECTED_RECEIPT = "afe69429e949c5c705e09045c3c77d39d961c82eb0e3789f493379a29a8252ea"
CHILD_ID = "break_and_continue__relative_volume_confirm_v1"
LOOKBACK = 20
FLOOR = 1.0
MIN_RETENTION = 0.60


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def max_drawdown(values: list[float]) -> float:
    equity = peak = dd = 0.0
    for x in values:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in trades]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "completed_trades": len(vals),
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "win_rate": len(wins) / len(vals) if vals else None,
        "drawdown_bps": max_drawdown(vals),
    }


def validate_snapshot(s: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    if s.get("strategy_id") != "break_and_continue": defects.append("STRATEGY_ID_MISMATCH")
    if s.get("baseline_id") != BASELINE_ID: defects.append("BASELINE_ID_MISMATCH")
    if (s.get("source_artifact") or {}).get("receipt_sha256") != EXPECTED_RECEIPT: defects.append("RECEIPT_ID_MISMATCH")
    if int(s.get("completed_trades") or -1) != 7: defects.append("BASELINE_TRADE_COUNT_MISMATCH")
    got = metrics(list(s.get("trades") or []))
    exp = s.get("metrics") or {}
    aliases = {
        "net_pnl_bps":"net_pnl_bps", "net_expectancy_bps":"net_expectancy_bps",
        "net_profit_factor":"profit_factor", "net_payoff":"payoff",
        "win_rate":"win_rate", "max_drawdown_bps":"drawdown_bps"
    }
    for ek, gk in aliases.items():
        a, b = exp.get(ek), got.get(gk)
        if a is None or b is None:
            if a is not b: defects.append(f"BASELINE_METRIC_MISMATCH:{ek}")
            continue
        scale = max(1.0, abs(float(a)), abs(float(b)))
        if abs(float(a)-float(b)) > 2e-6*scale:
            defects.append(f"BASELINE_METRIC_MISMATCH:{ek}:expected={a}:computed={b}")
    ids = [str(x.get("intent_sha")) for x in (s.get("trades") or [])]
    if len(ids) != len(set(ids)): defects.append("DUPLICATE_PARENT_TRADE_ID")
    return defects


def historical_relative_volume(symbol: str, signal_ts: int, cache: dict[str, list[dict[str, Any]]]) -> tuple[float, dict[str, Any]]:
    bars = cache.setdefault(symbol, fetch_bars(symbol, "1h", limit=1000))
    index = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
    if signal_ts not in index:
        raise RuntimeError(f"HISTORICAL_SIGNAL_BAR_MISSING:{symbol}:{signal_ts}")
    i = index[signal_ts]
    if i < LOOKBACK:
        raise RuntimeError(f"HISTORICAL_VOLUME_WARMUP_MISSING:{symbol}:{signal_ts}")
    signal_volume = float(bars[i]["volume"])
    prior = [float(x["volume"]) for x in bars[i-LOOKBACK:i]]
    if signal_volume <= 0 or any(x <= 0 or not math.isfinite(x) for x in prior):
        raise RuntimeError(f"HISTORICAL_VOLUME_INVALID:{symbol}:{signal_ts}")
    mean = sum(prior)/len(prior)
    ratio = signal_volume/mean
    return ratio, {"signal_volume":signal_volume,"prior20_mean_volume":mean,"relative_volume":ratio}


def evaluate() -> dict[str, Any]:
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    defects = validate_snapshot(s)
    parent_trades = list(s.get("trades") or [])
    parent = metrics(parent_trades)
    cache: dict[str, list[dict[str, Any]]] = {}
    decisions: list[dict[str, Any]] = []
    child: list[dict[str, Any]] = []
    if not defects:
        try:
            for t in parent_trades:
                ratio, volume = historical_relative_volume(str(t["symbol"]), int(t["signal_ts"]), cache)
                passed = ratio >= FLOOR
                decisions.append({
                    "intent_sha": t["intent_sha"], "symbol": t["symbol"], "signal_ts": t["signal_ts"],
                    **volume, "floor": FLOOR, "passed": passed
                })
                if passed:
                    child.append(dict(t))
        except Exception as exc:
            defects.append(f"HISTORICAL_AXIS_EVALUATION_FAILED:{type(exc).__name__}:{exc}")
    child_m = metrics(child)
    retention = len(child)/len(parent_trades) if parent_trades else 0.0
    delta = {
        "win_rate_pp": None if child_m["win_rate"] is None else (child_m["win_rate"]-parent["win_rate"])*100,
        "net_expectancy_bps": None if child_m["net_expectancy_bps"] is None else child_m["net_expectancy_bps"]-parent["net_expectancy_bps"],
        "net_pnl_bps": child_m["net_pnl_bps"]-parent["net_pnl_bps"],
        "profit_factor": None if child_m["profit_factor"] is None or parent["profit_factor"] is None else child_m["profit_factor"]-parent["profit_factor"],
        "payoff": None if child_m["payoff"] is None or parent["payoff"] is None else child_m["payoff"]-parent["payoff"],
        "drawdown_bps": child_m["drawdown_bps"]-parent["drawdown_bps"],
        "retention_pct": retention*100,
    }
    pareto = bool(
        not defects and retention >= MIN_RETENTION and child_m["completed_trades"] >= 3
        and child_m["net_pnl_bps"] > 0
        and child_m["net_expectancy_bps"] is not None and child_m["net_expectancy_bps"] >= parent["net_expectancy_bps"]
        and child_m["win_rate"] is not None and child_m["win_rate"] >= parent["win_rate"]
        and child_m["drawdown_bps"] <= parent["drawdown_bps"]
    )
    state = "HOLD_BASELINE_OR_AXIS_INTEGRITY" if defects else ("PASS_SCREENING_DIRECT_AB_FRESH_CHALLENGER_REQUIRED" if pareto else "FAIL_DIRECT_AB_ROUTE_NEXT_DISTINCT_AXIS")
    out = {
        "schema_version":"zel.a1.break_and_continue.original_relative_volume_ab.v1",
        "state":state, "strategy_id":"break_and_continue", "child_id":CHILD_ID,
        "baseline_id":BASELINE_ID, "axis":"TRADE_FLOW_REL_VOLUME_CONFIRMATION_ONLY",
        "axis_contract":{"lookback":LOOKBACK,"floor":FLOOR,"parameter_sweep":False,"post_outcome_trade_deletion":False,"new_trade_admission":False},
        "source_artifact":s.get("source_artifact"), "parent_metrics":parent, "child_metrics":child_m,
        "delta":delta, "retention":retention, "decisions":decisions,
        "parent_trade_ids":[x["intent_sha"] for x in parent_trades],
        "child_trade_ids":[x["intent_sha"] for x in child],
        "child_is_parent_subset":set(x["intent_sha"] for x in child).issubset(set(x["intent_sha"] for x in parent_trades)),
        "development_pareto_candidate":pareto,
        "fresh_validation_required_before_a1_survivor":True,
        "official_pass_counts_unchanged":{"A1":1,"A2":1,"A3":0},
        "integrity_defects":defects,
        "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED"
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def self_test() -> None:
    s = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    defects = validate_snapshot(s)
    assert not defects, defects
    assert s["source_artifact"]["workflow_run_id"] == 32482936710
    assert len(s["trades"]) == 7
    assert LOOKBACK == 20 and FLOOR == 1.0
    print("PASS_BREAK_ORIGINAL_FROZEN_COHORT_SELF_TEST")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", default=str(ROOT / "backend/research/architecture_factory/a1_break_and_continue_original_relative_volume_ab_latest.json"))
    args = p.parse_args()
    if args.self_test:
        self_test(); return 0
    out = evaluate()
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({k:out[k] for k in ["state","baseline_id","child_id","development_pareto_candidate","delta","integrity_defects"]}, sort_keys=True))
    return 2 if out["integrity_defects"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
