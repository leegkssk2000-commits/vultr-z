from __future__ import annotations

import argparse
import json
import math
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

import r7a4d_integrated_supertrend_bingx_real_oos as source
import r7a4d_integrated_supertrend_pullback_replay as baseline
import r7a4d_integrated_supertrend_single_cluster_entry_filter_oos as frozen


OUTPUT_DIRNAME = "r7a4d_integrated_supertrend_second_nonoverlap_oos_v1"
FIRST_BASELINE_DIRNAME = "r7a4d_integrated_supertrend_bingx_real_oos_v1"
FIRST_FILTER_DIRNAME = "r7a4d_integrated_supertrend_single_cluster_entry_filter_oos_v1"
SECOND_FOLD_BASELINE = "BINGX_REAL_OOS_PRECEDING_WINDOW_BASELINE"
SECOND_FOLD_FILTERED = "BINGX_REAL_OOS_PRECEDING_WINDOW_FROZEN_FILTER"


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON_NOT_FOUND:{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return value


def _timestamp_ms(value: Any) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return int(timestamp.timestamp() * 1000)


def _window_contract(path: Path) -> Dict[str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"FIRST_WINDOW_CSV_NOT_FOUND:{path}")
    frame = pd.read_csv(path, usecols=["timestamp"])
    if frame.empty:
        raise ValueError(f"FIRST_WINDOW_EMPTY:{path}")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    timestamp_ms = (timestamps.astype("int64") // 1_000_000).astype("int64")
    if timestamp_ms.duplicated().any():
        raise ValueError(f"FIRST_WINDOW_DUPLICATE_TIMESTAMP:{path}")
    if not bool((timestamp_ms.diff().dropna() == source.INTERVAL_MS).all()):
        raise ValueError(f"FIRST_WINDOW_GAP_OR_WRONG_INTERVAL:{path}")
    return {
        "rows": int(len(frame)),
        "start_ms": int(timestamp_ms.iloc[0]),
        "end_ms": int(timestamp_ms.iloc[-1]),
    }


def _payload_rows(payload: Mapping[str, Any]) -> List[Any]:
    data: Any = payload.get("data")
    if isinstance(data, dict):
        data = next(
            (
                data[key]
                for key in ("data", "rows", "klines", "list")
                if isinstance(data.get(key), list)
            ),
            [],
        )
    return data if isinstance(data, list) else []


def _fetch_exact_window(
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
    expected_rows: int,
) -> Tuple[pd.DataFrame, str, int]:
    if end_ms < start_ms:
        raise ValueError("WINDOW_REVERSED")
    calculated_rows = ((end_ms - start_ms) // source.INTERVAL_MS) + 1
    if calculated_rows != expected_rows:
        raise ValueError(f"WINDOW_ROW_CONTRACT:{calculated_rows}!={expected_rows}")

    request_start = start_ms - source.INTERVAL_MS
    request_end = end_ms + source.INTERVAL_MS
    max_requests = max(
        8,
        math.ceil((expected_rows + 2) / max(source.REQUEST_LIMIT - 1, 1)) + 4,
    )
    errors: List[str] = []

    for endpoint in source.ENDPOINTS:
        try:
            found: Dict[int, Tuple[int, float, float, float, float, float]] = {}
            cursor = request_start
            request_count = 0

            while cursor <= request_end and request_count < max_requests:
                window_end = min(
                    request_end,
                    cursor + source.REQUEST_LIMIT * source.INTERVAL_MS,
                )
                query = urllib.parse.urlencode(
                    {
                        "symbol": symbol[:-4] + "-USDT",
                        "interval": source.INTERVAL,
                        "limit": source.REQUEST_LIMIT,
                        "startTime": cursor,
                        "endTime": window_end,
                    }
                )
                payload = source.request_json(endpoint + "?" + query)
                if payload.get("code") not in (None, 0, "0"):
                    raise RuntimeError(
                        f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}"
                    )

                page = [
                    item
                    for item in (
                        source.parse_row(row) for row in _payload_rows(payload)
                    )
                    if item is not None
                ]
                request_count += 1
                if not page:
                    raise ValueError(f"EMPTY_PAGE:{cursor}:{window_end}")

                for item in page:
                    if start_ms <= item[0] <= end_ms:
                        found[item[0]] = item

                if (
                    len(found) >= expected_rows
                    and min(found) == start_ms
                    and max(found) == end_ms
                ):
                    break

                max_seen = max(item[0] for item in page)
                if max_seen <= cursor:
                    raise ValueError(f"PAGINATION_STALLED:{cursor}:{max_seen}")
                cursor = max_seen

            frame = pd.DataFrame(
                [found[key] for key in sorted(found)],
                columns=("timestamp_ms", "open", "high", "low", "close", "volume"),
            )
            source.validate(frame, expected_rows)
            if int(frame["timestamp_ms"].iloc[0]) != start_ms:
                raise ValueError("WINDOW_START_MISMATCH")
            if int(frame["timestamp_ms"].iloc[-1]) != end_ms:
                raise ValueError("WINDOW_END_MISMATCH")
            frame["timestamp"] = pd.to_datetime(
                frame["timestamp_ms"], unit="ms", utc=True
            )
            return frame, endpoint, request_count
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")

    raise RuntimeError("BINGX_EXACT_WINDOW_FAILED:" + "|".join(errors))


def _pf(values: List[float]) -> Optional[float]:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


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


def _strictly_better(candidate: Any, baseline_value: Any) -> bool:
    return (
        _finite(candidate)
        and _finite(baseline_value)
        and float(candidate) > float(baseline_value)
    )


def _metric_delta(candidate: Any, baseline_value: Any) -> Optional[float]:
    if not _finite(candidate) or not _finite(baseline_value):
        return None
    return float(candidate) - float(baseline_value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the surviving single-cluster entry filter and test it on the "
            "immediately preceding, fully non-overlapping BingX public 15m window."
        )
    )
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--symbols", default=",".join(source.SYMBOLS))
    parser.add_argument("--warmup-bars", type=int, default=400)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()

    if args.warmup_bars < 250:
        raise ValueError("WARMUP_BARS_INVALID")
    if args.cost_bps_per_side < 0:
        raise ValueError("COST_BPS_INVALID")

    root = Path(args.root).resolve()
    first_baseline_dir = root / "runtime" / FIRST_BASELINE_DIRNAME
    first_filter_dir = root / "runtime" / FIRST_FILTER_DIRNAME
    output_dir = root / "runtime" / OUTPUT_DIRNAME
    symbols = list(
        dict.fromkeys(
            source.norm_symbol(item)
            for item in args.symbols.split(",")
            if item.strip()
        )
    )

    blockers: List[str] = []
    results: List[Dict[str, Any]] = []
    baseline_replays: List[Dict[str, Any]] = []
    candidate_replays: List[Dict[str, Any]] = []
    total_blocked = 0
    first_summary: Dict[str, Any] = {}

    try:
        first_summary = _load_json(first_filter_dir / "summary_v1.json")
        if not bool(first_summary.get("economic_survivor")):
            raise RuntimeError("FIRST_WINDOW_FILTER_NOT_ECONOMIC_SURVIVOR")
        if str(first_summary.get("entry_filter_policy_id")) != frozen.POLICY_ID:
            raise RuntimeError("FROZEN_POLICY_ID_MISMATCH")
        if int(first_summary.get("canonical_strategy_count", 0)) != 1:
            raise RuntimeError("FIRST_WINDOW_CANONICAL_STRATEGY_COUNT_INVALID")
    except Exception as exc:
        blockers.append(f"FIRST_WINDOW_SUMMARY:{type(exc).__name__}:{exc}")

    for symbol in symbols:
        try:
            first_csv = first_baseline_dir / f"{symbol.lower()}_15m.csv"
            first_window = _window_contract(first_csv)
            second_end_ms = first_window["start_ms"] - source.INTERVAL_MS
            second_start_ms = (
                second_end_ms
                - (first_window["rows"] - 1) * source.INTERVAL_MS
            )
            non_overlap = second_end_ms < first_window["start_ms"]
            if not non_overlap:
                raise RuntimeError("WINDOW_OVERLAP_DETECTED")

            raw, endpoint, request_count = _fetch_exact_window(
                symbol,
                start_ms=second_start_ms,
                end_ms=second_end_ms,
                expected_rows=first_window["rows"],
            )
            enriched = source.geometry(raw, args.warmup_bars)
            prefix_checks = source.prefix_check(raw, args.warmup_bars)

            csv_path = output_dir / f"{symbol.lower()}_15m.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            enriched.to_csv(csv_path, index=False)

            same_window_baseline = baseline.run_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=SECOND_FOLD_BASELINE,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            candidate = frozen._run_filtered_replay(
                enriched,
                symbol=symbol,
                timeframe=source.INTERVAL,
                replay_fold_id=SECOND_FOLD_FILTERED,
                cost_bps_per_side=args.cost_bps_per_side,
            )

            blocked = int(candidate.get("blocked_entry_signal_count", 0))
            total_blocked += blocked
            baseline_replays.append(same_window_baseline)
            candidate_replays.append(candidate)
            source.atomic_json(
                output_dir / f"{symbol.lower()}_baseline_replay.json",
                same_window_baseline,
            )
            source.atomic_json(
                output_dir / f"{symbol.lower()}_candidate_replay.json",
                candidate,
            )

            results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "endpoint": endpoint,
                    "request_count": request_count,
                    "prefix_checks": prefix_checks,
                    "rows": len(enriched),
                    "first_window_start_ms": first_window["start_ms"],
                    "first_window_end_ms": first_window["end_ms"],
                    "second_window_start_ms": second_start_ms,
                    "second_window_end_ms": second_end_ms,
                    "non_overlap": non_overlap,
                    "blocked_entry_signal_count": blocked,
                    "baseline_trade_count": same_window_baseline["trade_count"],
                    "candidate_trade_count": candidate["trade_count"],
                    "baseline_net_return_pct": same_window_baseline["net_return_pct"],
                    "candidate_net_return_pct": candidate["net_return_pct"],
                    "baseline_net_profit_factor": same_window_baseline[
                        "net_profit_factor"
                    ],
                    "candidate_net_profit_factor": candidate["net_profit_factor"],
                    "csv": str(csv_path),
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            results.append({"symbol": symbol, "status": "HOLD", "error": error})

    baseline_metrics = _summary_metrics(baseline_replays)
    candidate_metrics = _summary_metrics(candidate_replays)
    data_pass = len(candidate_replays) == len(symbols) and not blockers
    all_nonoverlap = bool(
        data_pass
        and all(bool(result.get("non_overlap")) for result in results)
    )
    causal_improvement = bool(
        data_pass
        and all_nonoverlap
        and total_blocked > 0
        and candidate_metrics["trade_count"] < baseline_metrics["trade_count"]
        and _strictly_better(
            candidate_metrics["gross_return_pct_sum"],
            baseline_metrics["gross_return_pct_sum"],
        )
        and _strictly_better(
            candidate_metrics["gross_profit_factor"],
            baseline_metrics["gross_profit_factor"],
        )
        and _strictly_better(
            candidate_metrics["net_return_pct_sum"],
            baseline_metrics["net_return_pct_sum"],
        )
        and _strictly_better(
            candidate_metrics["net_profit_factor"],
            baseline_metrics["net_profit_factor"],
        )
    )
    second_oos_economic_survivor = bool(
        causal_improvement
        and candidate_metrics["net_return_pct_sum"] > 0.0
        and candidate_metrics["net_profit_factor"] is not None
        and candidate_metrics["net_profit_factor"] > 1.0
        and candidate_metrics["positive_symbol_count"] >= 3
    )
    two_window_confirmed = bool(
        bool(first_summary.get("economic_survivor"))
        and second_oos_economic_survivor
    )

    if two_window_confirmed:
        state = "PASS_R7A4D_FROZEN_FILTER_SECOND_NONOVERLAP_OOS"
        next_stage = "RUN_THIRD_NONOVERLAPPING_OOS_OR_SHADOW_READINESS_GATE"
    elif causal_improvement:
        state = "HOLD_R7A4D_SECOND_OOS_IMPROVED_BUT_NOT_ECONOMIC_SURVIVOR"
        next_stage = "REJECT_PROMOTION_AND_AUDIT_SECOND_WINDOW_LOSS_CONCENTRATION"
    else:
        state = "HOLD_R7A4D_FROZEN_FILTER_FAILED_SECOND_NONOVERLAP_OOS"
        next_stage = "ROLLBACK_FILTER_CANDIDACY_AND_SELECT_NEW_SINGLE_CAUSAL_CLUSTER"

    summary = {
        "state": state,
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "strategy_id": "integrated_supertrend_pullback_v1",
        "canonical_strategy_count": 1,
        "frozen_filter_policy_id": frozen.POLICY_ID,
        "frozen_filter_definition": {
            "side": frozen.TARGET_SIDE,
            "trigger_signature": frozen.TARGET_TRIGGER_SIGNATURE,
            "confluence_signature": frozen.TARGET_CONFLUENCE_SIGNATURE,
            "symbol_specific": False,
            "exit_reason_used": False,
            "future_data_used": False,
        },
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "shadow_started": False,
        "paper_live_order_allowed": False,
        "target_sha": args.target_sha,
        "source": "BingX public 15m immediately preceding fixed window",
        "interval": source.INTERVAL,
        "symbols": symbols,
        "warmup_bars": args.warmup_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "results": results,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "delta": {
            "trade_count": (
                candidate_metrics["trade_count"] - baseline_metrics["trade_count"]
            ),
            "gross_return_pct_sum": (
                candidate_metrics["gross_return_pct_sum"]
                - baseline_metrics["gross_return_pct_sum"]
            ),
            "net_return_pct_sum": (
                candidate_metrics["net_return_pct_sum"]
                - baseline_metrics["net_return_pct_sum"]
            ),
            "gross_profit_factor": _metric_delta(
                candidate_metrics["gross_profit_factor"],
                baseline_metrics["gross_profit_factor"],
            ),
            "net_profit_factor": _metric_delta(
                candidate_metrics["net_profit_factor"],
                baseline_metrics["net_profit_factor"],
            ),
            "positive_symbol_count": (
                candidate_metrics["positive_symbol_count"]
                - baseline_metrics["positive_symbol_count"]
            ),
        },
        "blocked_entry_signal_count": total_blocked,
        "all_windows_nonoverlapping": all_nonoverlap,
        "causal_improvement": causal_improvement,
        "second_oos_economic_survivor": second_oos_economic_survivor,
        "first_oos_economic_survivor": bool(first_summary.get("economic_survivor")),
        "two_window_confirmed": two_window_confirmed,
        "blockers": blockers,
        "performance_claim_allowed": False,
        "promotion_allowed": False,
        "next_stage": next_stage,
    }
    source.atomic_json(output_dir / "summary_v1.json", summary)

    print(f"STATE={state}")
    print(f"PASSED_SYMBOLS={len(candidate_replays)}/{len(symbols)}")
    print(f"ALL_WINDOWS_NONOVERLAPPING={str(all_nonoverlap).lower()}")
    print(f"BLOCKED_ENTRY_SIGNALS={total_blocked}")
    print(f"BASELINE_TRADES={baseline_metrics['trade_count']}")
    print(f"CANDIDATE_TRADES={candidate_metrics['trade_count']}")
    print(
        f"BASELINE_NET_RETURN_PCT_SUM="
        f"{baseline_metrics['net_return_pct_sum']:.6f}"
    )
    print(
        f"CANDIDATE_NET_RETURN_PCT_SUM="
        f"{candidate_metrics['net_return_pct_sum']:.6f}"
    )
    print(f"BASELINE_NET_PF={baseline_metrics['net_profit_factor']}")
    print(f"CANDIDATE_NET_PF={candidate_metrics['net_profit_factor']}")
    print(
        f"POSITIVE_SYMBOLS={candidate_metrics['positive_symbol_count']}/"
        f"{len(symbols)}"
    )
    print(f"CAUSAL_IMPROVEMENT={str(causal_improvement).lower()}")
    print(
        f"SECOND_OOS_ECONOMIC_SURVIVOR="
        f"{str(second_oos_economic_survivor).lower()}"
    )
    print(f"TWO_WINDOW_CONFIRMED={str(two_window_confirmed).lower()}")
    print(f"SUMMARY_JSON={output_dir / 'summary_v1.json'}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"RC={0 if data_pass else 2}")
    return 0 if data_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
