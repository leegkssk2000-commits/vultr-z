from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_terminal_evaluator_v1 as v1

VERSION = "ZEL_COMPOSITE_TERMINAL_EVALUATOR_V2"


def finite_metrics(rows: Sequence[Mapping[str, Any]], field: str = "realized_R") -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (str(row.get("exit_ts") or ""), str(row.get("event_id") or "")),
    )
    values = [v1.safe_float(row.get(field), 0.0) or 0.0 for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    mfe = [v1.safe_float(row.get("MFE_R")) for row in ordered]
    mae = [v1.safe_float(row.get("MAE_R")) for row in ordered]
    exposure = [v1.safe_float(row.get("time_exposure_min")) for row in ordered]
    fees = [v1.safe_float(row.get("fee"), 0.0) or 0.0 for row in ordered]
    slippage = [v1.safe_float(row.get("slippage"), 0.0) or 0.0 for row in ordered]
    funding = [v1.safe_float(row.get("funding_pnl_estimate_usdt"), 0.0) or 0.0 for row in ordered]
    return {
        "sample_count": len(values),
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "median_R": statistics.median(values) if values else None,
        "win_rate_pct": (len(wins) / len(values) * 100.0) if values else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "profit_factor_is_infinite": bool(values and gross_profit > 0 and gross_loss == 0),
        "gross_profit_R": gross_profit,
        "gross_loss_R": gross_loss,
        "max_drawdown_R": v1.max_drawdown(values),
        "average_MFE_R": statistics.fmean(value for value in mfe if value is not None)
        if any(value is not None for value in mfe)
        else None,
        "average_MAE_R": statistics.fmean(value for value in mae if value is not None)
        if any(value is not None for value in mae)
        else None,
        "average_exposure_min": statistics.fmean(value for value in exposure if value is not None)
        if any(value is not None for value in exposure)
        else None,
        "fee_total_usdt": sum(fees),
        "slippage_total_usdt": sum(slippage),
        "funding_total_usdt": sum(funding),
    }


def evaluate(
    terminal_root: Path,
    plan_path: Path,
    contract_path: Path,
    source_root: Path,
    method_behavior_path: Path,
) -> dict[str, Any]:
    method_behavior = v1.load_json(method_behavior_path)
    if method_behavior.get("schema_version") != "zel.trade_method.runtime_behavior.receipt.v1":
        raise RuntimeError("TRADE_METHOD_BEHAVIOR_SCHEMA_INVALID")
    if method_behavior.get("unsafe_strategy_count") not in {0, None}:
        raise RuntimeError("TRADE_METHOD_BEHAVIOR_AUTHORITY_UNSAFE")

    original_metrics = v1.metrics
    original_behavior = v1.trade_method_behavior
    v1.metrics = finite_metrics
    v1.trade_method_behavior = lambda source_root_arg, strategy_ids: method_behavior
    try:
        result = v1.evaluate(
            terminal_root,
            plan_path,
            contract_path,
            source_root,
        )
    finally:
        v1.metrics = original_metrics
        v1.trade_method_behavior = original_behavior

    result["schema_version"] = "zel.composite.post_terminal_sequence.receipt.v2"
    result["version"] = VERSION
    result["trade_method_behavior_receipt_sha256"] = method_behavior.get("receipt_sha256")
    result["runtime_behavior_injected"] = True
    result["receipt_sha256"] = v1.stable_sha(result)
    return result


def self_test() -> None:
    rows = [
        {
            "event_id": "e1",
            "exit_ts": "2026-01-01T00:00:00Z",
            "realized_R": 1.0,
            "MFE_R": 1.2,
            "MAE_R": -0.1,
            "time_exposure_min": 10.0,
            "fee": 0.1,
            "slippage": 0.01,
        }
    ]
    row = finite_metrics(rows)
    assert row["profit_factor"] is None, row
    assert row["profit_factor_is_infinite"] is True, row
    assert math.isfinite(float(row["net_R"])), row
    json.dumps(row, allow_nan=False)
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--method-behavior", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.terminal_root,
        args.plan,
        args.contract,
        args.source_root,
        args.method_behavior,
        args.out_dir,
    )
    if any(value is None for value in required):
        parser.error(
            "terminal-root, plan, contract, source-root, method-behavior and out-dir are required"
        )
    result = evaluate(
        args.terminal_root.resolve(),
        args.plan.resolve(),
        args.contract.resolve(),
        args.source_root.resolve(),
        args.method_behavior.resolve(),
    )
    v1.write_outputs(args.out_dir.resolve(), result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "sequence_id": result["sequence_id"],
                "trades": result["closed_trade_count"],
                "windows": result["window_trade_counts"],
                "economic_survivors": result["economic_survivor_count"],
                "incumbent_retained": result["incumbent_retained"],
                "errors": result["errors"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
