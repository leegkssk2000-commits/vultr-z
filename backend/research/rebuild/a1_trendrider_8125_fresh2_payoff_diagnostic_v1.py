#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
FRESH = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.8125.fresh2_payoff_diagnostic.v1"


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def validate_source(source: dict[str, Any]) -> None:
    if source.get("schema_version") != "zel.a1.trendrider.8125.fresh2_source.v1":
        raise RuntimeError("FRESH2_SOURCE_SCHEMA_MISMATCH")
    supplied = str(source.get("receipt_sha256") or "")
    core = dict(source)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("FRESH2_SOURCE_RECEIPT_MISMATCH")
    metrics = source.get("source_metrics") or {}
    if int(metrics.get("trades") or -1) != 2 or int(metrics.get("wins") or -1) != 2:
        raise RuntimeError("FRESH2_SOURCE_COUNT_MISMATCH")
    if abs(float(metrics.get("win_rate") or -1.0) - 1.0) > 1e-12:
        raise RuntimeError("FRESH2_SOURCE_WR_MISMATCH")
    trades = source.get("trades") or []
    if len(trades) != 2 or any(str(t.get("reason")) != "TIMEOUT" for t in trades):
        raise RuntimeError("FRESH2_SOURCE_EXPECTED_TWO_TIMEOUT_WINNERS")
    if any(float(t.get("net_bps") or 0.0) <= 0.0 for t in trades):
        raise RuntimeError("FRESH2_SOURCE_EXPECTED_POSITIVE_NET")


def parent_algebra(parent: dict[str, Any]) -> dict[str, float | int]:
    m = parent.get("metrics") or {}
    trades = int(m["completed_trades"])
    wins = int(m["wins"])
    losses = trades - wins
    pnl = float(m["net_pnl_bps"])
    payoff = float(m["payoff"])
    pf = float(m["profit_factor"])
    if trades != 16 or wins != 13 or losses != 3:
        raise RuntimeError("WR8125_PARENT_COUNT_MISMATCH")
    avg_loss = pnl / (wins * payoff - losses)
    avg_win = payoff * avg_loss
    gross_profit = wins * avg_win
    gross_loss = losses * avg_loss
    if abs(gross_profit / gross_loss - pf) > 1e-9 * max(1.0, abs(pf)):
        raise RuntimeError("WR8125_PARENT_PF_ALGEBRA_MISMATCH")
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "net_pnl_bps": pnl,
        "net_expectancy_bps": float(m["net_expectancy_bps"]),
        "drawdown_bps": float(m["max_drawdown_bps"]),
        "profit_factor": pf,
        "payoff": payoff,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "gross_profit_bps": gross_profit,
        "gross_loss_bps": gross_loss,
    }


def excursion(trade: dict[str, Any]) -> dict[str, Any]:
    symbol = str(trade["symbol"])
    entry_ts = int(trade["entry_ts"])
    exit_ts = int(trade["exit_ts"])
    entry = float(trade["entry"])
    cost = float(trade["realized_cost_bps"])
    bars = ev.fetch_bars(symbol, "1h", limit=1000)
    window = [x for x in bars if entry_ts <= int(x["ts_ms"]) <= exit_ts]
    if not window:
        raise RuntimeError(f"MFE_WINDOW_EMPTY:{symbol}:{entry_ts}:{exit_ts}")
    if int(window[0]["ts_ms"]) != entry_ts or int(window[-1]["ts_ms"]) != exit_ts:
        raise RuntimeError(f"MFE_WINDOW_BOUNDARY_MISMATCH:{symbol}:{int(window[0]['ts_ms'])}:{int(window[-1]['ts_ms'])}")
    if len(window) != int(trade["timeout_bars"]) + 1:
        raise RuntimeError(f"MFE_WINDOW_BAR_COUNT_MISMATCH:{symbol}:{len(window)}")
    if str(trade["side"]) != "long":
        raise RuntimeError("FRESH2_DIAGNOSTIC_LONG_ONLY_EXPECTED")
    max_high = max(float(x["high"]) for x in window)
    min_low = min(float(x["low"]) for x in window)
    mfe_gross = (max_high - entry) / entry * 10_000.0
    mae_gross = (entry - min_low) / entry * 10_000.0
    mfe_net_conservative = mfe_gross - cost
    realized = float(trade["net_bps"])
    return {
        "symbol": symbol,
        "signal_ts": int(trade["signal_ts"]),
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "timeout_bars": int(trade["timeout_bars"]),
        "entry": entry,
        "realized_exit": float(trade["exit"]),
        "realized_net_bps": realized,
        "realized_cost_bps": cost,
        "mfe_high": max_high,
        "mae_low": min_low,
        "mfe_gross_bps": mfe_gross,
        "mfe_net_upper_conservative_bps": mfe_net_conservative,
        "mae_gross_bps": mae_gross,
        "realized_capture_of_mfe_net": realized / mfe_net_conservative if mfe_net_conservative > 0 else None,
        "reason": str(trade["reason"]),
        "mfe_is_diagnostic_upper_bound_not_tradable_exit": True,
    }


def union_metrics(p: dict[str, float | int], added: list[float]) -> dict[str, Any]:
    fresh_wins = sum(1 for x in added if x > 0)
    fresh_losses = sum(1 for x in added if x < 0)
    t = int(p["trades"]) + len(added)
    wins = int(p["wins"]) + fresh_wins
    losses = int(p["losses"]) + fresh_losses
    total = float(p["net_pnl_bps"]) + sum(added)
    gp = float(p["gross_profit_bps"]) + sum(x for x in added if x > 0)
    gl = float(p["gross_loss_bps"]) + sum(-x for x in added if x < 0)
    avg_win = gp / wins if wins else None
    avg_loss = gl / losses if losses else None
    return {
        "trades": t,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / t if t else None,
        "net_pnl_bps": total,
        "net_expectancy_bps": total / t if t else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
        "drawdown_bps_upper_logic": float(p["drawdown_bps"]),
        "drawdown_non_increase_proof": "APPENDED_FRESH_TRADES_ARE_BOTH_POSITIVE; tail positive returns cannot increase prior max drawdown",
    }


def run(out: Path) -> dict[str, Any]:
    parent = read(PARENT)
    source = read(FRESH)
    validate_source(source)
    if parent.get("lane_id") != "trend_rider_primary_wr8125":
        raise RuntimeError("WR8125_PARENT_LANE_MISMATCH")
    p = parent_algebra(parent)
    fresh_trades = [dict(x) for x in source["trades"]]
    actual = [float(x["net_bps"]) for x in fresh_trades]
    actual_union = union_metrics(p, actual)

    ex = [excursion(x) for x in fresh_trades]
    mfe_upper = [float(x["mfe_net_upper_conservative_bps"]) for x in ex]
    mfe_union = union_metrics(p, mfe_upper)

    required_added_total_for_expectancy = len(actual) * float(p["net_expectancy_bps"])
    required_added_total_for_payoff = len(actual) * float(p["avg_win_bps"])
    actual_added_total = sum(actual)
    mfe_added_total = sum(mfe_upper)

    actual_checks = {
        "T_increase": int(actual_union["trades"]) > int(p["trades"]),
        "WR_non_decrease": float(actual_union["win_rate"]) >= 13 / 16,
        "PnL_non_decrease": float(actual_union["net_pnl_bps"]) >= float(p["net_pnl_bps"]),
        "expectancy_non_decrease": float(actual_union["net_expectancy_bps"]) >= float(p["net_expectancy_bps"]),
        "PF_non_decrease": float(actual_union["profit_factor"]) >= float(p["profit_factor"]),
        "payoff_non_decrease": float(actual_union["payoff"]) >= float(p["payoff"]),
        "DD_non_increase": True,
        "fresh_WR_100pct": all(x > 0 for x in actual),
    }

    if mfe_added_total < required_added_total_for_payoff:
        root = "ENTRY_AMPLITUDE_CEILING_WITHIN_48BARS"
        interpretation = "Even perfect capture of each trade's 48-bar MFE cannot preserve the 81.25 parent payoff; these fresh winners are too small-amplitude for the parent payoff target."
    elif actual_added_total < required_added_total_for_payoff:
        root = "EXIT_CAPTURE_DEFICIENCY_WITHIN_48BARS"
        interpretation = "The 48-bar path contains enough favorable excursion to preserve payoff, but TIMEOUT realizes too little; an EXIT_ONLY causal rule is the next lever."
    else:
        root = "NO_PAYOFF_BOTTLENECK_ON_FRESH2"
        interpretation = "Actual fresh2 economics already preserve the parent payoff."

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_ROOT_CAUSE_DIAGNOSTIC",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "parent_source_receipt_sha256": (parent.get("historical_source") or {}).get("upstream_receipt_sha256"),
        "fresh2_source_receipt_sha256": source.get("receipt_sha256"),
        "parent_metrics_reconstructed": p,
        "fresh2_actual": {
            "trade_count": 2,
            "wins": 2,
            "win_rate": 1.0,
            "net_pnl_bps": actual_added_total,
            "net_expectancy_bps": actual_added_total / 2,
            "exit_reasons": [str(x["reason"]) for x in fresh_trades],
        },
        "actual_16T_plus_2T_union": actual_union,
        "actual_union_checks": actual_checks,
        "payoff_constraint": {
            "parent_avg_win_bps": p["avg_win_bps"],
            "parent_avg_loss_bps": p["avg_loss_bps"],
            "required_added_total_bps_to_preserve_parent_expectancy": required_added_total_for_expectancy,
            "required_added_total_bps_to_preserve_parent_payoff": required_added_total_for_payoff,
            "actual_added_total_bps": actual_added_total,
            "expectancy_shortfall_bps": required_added_total_for_expectancy - actual_added_total,
            "payoff_shortfall_bps": required_added_total_for_payoff - actual_added_total,
        },
        "same_48bar_excursion_diagnostic": ex,
        "perfect_mfe_capture_upper_bound_union": mfe_union,
        "perfect_mfe_added_total_net_bps_conservative": mfe_added_total,
        "root_cause": root,
        "root_cause_interpretation": interpretation,
        "next_axis": "EXIT_ONLY_CAUSAL_CAPTURE_RULE" if root == "EXIT_CAPTURE_DEFICIENCY_WITHIN_48BARS" else "ADD_ONLY_HIGH_AMPLITUDE_ENTRY_QUALITY",
        "policy": {
            "diagnostic_only": True,
            "mfe_upper_bound_not_promotable": True,
            "parent_trade_rewrite_forbidden": True,
            "fresh_trade_outcome_cherry_pick_forbidden": True,
            "entry_ids_immutable": True,
            "production_ssot_unchanged": True,
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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    parent = read(PARENT)
    source = read(FRESH)
    validate_source(source)
    p = parent_algebra(parent)
    actual = [float(x["net_bps"]) for x in source["trades"]]
    u = union_metrics(p, actual)
    assert int(u["trades"]) == 18 and int(u["wins"]) == 15
    assert abs(float(u["win_rate"]) - 15 / 18) < 1e-12
    assert abs(float(u["net_pnl_bps"]) - 23737.115620801866) < 1e-9
    assert abs(float(u["net_expectancy_bps"]) - 1318.7286456001036) < 1e-9
    assert abs(float(u["profit_factor"]) - 65.69865682795493) < 1e-9
    assert abs(float(u["payoff"]) - 13.139731365590984) < 1e-9
    print("PASS_A1_TRENDRIDER_8125_FRESH2_PAYOFF_DIAGNOSTIC_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_8125_fresh2_payoff_diagnostic_v1.json"))
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print("A1_TRENDRIDER_8125_FRESH2_PAYOFF=" + json.dumps({
        "state": r["state"],
        "root_cause": r["root_cause"],
        "actual_union": r["actual_16T_plus_2T_union"],
        "checks": r["actual_union_checks"],
        "mfe_upper_union": r["perfect_mfe_capture_upper_bound_union"],
        "next_axis": r["next_axis"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
