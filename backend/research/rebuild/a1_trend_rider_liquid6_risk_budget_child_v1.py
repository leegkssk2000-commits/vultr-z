#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
PROSPECTIVE_BOUNDARY_UTC = "2026-08-24T04:00:00Z"


def _metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    return {
        "completed_trades": len(trades),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "net_profit_factor": v1.profit_factor(gp, gl),
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_bps": v1.max_drawdown(values),
    }


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


def _comparison(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    p_n = int(parent["completed_trades"])
    c_n = int(child["completed_trades"])
    p_wr, c_wr = float(parent["win_rate"]), float(child["win_rate"])
    p_pnl, c_pnl = float(parent["net_pnl_bps"]), float(child["net_pnl_bps"])
    p_dd, c_dd = float(parent["max_drawdown_bps"]), float(child["max_drawdown_bps"])
    p_pf, c_pf = float(parent["profit_factor"]), float(child["net_profit_factor"])
    return {
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

    receipt = apply_portfolio_risk_budget(json.loads(out.read_text(encoding="utf-8")))
    parent = _parent_metrics(parent_receipt)
    comparison = _comparison(parent, receipt["metrics"]) if parent_receipt is not None or mode == "development" else None
    by_symbol = {}
    for symbol in SYMBOLS:
        rows = [x for x in receipt["trades"] if x["symbol"] == symbol]
        by_symbol[symbol] = _metrics(rows)
    receipt.update({
        "schema_version": "zel.a1.trend_rider.liquid6_risk_budget_child.v1",
        "candidate_id": policy.CANDIDATE_IDENTITY,
        "evaluation_mode": mode,
        "original_parent_boundary_utc": original_boundary,
        "prospective_boundary_utc": boundary if mode == "prospective" else None,
        "symbols": list(SYMBOLS),
        "changed_axes": ["LIQUID6_UNIVERSE_DIVERSIFICATION", "LONG_ONLY_ADMISSION"],
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
            {"gross_bps": 33.0, "net_bps": 30.0, "realized_cost_bps": 3.0},
            {"gross_bps": -12.0, "net_bps": -15.0, "realized_cost_bps": 3.0},
        ]
    }
    row = apply_portfolio_risk_budget(raw)
    assert row["metrics"]["net_pnl_bps"] == 5.0
    assert row["metrics"]["max_drawdown_bps"] == 5.0
    assert row["portfolio_risk_budget"]["outcome_fitted"] is False
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
