from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_entry_origin_anatomy as anatomy
import r7a4d_integrated_supertrend_linkusdt_single_loss_cluster_oos as survivor_filter
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as shared
import r7a4d_integrated_supertrend_survivor_dema_second_nonoverlap_oos as second_oos

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_counter_break_contract_full_replay_v1"
POLICY_ID = "counter_trend_break_up_requires_structure_and_two_confluence_pullback_route_v1"
REJECT_REASON = "ENTRY_REJECT_COUNTER_TREND_BREAK_UP_INVALID_PULLBACK_CONTRACT"
FIRST_DATA_DIRNAME = survivor_filter.BASELINE_DIRNAME
SECOND_DATA_DIRNAME = second_oos.OUTPUT_DIRNAME
EXPECTED_FIRST = (209, 76, 133)
EXPECTED_SECOND = (222, 63, 159)


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def stats(trades: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return anatomy._stats(list(trades))


def delta(candidate: Any, control: Any) -> Any:
    return float(candidate) - float(control) if finite(candidate) and finite(control) else None


def invalid_counter_break(context: Mapping[str, Any], side: str) -> bool:
    if side != baseline.LONG:
        return False
    triggers = {str(v) for v in context.get("trigger_components", []) if v}
    confirms = {str(v) for v in context.get("confirmation_components", []) if v}
    pullback_only = "confirmation_edge" in triggers and not ({"supertrend_flip", "dema_cross"} & triggers)
    structure_valid = bool(context.get("structure_valid"))
    try:
        confluence_count = int(context.get("confluence_count", 0) or 0)
    except (TypeError, ValueError):
        confluence_count = 0
    return bool(
        "counter_trend_break_up" in confirms
        and pullback_only
        and ((not structure_valid) or confluence_count < 2)
    )


def run_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    fold_id: str,
    cost_bps_per_side: float,
    gate_enabled: bool,
) -> Dict[str, Any]:
    original_compute: Callable[..., pd.DataFrame] = baseline.compute_features
    blocked: List[Dict[str, Any]] = []

    def filtered_compute(source_frame: pd.DataFrame, cfg: Any) -> pd.DataFrame:
        features = original_compute(source_frame, cfg).copy()
        for position in range(len(features)):
            for side, column in ((baseline.LONG, "long_entry_signal"), (baseline.SHORT, "short_entry_signal")):
                if not bool(features[column].iloc[position]):
                    continue
                context = baseline._signal_context(source_frame, features, position, side)
                if survivor_filter._matches_target_cluster(symbol, context):
                    features.loc[features.index[position], column] = False
                    continue
                if not gate_enabled or not invalid_counter_break(context, side):
                    continue
                features.loc[features.index[position], column] = False
                blocked.append({
                    "bar": position,
                    "timestamp": baseline._timestamp(source_frame, position),
                    "symbol": source.norm_symbol(symbol),
                    "side": side,
                    "reason": REJECT_REASON,
                    "trigger_components": list(context.get("trigger_components", [])),
                    "confirmation_components": list(context.get("confirmation_components", [])),
                    "structure_valid": bool(context.get("structure_valid")),
                    "confluence_count": int(context.get("confluence_count", 0) or 0),
                    "confluence_signature": context.get("confluence_signature"),
                    "future_data_used": False,
                })
        return features

    baseline.compute_features = filtered_compute
    try:
        replay = baseline.run_replay(
            frame,
            symbol=symbol,
            timeframe=source.INTERVAL,
            replay_fold_id=fold_id,
            cost_bps_per_side=cost_bps_per_side,
        )
    finally:
        baseline.compute_features = original_compute
    replay["policy_id"] = POLICY_ID if gate_enabled else survivor_filter.POLICY_ID
    replay["contract_gate_enabled"] = gate_enabled
    replay["contract_gate_blocked_entry_signal_count"] = len(blocked)
    replay["contract_gate_blocked_entry_signals"] = blocked
    return replay


def load_window(
    data_dir: Path,
    symbols: Sequence[str],
    fold_prefix: str,
    cost_bps_per_side: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    control_trades: List[Dict[str, Any]] = []
    candidate_trades: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for symbol in symbols:
        try:
            frame = shared._load_frame(data_dir / f"{symbol.lower()}_15m.csv")
            control = run_replay(frame, symbol=symbol, fold_id=f"{fold_prefix}_CONTROL", cost_bps_per_side=cost_bps_per_side, gate_enabled=False)
            candidate = run_replay(frame, symbol=symbol, fold_id=f"{fold_prefix}_CANDIDATE", cost_bps_per_side=cost_bps_per_side, gate_enabled=True)
            c0 = [dict(v) for v in control.get("trades", []) if isinstance(v, Mapping)]
            c1 = [dict(v) for v in candidate.get("trades", []) if isinstance(v, Mapping)]
            s0, s1 = stats(c0), stats(c1)
            control_trades.extend(c0)
            candidate_trades.extend(c1)
            rows.append({
                "symbol": symbol,
                "status": "PASS",
                "control": s0,
                "candidate": s1,
                "blocked_entry_signal_count": candidate.get("contract_gate_blocked_entry_signal_count", 0),
                "net_delta_pct": float(s1["net_return_pct_sum"]) - float(s0["net_return_pct_sum"]),
                "win_rate_delta_pp": delta(s1.get("win_rate_pct"), s0.get("win_rate_pct")),
                "pf_delta": delta(s1.get("net_profit_factor"), s0.get("net_profit_factor")),
            })
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            rows.append({"symbol": symbol, "status": "HOLD", "error": error})
    return control_trades, candidate_trades, rows, blockers


def summarize(control: Sequence[Mapping[str, Any]], candidate: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    s0, s1 = stats(control), stats(candidate)
    retention = None
    if finite(s0.get("payoff_ratio_pct")) and finite(s1.get("payoff_ratio_pct")) and float(s0["payoff_ratio_pct"]) != 0.0:
        retention = float(s1["payoff_ratio_pct"]) / float(s0["payoff_ratio_pct"])
    positive = sum(
        1 for row in rows
        if row.get("status") == "PASS" and float(row["candidate"]["net_return_pct_sum"]) > 0.0
    )
    causal = bool(
        float(s1["net_return_pct_sum"]) > float(s0["net_return_pct_sum"])
        and (s1.get("net_profit_factor") or 0.0) > (s0.get("net_profit_factor") or 0.0)
        and (s1.get("win_rate_pct") or 0.0) > (s0.get("win_rate_pct") or 0.0)
        and retention is not None and retention >= 0.95
    )
    strict = bool(
        float(s1["net_return_pct_sum"]) > 0.0
        and (s1.get("net_profit_factor") or 0.0) > 1.0
        and (s1.get("win_rate_pct") or 0.0) - (s0.get("win_rate_pct") or 0.0) >= 2.0
        and retention is not None and retention >= 0.95
        and positive >= 4
    )
    return {
        "control": s0,
        "candidate": s1,
        "blocked_entry_signal_count": sum(int(row.get("blocked_entry_signal_count", 0) or 0) for row in rows),
        "trade_count_delta": int(s1["trade_count"]) - int(s0["trade_count"]),
        "win_count_delta": int(s1["win_count"]) - int(s0["win_count"]),
        "loss_count_delta": int(s1["loss_count"]) - int(s0["loss_count"]),
        "win_rate_delta_pp": delta(s1.get("win_rate_pct"), s0.get("win_rate_pct")),
        "net_return_delta_pct": float(s1["net_return_pct_sum"]) - float(s0["net_return_pct_sum"]),
        "net_pf_delta": delta(s1.get("net_profit_factor"), s0.get("net_profit_factor")),
        "payoff_retention": retention,
        "positive_symbol_count_candidate": positive,
        "causal_improvement": causal,
        "strict_survivor": strict,
    }


def parity(summary: Mapping[str, Any], expected: Tuple[int, int, int]) -> bool:
    values = summary["control"]
    return (
        int(values.get("trade_count", -1)),
        int(values.get("win_count", -1)),
        int(values.get("loss_count", -1)),
    ) == expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-window full replay of one source-derived counter-trend breakout pullback contract gate.")
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()
    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    symbols = list(dict.fromkeys(source.norm_symbol(v) for v in args.symbols.split(",") if v.strip()))
    first0, first1, first_rows, first_blockers = load_window(root / "runtime" / FIRST_DATA_DIRNAME, symbols, "FIRST_COUNTER_BREAK_CONTRACT", args.cost_bps_per_side)
    second0, second1, second_rows, second_blockers = load_window(root / "runtime" / SECOND_DATA_DIRNAME, symbols, "SECOND_COUNTER_BREAK_CONTRACT", args.cost_bps_per_side)
    first = summarize(first0, first1, first_rows)
    second = summarize(second0, second1, second_rows)
    combined = summarize(first0 + second0, first1 + second1, first_rows + second_rows)
    blockers = list(first_blockers) + list(second_blockers)
    first_parity, second_parity = parity(first, EXPECTED_FIRST), parity(second, EXPECTED_SECOND)
    if not first_parity:
        blockers.append(f"FIRST_PARITY:{first['control']}")
    if not second_parity:
        blockers.append(f"SECOND_PARITY:{second['control']}")

    data_pass = not blockers and first_parity and second_parity
    two_window_causal = bool(first["causal_improvement"] and second["causal_improvement"])
    two_window_strict = bool(first["strict_survivor"] and second["strict_survivor"])
    if not data_pass:
        state, next_stage = "HOLD_R7A4D_COUNTER_BREAK_CONTRACT_DATA_OR_PARITY_FAIL", "REPAIR_REPLAY_PARITY_ONLY"
    elif two_window_strict:
        state, next_stage = "PASS_R7A4D_COUNTER_BREAK_CONTRACT_TWO_WINDOW_SURVIVOR", "FREEZE_CHILD_AND_RUN_THIRD_UNSEEN_OOS"
    elif two_window_causal:
        state, next_stage = "PASS_R7A4D_COUNTER_BREAK_CONTRACT_CAUSAL_IMPROVEMENT_NOT_SURVIVOR", "DECOMPOSE_REMAINING_COUNTER_BREAK_WINNERS_AND_LOSSES_READ_ONLY"
    else:
        state, next_stage = "FAIL_R7A4D_COUNTER_BREAK_CONTRACT_NO_CROSS_WINDOW_RECOVERY", "ROLLBACK_CHILD_KEEP_FROZEN_SURVIVOR"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "policy_id": POLICY_ID,
        "target_sha": args.target_sha,
        "symbols": symbols,
        "cost_bps_per_side": args.cost_bps_per_side,
        "source_contract": {
            "target": "counter_trend_break_up auxiliary confirmation-edge-only route",
            "reject_when": "structure_valid=false OR confluence_count<2",
            "preserved_routes": ["supertrend_flip", "dema_cross", "short counter_trend_break_down"],
            "decision_time": "confirmed signal bar close",
            "future_data_used": False,
            "unknowns_not_invented": ["pivot_lookback", "touch_tolerance", "trendline_break_tolerance"],
        },
        "first_control_count_parity": first_parity,
        "second_control_count_parity": second_parity,
        "first_window": first,
        "second_window": second,
        "combined": combined,
        "first_symbol_results": first_rows,
        "second_symbol_results": second_rows,
        "two_window_causal_improvement": two_window_causal,
        "two_window_strict_survivor": two_window_strict,
        "blockers": blockers,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "next_stage": next_stage,
    }
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "summary_v1.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"STATE={state}")
    print(f"PASSED_FIRST_SYMBOLS={sum(row.get('status') == 'PASS' for row in first_rows)}/{len(symbols)}")
    print(f"PASSED_SECOND_SYMBOLS={sum(row.get('status') == 'PASS' for row in second_rows)}/{len(symbols)}")
    print(f"FIRST_CONTROL_COUNT_PARITY={str(first_parity).lower()}")
    print(f"SECOND_CONTROL_COUNT_PARITY={str(second_parity).lower()}")
    print(f"FIRST_BLOCKED_ENTRY_SIGNALS={first['blocked_entry_signal_count']}")
    print(f"SECOND_BLOCKED_ENTRY_SIGNALS={second['blocked_entry_signal_count']}")
    for name, row in (("FIRST", first), ("SECOND", second)):
        print(f"{name}_CONTROL_TRADES={row['control']['trade_count']}")
        print(f"{name}_CANDIDATE_TRADES={row['candidate']['trade_count']}")
        print(f"{name}_CONTROL_WIN_RATE_PCT={row['control']['win_rate_pct']}")
        print(f"{name}_CANDIDATE_WIN_RATE_PCT={row['candidate']['win_rate_pct']}")
        print(f"{name}_CONTROL_NET_RETURN_PCT_SUM={row['control']['net_return_pct_sum']:.6f}")
        print(f"{name}_CANDIDATE_NET_RETURN_PCT_SUM={row['candidate']['net_return_pct_sum']:.6f}")
        print(f"{name}_CONTROL_NET_PF={row['control']['net_profit_factor']}")
        print(f"{name}_CANDIDATE_NET_PF={row['candidate']['net_profit_factor']}")
        print(f"{name}_CONTROL_PAYOFF_RATIO={row['control']['payoff_ratio_pct']}")
        print(f"{name}_CANDIDATE_PAYOFF_RATIO={row['candidate']['payoff_ratio_pct']}")
        print(f"{name}_POSITIVE_SYMBOLS={row['positive_symbol_count_candidate']}/{len(symbols)}")
    print(f"TWO_WINDOW_CAUSAL_IMPROVEMENT={str(two_window_causal).lower()}")
    print(f"TWO_WINDOW_STRICT_SURVIVOR={str(two_window_strict).lower()}")
    print(f"OUTPUT={output}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
