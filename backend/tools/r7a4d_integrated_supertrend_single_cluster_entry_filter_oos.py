from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_pullback_replay as baseline

OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_single_cluster_entry_filter_oos_v1"
BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
POLICY_ID = "reject_short_confirmation_edge_sr_touch_plus_trendline_touch_v1"
TARGET_SIDE = baseline.SHORT
TARGET_TRIGGER_SIGNATURE = "confirmation_edge"
TARGET_CONFLUENCE_SIGNATURE = "sr_touch+trendline_touch"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _pf(values: List[float]) -> Optional[float]:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON_NOT_FOUND:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return value


def _load_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"BASELINE_CSV_NOT_FOUND:{path}")
    frame = pd.read_csv(path)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    return frame


def _matches_target_cluster(context: Mapping[str, Any]) -> bool:
    return (
        str(context.get("side")) == TARGET_SIDE
        and str(context.get("trigger_signature")) == TARGET_TRIGGER_SIGNATURE
        and str(context.get("confluence_signature")) == TARGET_CONFLUENCE_SIGNATURE
    )


def _run_filtered_replay(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    replay_fold_id: str,
    cost_bps_per_side: float,
) -> Dict[str, Any]:
    original_compute: Callable[..., pd.DataFrame] = baseline.compute_features
    blocked: List[Dict[str, Any]] = []

    def filtered_compute(source_frame: pd.DataFrame, cfg: Any) -> pd.DataFrame:
        features = original_compute(source_frame, cfg).copy()
        for position in range(len(features)):
            if not bool(features["short_entry_signal"].iloc[position]):
                continue
            context = baseline._signal_context(source_frame, features, position, baseline.SHORT)
            if not _matches_target_cluster(context):
                continue
            features.loc[features.index[position], "short_entry_signal"] = False
            blocked.append(
                {
                    "bar": position,
                    "timestamp": baseline._timestamp(source_frame, position),
                    "symbol": symbol,
                    "side": baseline.SHORT,
                    "trigger_signature": context["trigger_signature"],
                    "confirmation_signature": context["confirmation_signature"],
                    "confluence_signature": context["confluence_signature"],
                    "dema_distance_atr": context.get("dema_distance_atr"),
                    "rsi14": context.get("rsi14"),
                }
            )
        return features

    baseline.compute_features = filtered_compute
    try:
        replay = baseline.run_replay(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            replay_fold_id=replay_fold_id,
            cost_bps_per_side=cost_bps_per_side,
        )
    finally:
        baseline.compute_features = original_compute

    replay["replay_profile_id"] = "integrated_supertrend_single_cluster_entry_filter_replay_v1"
    replay["single_causal_entry_filter"] = True
    replay["entry_filter_policy_id"] = POLICY_ID
    replay["entry_filter_definition"] = {
        "side": TARGET_SIDE,
        "trigger_signature": TARGET_TRIGGER_SIGNATURE,
        "confluence_signature": TARGET_CONFLUENCE_SIGNATURE,
        "symbol_specific": False,
        "exit_reason_used": False,
        "future_data_used": False,
    }
    replay["blocked_entry_signal_count"] = len(blocked)
    replay["blocked_entry_signals"] = blocked
    return replay


def _summary_metrics(replays: List[Mapping[str, Any]]) -> Dict[str, Any]:
    trades = [
        trade
        for replay in replays
        for trade in replay.get("trades", [])
        if isinstance(trade, Mapping)
    ]
    gross = [float(trade["gross_return_pct"]) for trade in trades]
    net = [float(trade["net_return_pct"]) for trade in trades]
    wins = sum(value > 0 for value in net)
    symbol_net = {
        str(replay.get("symbol")): float(replay.get("net_return_pct", 0.0))
        for replay in replays
    }
    return {
        "trade_count": len(trades),
        "win_count": wins,
        "win_rate_pct": wins / len(trades) * 100.0 if trades else None,
        "gross_return_pct_sum": sum(gross),
        "net_return_pct_sum": sum(net),
        "gross_profit_factor": _pf(gross),
        "net_profit_factor": _pf(net),
        "positive_symbol_count": sum(value > 0 for value in symbol_net.values()),
        "symbol_net_return_pct": symbol_net,
    }


def _close_enough(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if not _finite(left) or not _finite(right):
        return False
    return abs(float(left) - float(right)) <= tolerance


def _baseline_invariant(replay: Mapping[str, Any], stored: Mapping[str, Any]) -> Dict[str, Any]:
    checks = {
        "trade_count": int(replay.get("trade_count", -1)) == int(stored.get("trade_count", -2)),
        "gross_return_pct": _close_enough(replay.get("gross_return_pct"), stored.get("gross_return_pct")),
        "net_return_pct": _close_enough(replay.get("net_return_pct"), stored.get("net_return_pct")),
        "gross_profit_factor": _close_enough(replay.get("gross_profit_factor"), stored.get("gross_profit_factor")),
        "net_profit_factor": _close_enough(replay.get("net_profit_factor"), stored.get("net_profit_factor")),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def _strictly_better(candidate: Any, baseline_value: Any) -> bool:
    return _finite(candidate) and _finite(baseline_value) and float(candidate) > float(baseline_value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only same-window OOS test of one pre-entry cluster filter: "
            "short confirmation_edge at exact sr_touch+trendline_touch confluence"
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.cost_bps_per_side < 0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    baseline_dir = root / "runtime" / BASELINE_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(source.norm_symbol(item) for item in args.symbols.split(",") if item.strip())
    )

    baseline_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    blockers: List[str] = []
    total_blocked = 0

    for symbol in symbols:
        try:
            csv_path = baseline_dir / f"{symbol.lower()}_15m.csv"
            stored_replay_path = baseline_dir / f"{symbol.lower()}_replay.json"
            frame = _load_frame(csv_path)
            stored_replay = _load_json(stored_replay_path)

            same_window_baseline = baseline.run_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_BASELINE_RECHECK",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            invariant = _baseline_invariant(same_window_baseline, stored_replay)
            if invariant["status"] != "PASS":
                raise RuntimeError(f"BASELINE_INVARIANT_FAILED:{symbol}:{invariant['checks']}")

            candidate = _run_filtered_replay(
                frame,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id="BINGX_REAL_OOS_FIXED_WINDOW_SINGLE_CLUSTER_FILTER",
                cost_bps_per_side=args.cost_bps_per_side,
            )
            blocked = int(candidate["blocked_entry_signal_count"])
            total_blocked += blocked
            baseline_replays.append(same_window_baseline)
            candidate_replays.append(candidate)
            source.atomic_json(output_dir / f"{symbol.lower()}_candidate_replay.json", candidate)
            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "csv": str(csv_path),
                    "baseline_invariant": invariant,
                    "blocked_entry_signal_count": blocked,
                    "baseline_trade_count": same_window_baseline["trade_count"],
                    "candidate_trade_count": candidate["trade_count"],
                    "baseline_gross_return_pct": same_window_baseline["gross_return_pct"],
                    "candidate_gross_return_pct": candidate["gross_return_pct"],
                    "baseline_net_return_pct": same_window_baseline["net_return_pct"],
                    "candidate_net_return_pct": candidate["net_return_pct"],
                    "baseline_gross_profit_factor": same_window_baseline["gross_profit_factor"],
                    "candidate_gross_profit_factor": candidate["gross_profit_factor"],
                    "baseline_net_profit_factor": same_window_baseline["net_profit_factor"],
                    "candidate_net_profit_factor": candidate["net_profit_factor"],
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    baseline_metrics = _summary_metrics(baseline_replays)
    candidate_metrics = _summary_metrics(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers
    causal_improvement = bool(
        data_pass
        and total_blocked > 0
        and candidate_metrics["trade_count"] < baseline_metrics["trade_count"]
        and _strictly_better(candidate_metrics["gross_return_pct_sum"], baseline_metrics["gross_return_pct_sum"])
        and _strictly_better(candidate_metrics["gross_profit_factor"], baseline_metrics["gross_profit_factor"])
        and _strictly_better(candidate_metrics["net_return_pct_sum"], baseline_metrics["net_return_pct_sum"])
        and _strictly_better(candidate_metrics["net_profit_factor"], baseline_metrics["net_profit_factor"])
    )
    economic_survivor = bool(
        causal_improvement
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and candidate_metrics["net_profit_factor"] is not None
        and candidate_metrics["net_profit_factor"] > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )

    if economic_survivor:
        state = "PASS_R7A4D_SINGLE_CLUSTER_ENTRY_FILTER_ECONOMIC_SURVIVOR"
        next_stage = "FREEZE_FILTER_AND_RUN_SECOND_NONOVERLAPPING_OOS"
    elif causal_improvement:
        state = "HOLD_R7A4D_SINGLE_CLUSTER_ENTRY_FILTER_CAUSAL_IMPROVEMENT_NOT_SURVIVOR"
        next_stage = "SELECT_ONE_REMAINING_PRE_ENTRY_LOSS_CLUSTER_ONLY"
    else:
        state = "HOLD_R7A4D_SINGLE_CLUSTER_ENTRY_FILTER_NO_CAUSAL_IMPROVEMENT"
        next_stage = "REJECT_FILTER_AND_AUDIT_SUPERTREND_TRAILING_EXIT_CAPTURE"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "single_causal_repair": True,
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "target_sha": args.target_sha,
        "source_directory": str(baseline_dir),
        "output_directory": str(output_dir),
        "source": "existing BingX public 15m fixed-window baseline CSVs",
        "interval": source.INTERVAL,
        "symbols": symbols,
        "cost_bps_per_side": args.cost_bps_per_side,
        "entry_filter_policy_id": POLICY_ID,
        "entry_filter_definition": {
            "side": TARGET_SIDE,
            "trigger_signature": TARGET_TRIGGER_SIGNATURE,
            "confluence_signature": TARGET_CONFLUENCE_SIGNATURE,
            "symbol_specific": False,
            "exit_reason_used": False,
            "future_data_used": False,
        },
        "blocked_entry_signal_count": total_blocked,
        "results": results,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "delta": {
            "trade_count": candidate_metrics["trade_count"] - baseline_metrics["trade_count"],
            "gross_return_pct_sum": candidate_metrics["gross_return_pct_sum"] - baseline_metrics["gross_return_pct_sum"],
            "net_return_pct_sum": candidate_metrics["net_return_pct_sum"] - baseline_metrics["net_return_pct_sum"],
            "gross_profit_factor": (
                candidate_metrics["gross_profit_factor"] - baseline_metrics["gross_profit_factor"]
                if _finite(candidate_metrics["gross_profit_factor"]) and _finite(baseline_metrics["gross_profit_factor"])
                else None
            ),
            "net_profit_factor": (
                candidate_metrics["net_profit_factor"] - baseline_metrics["net_profit_factor"]
                if _finite(candidate_metrics["net_profit_factor"]) and _finite(baseline_metrics["net_profit_factor"])
                else None
            ),
            "positive_symbol_count": candidate_metrics["positive_symbol_count"] - baseline_metrics["positive_symbol_count"],
        },
        "causal_improvement": causal_improvement,
        "economic_survivor": economic_survivor,
        "blockers": blockers,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"BLOCKED_ENTRY_SIGNALS={total_blocked}")
    print(f"BASELINE_TRADES={baseline_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(f"BASELINE_GROSS_RETURN_PCT_SUM={baseline_metrics['gross_return_pct_sum']:.6f}")
    print(f"CANDIDATE_GROSS_RETURN_PCT_SUM={candidate_metrics['gross_return_pct_sum']:.6f}")
    print(f"BASELINE_NET_RETURN_PCT_SUM={baseline_metrics['net_return_pct_sum']:.6f}")
    print(f"CANDIDATE_NET_RETURN_PCT_SUM={candidate_metrics['net_return_pct_sum']:.6f}")
    print(f"BASELINE_GROSS_PF={baseline_metrics['gross_profit_factor']}")
    print(f"CANDIDATE_GROSS_PF={candidate_metrics['gross_profit_factor']}")
    print(f"BASELINE_NET_PF={baseline_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(f"POSITIVE_SYMBOLS={candidate_metrics['positive_symbol_count']}/{len(symbols)}")
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(f"ECONOMIC_SURVIVOR={str(economic_survivor).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"RC={0 if data_pass else 2}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
