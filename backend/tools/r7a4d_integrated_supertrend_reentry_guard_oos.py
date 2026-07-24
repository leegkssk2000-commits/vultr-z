from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import r7a4d_integrated_supertrend_bingx_real_oos as source
from r7a4d_integrated_supertrend_reentry_guard_replay import run_replay

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_reentry_guard_oos_v1"
BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
FAILED_VARIANT_DIRNAME = "r7a4d_integrated_supertrend_cost_aware_lock_oos_v1"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _aggregate_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    aggregate = summary.get("aggregate")
    return aggregate if isinstance(aggregate, dict) else {}


def _metric(aggregate: dict[str, Any], key: str) -> float | None:
    return _finite_float(aggregate.get(key))


def _self_check() -> None:
    assert source.INTERVAL == "15m"
    assert source.INTERVAL_MS == 900_000
    assert len(source.SYMBOLS) == 5


def main() -> int:
    _self_check()
    parser = argparse.ArgumentParser(
        description="Single-causal OOS: block same-side reentry after a profit-lock exit until structural reset"
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--evaluation-bars", type=int, default=3600)
    parser.add_argument("--warmup-bars", type=int, default=400)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--arm-cost-multiple", type=float, default=3.0)
    parser.add_argument("--lock-net-bps", type=float, default=1.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = root / "runtime" / OUTPUT_DIRNAME
    baseline_summary_path = root / "runtime" / BASELINE_DIRNAME / "summary_v1.json"
    failed_summary_path = root / "runtime" / FAILED_VARIANT_DIRNAME / "summary_v1.json"
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )
    if args.evaluation_bars < 1000 or args.warmup_bars < 250:
        raise ValueError("BAR_CONTRACT_INVALID")
    if args.arm_cost_multiple <= 0 or args.lock_net_bps < 0:
        raise ValueError("PROFIT_LOCK_CONTRACT_INVALID")

    results: list[dict[str, Any]] = []
    blockers: list[str] = []
    returns: list[float] = []
    gross_returns: list[float] = []
    armed_trades = 0
    lock_exits = 0
    blocked_signals = 0
    resets = 0

    for symbol in symbols:
        try:
            raw, endpoint = source.fetch(symbol, args.evaluation_bars + args.warmup_bars)
            enriched = source.geometry(raw, args.warmup_bars)
            checks = source.prefix_check(raw, args.warmup_bars)
            csv_path = output / f"{symbol.lower()}_15m.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            enriched.to_csv(csv_path, index=False)
            replay = run_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_REENTRY_GUARD",
                cost_bps_per_side=args.cost_bps_per_side,
                arm_cost_multiple=args.arm_cost_multiple,
                lock_net_bps=args.lock_net_bps,
            )
            source.atomic_json(output / f"{symbol.lower()}_replay.json", replay)
            symbol_net = [float(trade["net_return_pct"]) for trade in replay["trades"]]
            symbol_gross = [float(trade["gross_return_pct"]) for trade in replay["trades"]]
            returns.extend(symbol_net)
            gross_returns.extend(symbol_gross)
            armed_trades += int(replay["profit_lock_armed_trade_count"])
            lock_exits += int(replay["profit_lock_exit_count"])
            blocked_signals += int(replay["reentry_blocked_signal_count"])
            resets += int(replay["reentry_reset_count"])
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "endpoint": endpoint,
                    "rows": len(raw),
                    "prefix_checks": checks,
                    "csv": str(csv_path),
                    "trade_count": replay["trade_count"],
                    "win_count": replay["win_count"],
                    "win_rate_pct": replay["win_rate_pct"],
                    "gross_return_pct": replay["gross_return_pct"],
                    "net_return_pct": replay["net_return_pct"],
                    "gross_profit_factor": replay["gross_profit_factor"],
                    "net_profit_factor": replay["net_profit_factor"],
                    "max_drawdown_pct": replay["max_drawdown_pct"],
                    "profit_lock_armed_trade_count": replay["profit_lock_armed_trade_count"],
                    "profit_lock_exit_count": replay["profit_lock_exit_count"],
                    "reentry_blocked_signal_count": replay["reentry_blocked_signal_count"],
                    "reentry_reset_count": replay["reentry_reset_count"],
                    "reentry_block_side_at_end": replay["reentry_block_side_at_end"],
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    passed = [row for row in results if row["status"] == "PASS"]
    trades = sum(int(row.get("trade_count", 0)) for row in passed)
    wins = sum(int(row.get("win_count", 0)) for row in passed)
    aggregate = {
        "trade_count": trades,
        "win_count": wins,
        "win_rate_pct": wins / trades * 100.0 if trades else None,
        "gross_return_pct_sum": sum(gross_returns),
        "net_return_pct_sum": sum(returns),
        "gross_profit_factor": source.pf(gross_returns),
        "net_profit_factor": source.pf(returns),
        "positive_symbol_count": sum(float(row.get("net_return_pct", 0.0)) > 0 for row in passed),
        "profit_lock_armed_trade_count": armed_trades,
        "profit_lock_exit_count": lock_exits,
        "reentry_blocked_signal_count": blocked_signals,
        "reentry_reset_count": resets,
    }

    baseline_summary = _load_json(baseline_summary_path)
    failed_summary = _load_json(failed_summary_path)
    baseline = _aggregate_from_summary(baseline_summary)
    failed = _aggregate_from_summary(failed_summary)

    baseline_trades = int(baseline.get("trade_count", 0) or 0)
    baseline_net = _metric(baseline, "net_return_pct_sum")
    baseline_gross = _metric(baseline, "gross_return_pct_sum")
    baseline_net_pf = _metric(baseline, "net_profit_factor")
    baseline_gross_pf = _metric(baseline, "gross_profit_factor")

    failed_trades = int(failed.get("trade_count", 0) or 0)
    failed_net = _metric(failed, "net_return_pct_sum")
    failed_gross = _metric(failed, "gross_return_pct_sum")
    failed_net_pf = _metric(failed, "net_profit_factor")
    failed_gross_pf = _metric(failed, "gross_profit_factor")

    baseline_comparison = {
        "summary": str(baseline_summary_path),
        "available": bool(baseline),
        "trade_count": baseline_trades or None,
        "trade_count_delta": trades - baseline_trades if baseline_trades else None,
        "gross_return_pct_sum": baseline_gross,
        "gross_return_delta": aggregate["gross_return_pct_sum"] - baseline_gross if baseline_gross is not None else None,
        "net_return_pct_sum": baseline_net,
        "net_return_delta": aggregate["net_return_pct_sum"] - baseline_net if baseline_net is not None else None,
        "gross_profit_factor": baseline_gross_pf,
        "gross_pf_delta": aggregate["gross_profit_factor"] - baseline_gross_pf if baseline_gross_pf is not None else None,
        "net_profit_factor": baseline_net_pf,
        "net_pf_delta": aggregate["net_profit_factor"] - baseline_net_pf if baseline_net_pf is not None else None,
    }
    failed_variant_comparison = {
        "summary": str(failed_summary_path),
        "available": bool(failed),
        "trade_count": failed_trades or None,
        "trade_count_delta": trades - failed_trades if failed_trades else None,
        "gross_return_pct_sum": failed_gross,
        "gross_return_delta": aggregate["gross_return_pct_sum"] - failed_gross if failed_gross is not None else None,
        "net_return_pct_sum": failed_net,
        "net_return_delta": aggregate["net_return_pct_sum"] - failed_net if failed_net is not None else None,
        "gross_profit_factor": failed_gross_pf,
        "gross_pf_delta": aggregate["gross_profit_factor"] - failed_gross_pf if failed_gross_pf is not None else None,
        "net_profit_factor": failed_net_pf,
        "net_pf_delta": aggregate["net_profit_factor"] - failed_net_pf if failed_net_pf is not None else None,
    }

    data_pass = len(passed) == len(symbols) and trades > 0 and not blockers
    causal_recovery = bool(
        data_pass
        and failed
        and failed_net is not None
        and failed_net_pf is not None
        and aggregate["net_return_pct_sum"] > failed_net
        and aggregate["net_profit_factor"] > failed_net_pf
        and (not failed_trades or trades < failed_trades)
    )
    baseline_restored = bool(
        data_pass
        and baseline
        and baseline_net is not None
        and baseline_gross is not None
        and baseline_net_pf is not None
        and baseline_gross_pf is not None
        and trades <= baseline_trades
        and aggregate["gross_return_pct_sum"] >= baseline_gross
        and aggregate["gross_profit_factor"] >= baseline_gross_pf
        and aggregate["net_return_pct_sum"] > baseline_net
        and aggregate["net_profit_factor"] > baseline_net_pf
    )
    economic_survivor = bool(
        data_pass
        and aggregate["net_return_pct_sum"] > 0.0
        and aggregate["net_profit_factor"] > 1.0
        and aggregate["positive_symbol_count"] >= 3
    )

    if economic_survivor:
        state = "PASS_R7A4D_REENTRY_GUARD_ECONOMIC_SURVIVOR"
        next_stage = "FREEZE_SINGLE_STRATEGY_AND_RUN_SECOND_NONOVERLAPPING_OOS"
    elif baseline_restored:
        state = "PASS_R7A4D_REENTRY_GUARD_BASELINE_RESTORED_NOT_SURVIVOR"
        next_stage = "SELECT_ONE_REMAINING_NET_LOSS_CLUSTER_ONLY"
    elif causal_recovery:
        state = "HOLD_R7A4D_REENTRY_GUARD_CAUSAL_RECOVERY_NOT_SURVIVOR"
        next_stage = "SELECT_ONE_REMAINING_NET_LOSS_CLUSTER_ONLY"
    else:
        state = "HOLD_R7A4D_REENTRY_GUARD_NO_CAUSAL_RECOVERY"
        next_stage = "ROLLBACK_REENTRY_GUARD_AND_REASSESS_PROFIT_LOCK_EXIT"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "single_causal_repair": True,
        "strategy_id": "integrated_supertrend_pullback_v1",
        "base_entry_signal_formula_unchanged": True,
        "post_profit_lock_reentry_guard_added": True,
        "exit_policy_id": "completed_close_3x_cost_arm_plus_1bp_net_lock_v1",
        "reentry_guard_policy_id": "block_same_side_after_profit_lock_until_opposite_st_or_dema200_cross_v1",
        "target_sha": args.target_sha,
        "source": "BingX public perpetual klines",
        "interval": source.INTERVAL,
        "symbols": symbols,
        "evaluation_bars": args.evaluation_bars,
        "warmup_bars": args.warmup_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "arm_cost_multiple": args.arm_cost_multiple,
        "lock_net_bps": args.lock_net_bps,
        "results": results,
        "aggregate": aggregate,
        "baseline_comparison": baseline_comparison,
        "failed_variant_comparison": failed_variant_comparison,
        "causal_recovery": causal_recovery,
        "baseline_restored": baseline_restored,
        "economic_survivor": economic_survivor,
        "pass_contract": {
            "causal_recovery": "net return and net PF improve versus failed profit-lock variant, with fewer trades",
            "baseline_restored": "trades <= baseline; gross return/PF >= baseline; net return/PF > baseline",
            "economic_survivor": "net return > 0; net PF > 1; positive symbols >= 3/5",
        },
        "blockers": blockers,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(passed)}/{len(symbols)}")
    print(f"TRADES={trades}")
    print(f"WIN_RATE_PCT={aggregate['win_rate_pct']}")
    print(f"GROSS_RETURN_PCT_SUM={aggregate['gross_return_pct_sum']:.6f}")
    print(f"NET_RETURN_PCT_SUM={aggregate['net_return_pct_sum']:.6f}")
    print(f"GROSS_PF={aggregate['gross_profit_factor']}")
    print(f"NET_PF={aggregate['net_profit_factor']}")
    print(f"POSITIVE_SYMBOLS={aggregate['positive_symbol_count']}/{len(symbols)}")
    print(f"PROFIT_LOCK_EXITS={lock_exits}")
    print(f"REENTRY_BLOCKED_SIGNALS={blocked_signals}")
    print(f"REENTRY_RESETS={resets}")
    print(f"FAILED_VARIANT_NET_DELTA={failed_variant_comparison['net_return_delta']}")
    print(f"FAILED_VARIANT_PF_DELTA={failed_variant_comparison['net_pf_delta']}")
    print(f"BASELINE_NET_DELTA={baseline_comparison['net_return_delta']}")
    print(f"BASELINE_PF_DELTA={baseline_comparison['net_pf_delta']}")
    print(f"CAUSAL_RECOVERY={str(causal_recovery).lower()}")
    print(f"BASELINE_RESTORED={str(baseline_restored).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"SUMMARY_JSON={output / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"RC={0 if data_pass else 2}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
