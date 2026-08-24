#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "zel.a1.other_finalists.fixed_axis_surgery.v1"
TARGETS = ("break_and_continue", "supertrend_pullback", "trend_ma_macd")
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return row


def _session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else ("EU" if h < 16 else "US")


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(t.get("net_bps") or 0.0) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    pnl = sum(vals)
    buckets: dict[int, float] = defaultdict(float)
    for t, v in zip(trades, vals):
        buckets[int(t.get("exit_ts") or 0)] += v
    eq = peak = dd = 0.0
    for _, v in sorted(buckets.items()):
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else None)
    return {
        "completed_trades": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(vals)) if vals else None,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": (pnl / len(vals)) if vals else None,
        "profit_factor": pf,
        "max_drawdown_bps": dd,
        "distinct_symbols": len({str(t.get("symbol") or "") for t in trades if t.get("symbol")}),
    }


def _validate_parent(row: Mapping[str, Any], sid: str) -> list[str]:
    defects: list[str] = []
    if str(row.get("strategy_id") or "") != sid:
        defects.append("STRATEGY_ID_MISMATCH")
    if list(row.get("integrity_defects") or []):
        defects.append("INTEGRITY_DEFECT")
    if int(row.get("leakage_lookahead") or 0) != 0:
        defects.append("LOOKAHEAD_NONZERO")
    sq = row.get("source_quality_gate")
    if isinstance(sq, Mapping) and str(sq.get("state") or "") not in {"PASS", "PENDING"}:
        defects.append("SOURCE_QUALITY_FAIL")
    if not isinstance(row.get("trades"), list):
        defects.append("TRADES_MISSING")
    return defects


def _winner_retention(parent: list[dict[str, Any]], child: list[dict[str, Any]]) -> float:
    p = sum(float(t.get("net_bps") or 0.0) > 0 for t in parent)
    c = sum(float(t.get("net_bps") or 0.0) > 0 for t in child)
    return (c / p) if p else 1.0


def _nonworse(child: float | None, parent: float | None, higher: bool) -> bool:
    if child is None or parent is None:
        return False
    eps = 1e-9
    return child + eps >= parent if higher else child <= parent + eps


def _evaluate(sid: str, parent_row: Mapping[str, Any], keep: Callable[[dict[str, Any]], bool], axis: str, variant: str, rationale: str) -> dict[str, Any]:
    defects = _validate_parent(parent_row, sid)
    parent = [dict(x) for x in (parent_row.get("trades") or [])]
    child = [dict(x) for x in parent if keep(dict(x))]
    pm = _metrics(parent)
    cm = _metrics(child)
    retention = len(child) / max(1, len(parent))
    winner_ret = _winner_retention(parent, child)
    blockers: list[str] = []
    if defects:
        blockers.extend(defects)
    if len(child) < 12:
        blockers.append("CHILD_TRADES_LT_12")
    if retention < 0.60:
        blockers.append("TRADE_RETENTION_LT_60PCT")
    if winner_ret < 0.80:
        blockers.append("WINNER_RETENTION_LT_80PCT")
    if cm["distinct_symbols"] < 3:
        blockers.append("SYMBOL_BREADTH_LT_3")
    for key in ("net_pnl_bps", "net_expectancy_bps"):
        if not (isinstance(cm[key], (int, float)) and isinstance(pm[key], (int, float)) and float(cm[key]) > float(pm[key]) + 1e-9):
            blockers.append(f"{key.upper()}_NOT_STRICTLY_IMPROVED")
    if not _nonworse(cm["win_rate"], pm["win_rate"], True):
        blockers.append("WIN_RATE_WORSE")
    if not _nonworse(cm["profit_factor"], pm["profit_factor"], True):
        blockers.append("PROFIT_FACTOR_WORSE")
    if not _nonworse(cm["max_drawdown_bps"], pm["max_drawdown_bps"], False):
        blockers.append("DRAWDOWN_WORSE")
    state = "PASS_FIXED_AXIS_DEVELOPMENT_PARETO" if not blockers else "HOLD_FIXED_AXIS_NOT_PARETO"
    out = {
        "strategy_id": sid,
        "candidate_id": f"{sid}__{axis.lower()}__{variant.lower()}",
        "changed_axis": axis,
        "changed_variant": variant,
        "changed_axis_count": 1,
        "rationale_predeclared": rationale,
        "numeric_threshold_sweep": False,
        "post_outcome_threshold_fit": False,
        "stop_changed": False,
        "timeout_changed": False,
        "cost_model_changed": False,
        "parent_trade_count": len(parent),
        "child_trade_count": len(child),
        "trade_retention": retention,
        "winner_retention": winner_ret,
        "parent_metrics": pm,
        "child_metrics": cm,
        "blockers": blockers,
        "state": state,
        "fresh_oos_required": True,
        **AUTH,
    }
    out["candidate_sha256"] = _sha(out)
    return out


def run(paths: Mapping[str, Path], out: Path) -> dict[str, Any]:
    rows = {sid: _read(paths[sid]) for sid in TARGETS}
    specs: dict[str, tuple[Callable[[dict[str, Any]], bool], str, str, str]] = {
        "break_and_continue": (
            lambda t: str(t.get("side") or "").lower() == "long",
            "SIDE_ADMISSION_ONLY", "LONG_ONLY",
            "Prior 44-trade concentration attribution: LONG +221.81R versus SHORT -12.81R; test one categorical side axis only.",
        ),
        "supertrend_pullback": (
            lambda t: _session(int(t.get("signal_ts") or 0)) != "US",
            "SESSION_ADMISSION_ONLY", "NON_US_ONLY",
            "Prior 39-trade attribution: US session -14.83R while APAC/EU positive; LONG-only already has an independent sealed fresh lane, so test a distinct session axis.",
        ),
        "trend_ma_macd": (
            lambda t: _session(int(t.get("signal_ts") or 0)) != "US",
            "SESSION_ADMISSION_ONLY", "NON_US_ONLY",
            "Prior 31-trade attribution: US session -12.14R while APAC/EU positive; LONG-only already has an independent sealed fresh lane, so test a distinct session axis.",
        ),
    }
    strategies: dict[str, Any] = {}
    for sid in TARGETS:
        keep, axis, variant, rationale = specs[sid]
        strategies[sid] = _evaluate(sid, rows[sid], keep, axis, variant, rationale)
    passed = [sid for sid, r in strategies.items() if r["state"].startswith("PASS_")]
    result = {
        "schema_version": SCHEMA,
        "research_only": True,
        "policy": {
            "one_axis_per_strategy": True,
            "fixed_categorical_axis_only": True,
            "numeric_threshold_sweep_forbidden": True,
            "post_outcome_threshold_fit_forbidden": True,
            "fresh_oos_before_survivor_required": True,
            "minimum_child_trades": 12,
            "minimum_trade_retention": 0.60,
            "minimum_winner_retention": 0.80,
            "pareto_requires": ["pnl_up", "expectancy_up", "wr_nonworse", "pf_nonworse", "dd_nonworse"],
        },
        "pass_count": len(passed),
        "passed_strategies": passed,
        "strategies": strategies,
        "state": "PASS_FIXED_AXIS_SURGERY_HAS_CANDIDATE" if passed else "HOLD_NO_FIXED_AXIS_PARETO",
        "next": "FREEZE_EACH_PASS_TO_SEPARATE_FRESH_OOS_LANE" if passed else "ROUTE_NEXT_DISTINCT_AXIS_WITHOUT_RETUNING",
        **AUTH,
    }
    result["receipt_sha256"] = _sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake = {
        "strategy_id": "break_and_continue", "integrity_defects": [], "leakage_lookahead": 0,
        "source_quality_gate": {"state": "PASS"},
        "trades": [
            {"side": "long", "signal_ts": 0, "exit_ts": i, "symbol": ["A", "B", "C"][i % 3], "net_bps": 10.0}
            for i in range(12)
        ] + [
            {"side": "short", "signal_ts": 0, "exit_ts": 20 + i, "symbol": ["A", "B", "C"][i % 3], "net_bps": -5.0}
            for i in range(6)
        ],
    }
    row = _evaluate("break_and_continue", fake, lambda t: t["side"] == "long", "SIDE_ADMISSION_ONLY", "LONG_ONLY", "test")
    assert row["state"] == "PASS_FIXED_AXIS_DEVELOPMENT_PARETO", row
    assert row["trade_retention"] >= 0.60 and row["winner_retention"] == 1.0
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_OTHER_FINALISTS_FIXED_AXIS_SURGERY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--trendma-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_other_finalists_fixed_axis_surgery_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.break_parent, args.supertrend_parent, args.trendma_parent)):
        raise SystemExit("PARENT_PATHS_REQUIRED")
    r = run({
        "break_and_continue": args.break_parent,
        "supertrend_pullback": args.supertrend_parent,
        "trend_ma_macd": args.trendma_parent,
    }, args.out)
    print(json.dumps({
        "state": r["state"], "pass_count": r["pass_count"], "passed": r["passed_strategies"],
        "rows": {k: {"state": v["state"], "parent": v["parent_metrics"], "child": v["child_metrics"], "ret": v["trade_retention"], "winner_ret": v["winner_retention"], "blockers": v["blockers"]} for k, v in r["strategies"].items()},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
