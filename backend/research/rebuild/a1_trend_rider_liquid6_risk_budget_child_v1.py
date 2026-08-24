#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as v1
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as v2
from backend.research.rebuild.a1_exact25_survivor_gate_v1 import stable_sha
from backend.research.rebuild import trend_rider_first_confirmation_long_only_policy_v1 as policy


ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = Path(policy.__file__).resolve()
TOP3_LATEST = ROOT / "backend/research/rebuild/a1_top3_profitability_survivor_latest.json"
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
RISK_SCALE = 1.0 / 3.0
PROSPECTIVE_BOUNDARY_UTC = "2026-08-24T15:00:00Z"
CANDIDATE_ID = "trend_rider_liquid6_losing_basket_guard_v1"


def _metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    # Multi-symbol evaluators append one symbol at a time. Portfolio drawdown
    # must follow the realized equity timeline, never symbol concatenation.
    ordered = sorted(
        trades,
        key=lambda x: (
            int(x.get("exit_ts") or x.get("entry_ts") or x.get("signal_ts") or 0),
            int(x.get("entry_ts") or x.get("signal_ts") or 0),
            str(x.get("symbol") or ""),
        ),
    )
    values = [float(x["net_bps"]) for x in ordered]
    gross = [float(x["gross_bps"]) for x in ordered]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)

    # Exits sharing one exchange timestamp are one observable portfolio equity
    # event.  Sum them atomically so arbitrary symbol ordering cannot create a
    # peak/trough that never existed.
    pnl_by_exit_ts: dict[int, float] = {}
    for row in ordered:
        exit_ts = int(row.get("exit_ts") or row.get("entry_ts") or row.get("signal_ts") or 0)
        pnl_by_exit_ts[exit_ts] = pnl_by_exit_ts.get(exit_ts, 0.0) + float(row["net_bps"])
    timeline_values = [pnl_by_exit_ts[ts] for ts in sorted(pnl_by_exit_ts)]
    return {
        "completed_trades": len(trades),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "net_profit_factor": v1.profit_factor(gp, gl),
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_bps": v1.max_drawdown(timeline_values),
    }


def apply_losing_basket_admission_guard(
    receipt: dict[str, Any],
    bars_by_symbol: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Reject only new cohorts added while the active same-side basket is losing.

    Every mark is the open of the new cohort's entry bar.  The zero threshold is
    sign-only, fixed, and observable before admission; exit outcomes are never
    consulted.
    """
    bar_maps = {
        symbol: {int(bar["ts_ms"]): bar for bar in bars}
        for symbol, bars in bars_by_symbol.items()
    }
    candidates: list[dict[str, Any]] = []
    for row in receipt.get("trades") or []:
        candidates.append({"kind": "completed", "row": dict(row)})
    for row in receipt.get("open_intents") or []:
        candidates.append({"kind": "open", "row": dict(row)})

    cohorts: dict[int, list[dict[str, Any]]] = {}
    for item in candidates:
        entry_ts = int(item["row"]["entry_ts"])
        cohorts.setdefault(entry_ts, []).append(item)

    admitted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for entry_ts in sorted(cohorts):
        active = [
            item for item in active
            if item["kind"] == "open" or int(item["row"]["exit_ts"]) > entry_ts
        ]
        mtm_rows: list[dict[str, Any]] = []
        for item in active:
            row = item["row"]
            symbol = str(row["symbol"])
            bar = bar_maps.get(symbol, {}).get(entry_ts)
            if bar is None:
                raise RuntimeError(f"LOSING_BASKET_MARK_MISSING:{symbol}:{entry_ts}")
            entry_bar = bar_maps.get(symbol, {}).get(int(row["entry_ts"]))
            if entry_bar is None:
                raise RuntimeError(f"LOSING_BASKET_ENTRY_MISSING:{symbol}:{row['entry_ts']}")
            entry = float(row.get("entry") or entry_bar["open"])
            mark = float(bar["open"])
            side = 1.0 if str(row["side"]) == "long" else -1.0
            mtm_bps = side * (mark / entry - 1.0) * 10_000.0
            mtm_rows.append({
                "symbol": symbol,
                "intent_sha": row.get("intent_sha"),
                "entry_ts": int(row["entry_ts"]),
                "mark_ts": entry_ts,
                "instrument_mtm_bps": mtm_bps,
            })
        basket_mtm_bps = sum(float(row["instrument_mtm_bps"]) for row in mtm_rows)
        block = bool(active) and basket_mtm_bps < 0.0
        cohort = sorted(
            cohorts[entry_ts],
            key=lambda item: (str(item["row"]["symbol"]), str(item["kind"])),
        )
        audit.append({
            "entry_ts": entry_ts,
            "active_position_count": len(active),
            "active_symbols": sorted(str(item["row"]["symbol"]) for item in active),
            "instrument_basket_mtm_bps": basket_mtm_bps,
            "portfolio_scaled_basket_mtm_bps": basket_mtm_bps * RISK_SCALE,
            "decision": "BLOCK_NEW_COHORT" if block else "ADMIT_NEW_COHORT",
            "cohort_symbols": [str(item["row"]["symbol"]) for item in cohort],
            "entry_time_observable_only": True,
        })
        if block:
            for item in cohort:
                row = item["row"]
                rejected.append({
                    "kind": item["kind"],
                    "symbol": row["symbol"],
                    "intent_sha": row.get("intent_sha"),
                    "entry_ts": entry_ts,
                    "instrument_basket_mtm_bps": basket_mtm_bps,
                    "reason": "ACTIVE_SAME_SIDE_BASKET_MTM_NEGATIVE",
                })
            continue
        admitted.extend(cohort)
        active.extend(cohort)

    admitted_trades = [item["row"] for item in admitted if item["kind"] == "completed"]
    admitted_open = [item["row"] for item in admitted if item["kind"] == "open"]
    native = dict(receipt.get("native_policy_ownership") or {})
    native["pre_portfolio_guard_admitted_completed_trade_count"] = native.get("admitted_completed_trade_count")
    native["pre_portfolio_guard_admitted_open_intent_count"] = native.get("admitted_open_intent_count")
    native["admitted_completed_trade_count"] = len(admitted_trades)
    native["admitted_open_intent_count"] = len(admitted_open)
    receipt["native_policy_ownership"] = native
    receipt["trades"] = admitted_trades
    receipt["open_intents"] = admitted_open
    receipt["completed_trades"] = len(admitted_trades)
    receipt["portfolio_admission_guard"] = {
        "state": "PASS_ENTRY_TIME_OBSERVABLE_SIGN_ONLY_GUARD",
        "axis": "ACTIVE_SAME_SIDE_BASKET_MTM_SIGN",
        "admission_rule": "block new cohort iff active basket gross MTM < 0 bps",
        "threshold_bps": 0.0,
        "threshold_sweep": False,
        "outcome_fields_used": False,
        "post_outcome_symbol_selection": False,
        "raw_candidate_count": len(candidates),
        "admitted_candidate_count": len(admitted),
        "rejected_candidate_count": len(rejected),
        "rejected": rejected,
        "rejected_sha256": stable_sha(rejected),
        "audit": audit,
    }
    return receipt


def apply_portfolio_risk_budget(receipt: dict[str, Any]) -> dict[str, Any]:
    scaled: list[dict[str, Any]] = []
    for source in receipt.get("trades") or []:
        row = dict(source)
        row["instrument_gross_bps"] = float(row["gross_bps"])
        row["instrument_net_bps"] = float(row["net_bps"])
        row["instrument_realized_cost_bps"] = float(row["realized_cost_bps"])
        row["gross_bps"] = row["instrument_gross_bps"] * RISK_SCALE
        row["net_bps"] = row["instrument_net_bps"] * RISK_SCALE
        row["realized_cost_bps"] = row["instrument_realized_cost_bps"] * RISK_SCALE
        row["portfolio_risk_scale"] = RISK_SCALE
        scaled.append(row)
    receipt["trades"] = scaled
    receipt["completed_trades"] = len(scaled)
    receipt["metrics"] = _metrics(scaled)
    receipt["portfolio_risk_budget"] = {
        "state": "PASS_FIXED_NON_OUTCOME_FITTED_RISK_BUDGET",
        "baseline_max_concurrent_positions": 2,
        "expanded_max_concurrent_positions": 6,
        "position_risk_scale": RISK_SCALE,
        "maximum_gross_risk_units": 2.0,
        "formula": "baseline_max_concurrent_positions / expanded_max_concurrent_positions",
        "outcome_fitted": False,
        "threshold_sweep": False,
    }
    return receipt


def _parent_metrics(parent_receipt: Path | None = None) -> dict[str, Any]:
    if parent_receipt is not None:
        receipt = json.loads(parent_receipt.read_text(encoding="utf-8"))
        metrics = dict(receipt["metrics"])
        return {
            "completed_trades": int(receipt["completed_trades"]),
            "win_rate": metrics["win_rate"],
            "net_pnl_bps": metrics["net_pnl_bps"],
            "net_expectancy_bps": metrics["net_expectancy_bps"],
            "profit_factor": metrics.get("net_profit_factor", metrics.get("profit_factor")),
            "max_drawdown_bps": metrics["max_drawdown_bps"],
            "policy_fidelity": dict(receipt.get("policy_fidelity") or receipt.get("native_policy_ownership") or {}),
            "receipt_sha256": receipt.get("receipt_sha256"),
        }
    top3 = json.loads(TOP3_LATEST.read_text(encoding="utf-8"))
    row = next(x for x in top3["candidates"] if x["identity"] == "trend_rider_transition_freshness")
    metrics = dict(row["profit_lane"]["metrics"])
    fidelity = dict(row.get("policy_fidelity") or {})
    return {
        **metrics,
        "max_drawdown_bps": 219.06777382538303,
        "policy_fidelity": fidelity,
    }


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _comparison(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    p_n = int(parent.get("completed_trades") or 0)
    c_n = int(child.get("completed_trades") or 0)
    raw = {
        "parent_win_rate": parent.get("win_rate"),
        "child_win_rate": child.get("win_rate"),
        "parent_net_pnl_bps": parent.get("net_pnl_bps"),
        "child_net_pnl_bps": child.get("net_pnl_bps"),
        "parent_max_drawdown_bps": parent.get("max_drawdown_bps"),
        "child_max_drawdown_bps": child.get("max_drawdown_bps"),
        "parent_profit_factor": parent.get("profit_factor"),
        "child_profit_factor": child.get("net_profit_factor"),
    }
    values = {key: _finite(value) for key, value in raw.items()}
    blockers = [key.upper() + "_UNAVAILABLE" for key, value in values.items() if value is None]
    if p_n <= 0:
        blockers.append("PARENT_COMPLETED_TRADES_ZERO")
    if c_n <= 0:
        blockers.append("CHILD_COMPLETED_TRADES_ZERO")
    p_pnl = values["parent_net_pnl_bps"]
    p_dd = values["parent_max_drawdown_bps"]
    c_dd = values["child_max_drawdown_bps"]
    if p_pnl == 0.0:
        blockers.append("PARENT_NET_PNL_ZERO")
    if p_dd is not None and p_dd <= 0.0:
        blockers.append("PARENT_DRAWDOWN_NONPOSITIVE")
    if c_dd is not None and c_dd <= 0.0:
        blockers.append("CHILD_DRAWDOWN_NONPOSITIVE")
    if blockers:
        return {
            "state": "PENDING_COMPARABLE_SAMPLE",
            "pareto_pass": False,
            "blockers": sorted(set(blockers)),
            "parent_completed_trades": p_n,
            "child_completed_trades": c_n,
        }

    p_wr = values["parent_win_rate"]; c_wr = values["child_win_rate"]
    c_pnl = values["child_net_pnl_bps"]
    p_pf = values["parent_profit_factor"]; c_pf = values["child_profit_factor"]
    assert None not in (p_wr, c_wr, p_pnl, c_pnl, p_dd, c_dd, p_pf, c_pf)
    return {
        "state": "PASS_COMPARABLE_SAMPLE",
        "blockers": [],
        "trade_count_delta": c_n - p_n,
        "trade_count_improvement_pct": ((c_n / p_n) - 1.0) * 100.0,
        "win_rate_delta_pp": (c_wr - p_wr) * 100.0,
        "net_pnl_delta_bps": c_pnl - p_pnl,
        "net_pnl_improvement_pct": ((c_pnl / p_pnl) - 1.0) * 100.0,
        "max_drawdown_delta_bps": c_dd - p_dd,
        "max_drawdown_improvement_pct": (1.0 - c_dd / p_dd) * 100.0,
        "profit_factor_delta": c_pf - p_pf,
        "return_to_drawdown_parent": p_pnl / p_dd,
        "return_to_drawdown_child": c_pnl / c_dd,
        "pareto_pass": c_n > p_n and c_wr > p_wr and c_pnl > p_pnl and c_dd < p_dd and c_pf > p_pf,
    }


def evaluate(
    out: Path,
    *,
    mode: str,
    boundary_utc: str | None,
    parent_receipt: Path | None = None,
) -> dict[str, Any]:
    ledger = json.loads(v1.LEDGER_PATH.read_text(encoding="utf-8"))
    original_boundary = str(ledger["strategies"]["trend_rider"]["prospective_boundary_utc"])
    boundary = boundary_utc or original_boundary
    if mode == "prospective" and not boundary_utc:
        raise RuntimeError("PROSPECTIVE_BOUNDARY_REQUIRED")
    ledger["strategies"]["trend_rider"]["prospective_boundary_utc"] = boundary
    ledger["strategies"]["trend_rider"]["status"] = "ACTIVE"

    original_load_policy = v1.load_policy
    original_ledger_path = v1.LEDGER_PATH
    with tempfile.TemporaryDirectory(prefix="trend-rider-liquid6-risk-budget-") as tmp:
        ledger_path = Path(tmp) / "ledger.json"
        ledger_path.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")

        def load_policy(_: str, __: dict[str, Any]):
            return policy, POLICY_PATH, v1.git_blob_sha(POLICY_PATH)

        v1.load_policy = load_policy
        v1.LEDGER_PATH = ledger_path
        old_argv = sys.argv
        try:
            sys.argv = [
                "a1_exact25_generic_evaluator_v2",
                "--strategy-id", "trend_rider",
                "--symbols", ",".join(SYMBOLS),
                "--out", str(out),
            ]
            v2.main()
        finally:
            sys.argv = old_argv
            v1.load_policy = original_load_policy
            v1.LEDGER_PATH = original_ledger_path

    raw_receipt = json.loads(out.read_text(encoding="utf-8"))
    if (raw_receipt.get("trades") or raw_receipt.get("open_intents")):
        cfg = v1.config_instance(policy)
        interval = v1.interval_for_ms(int(getattr(cfg, "timeframe_ms")))
        bars_by_symbol = {symbol: v1.fetch_bars(symbol, interval, 1000) for symbol in SYMBOLS}
        raw_receipt = apply_losing_basket_admission_guard(raw_receipt, bars_by_symbol)
    else:
        raw_receipt["portfolio_admission_guard"] = {
            "state": "PENDING_FIRST_CANDIDATE",
            "axis": "ACTIVE_SAME_SIDE_BASKET_MTM_SIGN",
            "admission_rule": "block new cohort iff active basket gross MTM < 0 bps",
            "threshold_bps": 0.0,
            "threshold_sweep": False,
            "outcome_fields_used": False,
            "post_outcome_symbol_selection": False,
            "raw_candidate_count": 0,
            "admitted_candidate_count": 0,
            "rejected_candidate_count": 0,
            "rejected": [],
            "rejected_sha256": stable_sha([]),
            "audit": [],
        }
    receipt = apply_portfolio_risk_budget(raw_receipt)
    parent = _parent_metrics(parent_receipt)
    comparison = _comparison(parent, receipt["metrics"]) if parent_receipt is not None or mode == "development" else None
    by_symbol = {}
    for symbol in SYMBOLS:
        rows = [x for x in receipt["trades"] if x["symbol"] == symbol]
        by_symbol[symbol] = _metrics(rows)
    receipt.update({
        "schema_version": "zel.a1.trend_rider.liquid6_losing_basket_guard_child.v1",
        "candidate_id": CANDIDATE_ID,
        "evaluation_mode": mode,
        "original_parent_boundary_utc": original_boundary,
        "prospective_boundary_utc": boundary if mode == "prospective" else None,
        "symbols": list(SYMBOLS),
        "changed_axes": ["LIQUID6_UNIVERSE_DIVERSIFICATION", "LONG_ONLY_ADMISSION", "ACTIVE_SAME_SIDE_BASKET_MTM_SIGN"],
        "portfolio_normalization_axis": "FIXED_TOTAL_RISK_BUDGET",
        "side_specialization_preregistered": "LONG_ONLY",
        "development_parent_metrics": parent if mode == "development" else None,
        "development_comparison": comparison,
        "by_symbol": by_symbol,
        "parameter_sweep": False,
        "post_outcome_threshold_fit": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "next": "ACCUMULATE_FRESH_TO_12_THEN_A2_A3" if mode == "prospective" else "PREREGISTER_FUTURE_BOUNDARY_IF_PARETO_PASS",
    })
    receipt["receipt_sha256"] = stable_sha({k: value for k, value in receipt.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def self_test() -> int:
    raw = {
        "trades": [
            {"exit_ts": 1, "gross_bps": 33.0, "net_bps": 30.0, "realized_cost_bps": 3.0},
            {"exit_ts": 2, "gross_bps": -12.0, "net_bps": -15.0, "realized_cost_bps": 3.0},
        ]
    }
    row = apply_portfolio_risk_budget(raw)
    assert row["metrics"]["net_pnl_bps"] == 5.0
    assert row["metrics"]["max_drawdown_bps"] == 5.0
    assert row["portfolio_risk_budget"]["outcome_fitted"] is False
    guarded = apply_losing_basket_admission_guard(
        {
            "trades": [
                {"symbol": "BTC-USDT", "entry_ts": 1, "exit_ts": 4, "entry": 100.0, "side": "long", "intent_sha": "a"},
                {"symbol": "ETH-USDT", "entry_ts": 2, "exit_ts": 5, "entry": 50.0, "side": "long", "intent_sha": "b"},
                {"symbol": "SOL-USDT", "entry_ts": 3, "exit_ts": 6, "entry": 25.0, "side": "long", "intent_sha": "c"},
            ],
            "open_intents": [],
            "native_policy_ownership": {"admitted_completed_trade_count": 3, "admitted_open_intent_count": 0},
        },
        {
            "BTC-USDT": [
                {"ts_ms": 1, "open": 100.0}, {"ts_ms": 2, "open": 90.0}, {"ts_ms": 3, "open": 105.0},
            ],
            "ETH-USDT": [{"ts_ms": 2, "open": 50.0}, {"ts_ms": 3, "open": 51.0}],
            "SOL-USDT": [{"ts_ms": 3, "open": 25.0}],
        },
    )
    assert [x["symbol"] for x in guarded["trades"]] == ["BTC-USDT", "SOL-USDT"]
    assert guarded["portfolio_admission_guard"]["rejected_candidate_count"] == 1
    assert guarded["portfolio_admission_guard"]["outcome_fields_used"] is False
    chronological = _metrics([
        {"symbol": "BTC-USDT", "exit_ts": 2, "gross_bps": 100.0, "net_bps": 100.0},
        {"symbol": "BTC-USDT", "exit_ts": 4, "gross_bps": -90.0, "net_bps": -90.0},
        {"symbol": "ETH-USDT", "exit_ts": 1, "gross_bps": -80.0, "net_bps": -80.0},
        {"symbol": "ETH-USDT", "exit_ts": 3, "gross_bps": 100.0, "net_bps": 100.0},
    ])
    assert chronological["max_drawdown_bps"] == 90.0
    simultaneous = _metrics([
        {"symbol": "BTC-USDT", "exit_ts": 1, "gross_bps": 100.0, "net_bps": 100.0},
        {"symbol": "ETH-USDT", "exit_ts": 1, "gross_bps": -90.0, "net_bps": -90.0},
        {"symbol": "SOL-USDT", "exit_ts": 2, "gross_bps": -50.0, "net_bps": -50.0},
    ])
    assert simultaneous["max_drawdown_bps"] == 50.0
    pending = _comparison(
        {"completed_trades": 0, "win_rate": None, "net_pnl_bps": 0.0, "max_drawdown_bps": 0.0, "profit_factor": None},
        {"completed_trades": 0, "win_rate": None, "net_pnl_bps": 0.0, "max_drawdown_bps": 0.0, "net_profit_factor": None},
    )
    assert pending["state"] == "PENDING_COMPARABLE_SAMPLE" and pending["pareto_pass"] is False
    comparable = _comparison(
        {"completed_trades": 1, "win_rate": 0.5, "net_pnl_bps": 100.0, "max_drawdown_bps": 50.0, "profit_factor": 2.0},
        {"completed_trades": 2, "win_rate": 0.75, "net_pnl_bps": 150.0, "max_drawdown_bps": 40.0, "net_profit_factor": 3.0},
    )
    assert comparable["state"] == "PASS_COMPARABLE_SAMPLE" and comparable["pareto_pass"] is True
    print("PASS_TREND_RIDER_LIQUID6_RISK_BUDGET_CHILD_V1")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_liquid6_risk_budget_child_v1.json"))
    parser.add_argument("--mode", choices=("development", "prospective"), default="development")
    parser.add_argument("--boundary-utc")
    parser.add_argument("--parent-receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    row = evaluate(
        args.out,
        mode=args.mode,
        boundary_utc=args.boundary_utc,
        parent_receipt=args.parent_receipt,
    )
    print("A1_TREND_RIDER_LIQUID6_RISK_BUDGET=" + json.dumps({
        "mode": args.mode,
        "completed_trades": row["completed_trades"],
        "metrics": row["metrics"],
        "comparison": row["development_comparison"],
        "receipt_sha256": row["receipt_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
